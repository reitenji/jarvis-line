import AppKit
import SwiftUI

@MainActor
final class SetupAssistantModel: ObservableObject {
    enum Step: Int, CaseIterable {
        case welcome
        case language
        case voice
        case speech
        case agent
        case review
        case applying
        case complete

        var title: String {
            switch self {
            case .welcome: return "Welcome"
            case .language: return "Language"
            case .voice: return "Voice"
            case .speech: return "Speech"
            case .agent: return "Agent & Scope"
            case .review: return "Review"
            case .applying: return "Applying"
            case .complete: return "Complete"
            }
        }
    }

    @Published var step: Step = .welcome
    @Published private(set) var inspection: SetupInspection?
    @Published var plan = SetupPlanPayload.defaults
    @Published private(set) var result: SetupApplyResult?
    @Published private(set) var isBusy = false
    @Published var errorMessage: String?
    @Published var languageSelection = "English"
    @Published var otherLanguage = ""
    @Published var installKokoroAccepted = false {
        didSet {
            plan.installKokoro = selectedBackend?.requiresInstall == true && installKokoroAccepted
            plan.acceptKokoroLicense = plan.installKokoro
        }
    }

    private let runner: any JarvisLineCommandRunning
    private let didComplete: @MainActor () async -> Void
    private var didNotifyCompletion = false

    init(
        runner: any JarvisLineCommandRunning = JarvisLineCLI(),
        didComplete: @escaping @MainActor () async -> Void = {}
    ) {
        self.runner = runner
        self.didComplete = didComplete
    }

    var languageOptions: [String] {
        let values = inspection?.languages ?? []
        return values.isEmpty ? ["English", "Turkish"] : values
    }

    var selectedBackend: SetupBackendOption? {
        inspection?.backendOptions.first { $0.id == plan.tts }
    }

    var visibleBackendOptions: [SetupBackendOption] {
        (inspection?.backendOptions ?? []).filter { $0.id != "command" || $0.available }
    }

    var canContinue: Bool {
        guard !isBusy else { return false }
        switch step {
        case .language:
            return Self.isValidFullLanguage(languageInputForValidation)
        case .voice:
            guard let backend = selectedBackend, backend.available else { return false }
            return backend.ready || (backend.requiresInstall && installKokoroAccepted)
        case .agent:
            return plan.instructionScope != "project" || plan.projectPath != nil
        case .applying:
            return false
        default:
            return true
        }
    }

    var canClose: Bool {
        step != .applying
    }

    var canCopyInstructions: Bool {
        guard let text = result?.instruction?.text.trimmingCharacters(in: .whitespacesAndNewlines) else {
            return false
        }
        return !text.isEmpty
    }

    var isNonEnglish: Bool {
        plan.language.caseInsensitiveCompare("English") != .orderedSame
    }

    var languageValidationMessage: String? {
        Self.languageValidationMessage(for: languageInputForValidation)
    }

    private var languageInputForValidation: String {
        languageSelection == "Other language..." ? otherLanguage : plan.language
    }

    var reviewActions: [String] {
        var actions = ["Write the reviewed Jarvis Line configuration", "Run a local health check"]
        if plan.installKokoro {
            actions.insert("Download verified Kokoro assets and install approved dependencies", at: 0)
        }
        if plan.installCodexHook {
            actions.append("Install or refresh the bundled Codex hook")
        }
        if plan.startRuntime {
            actions.append("Start or restart Jarvis Line")
        }
        if plan.testVoice {
            actions.append("Play the approved voice test")
        }
        actions.append("Generate instructions for manual review and paste")
        return actions
    }

    func load() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            applyInspection(try await inspect())
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func preload(_ inspection: SetupInspection) {
        applyInspection(inspection)
    }

    func selectLanguage(_ language: String) {
        languageSelection = language
        if language == "Other language..." {
            plan.language = otherLanguage.trimmingCharacters(in: .whitespacesAndNewlines)
        } else {
            otherLanguage = ""
            plan.language = language
        }
    }

    func setOtherLanguage(_ language: String) {
        otherLanguage = language
        languageSelection = "Other language..."
        plan.language = language.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func continueFromLanguage() async {
        guard canContinue else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            let language = plan.language
            let priorBackendID = plan.tts
            let updatedInspection = try await inspect(language: language)
            inspection = updatedInspection
            let available = updatedInspection.backendOptions.filter(\.available)
            let selected = available.first(where: { $0.id == priorBackendID })
                ?? available.first(where: \.recommended)
                ?? available.first
            plan.language = language
            plan.tts = selected?.id ?? "system"
            installKokoroAccepted = false
            plan.installKokoro = false
            plan.acceptKokoroLicense = false
            step = .voice
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func selectBackend(_ id: String) {
        guard let backend = visibleBackendOptions.first(where: { $0.id == id && $0.available }) else {
            return
        }
        plan.tts = backend.id
        installKokoroAccepted = false
        plan.installKokoro = false
        plan.acceptKokoroLicense = false
    }

    func setAgentTarget(_ target: String) {
        guard ["codex", "claude", "gemini", "agents"].contains(target) else { return }
        plan.agentTarget = target
        if target != "codex" {
            plan.installCodexHook = false
        }
    }

    func setInstructionScope(_ scope: String) {
        guard ["project", "global"].contains(scope) else { return }
        plan.instructionScope = scope
        if scope == "global" {
            plan.projectPath = nil
        }
    }

    func selectProjectDirectory(_ url: URL) {
        guard url.isFileURL else { return }
        plan.projectPath = url.path
    }

    func next() {
        guard canContinue,
              let index = Step.allCases.firstIndex(of: step),
              index + 1 < Step.allCases.count else {
            return
        }
        step = Step.allCases[index + 1]
        errorMessage = nil
    }

    func back() {
        guard !isBusy,
              canClose,
              let index = Step.allCases.firstIndex(of: step),
              index > 0 else {
            return
        }
        step = Step.allCases[index - 1]
        errorMessage = nil
    }

    func cancel() {
        guard canClose else { return }
        errorMessage = nil
    }

    func apply() async {
        guard step == .review, canContinue else { return }
        isBusy = true
        step = .applying
        errorMessage = nil
        defer { isBusy = false }

        do {
            let decoded = try await applySetup(plan, using: runner)
            result = decoded
            if decoded.ok {
                step = .complete
                if !didNotifyCompletion {
                    didNotifyCompletion = true
                    await didComplete()
                }
            } else {
                step = .review
                errorMessage = readableError(for: decoded)
            }
        } catch {
            step = .review
            errorMessage = error.localizedDescription
        }
    }

    func copyInstructions() {
        guard step == .complete, let text = result?.instruction?.text, !text.isEmpty else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    func testVoice() async {
        guard step == .complete, !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            _ = try await runner.run(["tts", "test", "--text", "Jarvis line setup is ready."])
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    static func instructionDestination(for instruction: SetupInstructionResult) -> String {
        guard instruction.scope == "project" else { return instruction.destination }
        return URL(fileURLWithPath: instruction.destination)
            .appendingPathComponent(instruction.filename)
            .path
    }

    private func applyInspection(_ inspection: SetupInspection) {
        self.inspection = inspection
        plan = SetupPlanPayload(inspection: inspection)
        languageSelection = languageOptions.contains(plan.language) ? plan.language : "Other language..."
        otherLanguage = languageSelection == "Other language..." ? plan.language : ""
        installKokoroAccepted = false
        plan.installKokoro = false
        plan.acceptKokoroLicense = false
    }

    private func readableError(for result: SetupApplyResult) -> String {
        result.error
            ?? result.steps.first(where: { !$0.ok })?.detail
            ?? "Setup could not be completed. Review the choices and try again."
    }

    private func inspect(language: String? = nil) async throws -> SetupInspection {
        var args = ["setup", "inspect", "--json"]
        if let language {
            args += ["--language", language]
        }

        do {
            let output = try await runner.run(args)
            if let message = Self.cliErrorMessage(in: output) {
                throw SetupAssistantUserError(message: message)
            }
            return try SetupInspection.decode(output)
        } catch let error as CLIError {
            if let message = Self.cliErrorMessage(in: error.stdout) {
                throw SetupAssistantUserError(message: message)
            }
            throw error
        }
    }

    private static func isValidFullLanguage(_ value: String) -> Bool {
        languageValidationMessage(for: value) == nil
    }

    private static func languageValidationMessage(for value: String) -> String? {
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.unicodeScalars.count <= 80 else { return "Enter a full language name (up to 80 characters)." }
        if text.unicodeScalars.allSatisfy({ $0.isASCII && CharacterSet.letters.contains($0) }) && text.count <= 3 {
            return "Use a full language name, for example English or Turkish."
        }
        let allowedPunctuation = CharacterSet(charactersIn: " -'’()")
        for scalar in text.unicodeScalars {
            if Self.isControlCategory(scalar) {
                return "Language name is invalid."
            }
            if CharacterSet.letters.contains(scalar) || Self.isCombiningMark(scalar) || allowedPunctuation.contains(scalar) {
                continue
            }
            return "Language name contains unsupported characters."
        }
        return nil
    }

    private static func isCombiningMark(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.properties.generalCategory {
        case .nonspacingMark, .spacingMark, .enclosingMark:
            return true
        default:
            return false
        }
    }

    private static func isControlCategory(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.properties.generalCategory {
        case .control, .format, .privateUse, .surrogate, .unassigned:
            return true
        default:
            return false
        }
    }

    private static func cliErrorMessage(in output: String) -> String? {
        guard let payload = try? JSONDecoder().decode(SetupAssistantCLIErrorPayload.self, from: Data(output.utf8)),
              payload.version == 1,
              payload.ok == false,
              let error = payload.error?.trimmingCharacters(in: .whitespacesAndNewlines),
              !error.isEmpty else {
            return nil
        }
        return error
    }
}

private struct SetupAssistantCLIErrorPayload: Decodable {
    let version: Int
    let ok: Bool?
    let error: String?
}

private struct SetupAssistantUserError: LocalizedError {
    let message: String

    var errorDescription: String? { message }
}

enum SetupAssistantFirstRunController {
    private static let offeredKey = "setupAssistantWasOffered"

    static func shouldOffer(configExists: Bool, wasOffered: Bool) -> Bool {
        SetupFirstRunPolicy.shouldOffer(configExists: configExists, wasOffered: wasOffered)
    }

    static func wasOffered(defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: offeredKey)
    }

    static func markOffered(defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: offeredKey)
    }
}

struct SetupFirstRunInspectionState {
    private enum Status {
        case pending
        case inspecting
        case complete
    }

    private var status: Status = .pending

    var needsInspection: Bool {
        status == .pending
    }

    mutating func beginInspection() -> Bool {
        guard status == .pending else { return false }
        status = .inspecting
        return true
    }

    mutating func recordFailedInspection() {
        guard status == .inspecting else { return }
        status = .pending
    }

    mutating func recordSuccessfulInspection() {
        guard status == .inspecting else { return }
        status = .complete
    }
}

@MainActor
final class SetupAssistantWindowController: NSObject, NSWindowDelegate {
    static let shared = SetupAssistantWindowController()

    private var window: NSWindow?
    private var assistantModel: SetupAssistantModel?

    func show(mainModel: JarvisLineModel, inspection: SetupInspection? = nil) {
        if let window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let assistantModel = SetupAssistantModel { [weak mainModel] in
            await mainModel?.setupCompleted()
        }
        if let inspection {
            assistantModel.preload(inspection)
        }
        let rootView = SetupAssistantView(model: assistantModel) { [weak self] in
            self?.window?.performClose(nil)
        }
        .frame(minWidth: 640, minHeight: 500)
        .task {
            if inspection == nil {
                await assistantModel.load()
            }
        }
        let window = NSWindow(contentViewController: NSHostingController(rootView: rootView))
        window.title = "Jarvis Line Setup Assistant"
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        window.setContentSize(NSSize(width: 700, height: 560))
        window.minSize = NSSize(width: 640, height: 500)
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = NSColor(red: 0.05, green: 0.06, blue: 0.08, alpha: 1)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        self.window = window
        self.assistantModel = assistantModel
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        assistantModel?.canClose ?? true
    }

    func windowWillClose(_ notification: Notification) {
        window = nil
        assistantModel = nil
    }
}

struct SetupAssistantView: View {
    @ObservedObject var model: SetupAssistantModel
    let dismiss: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            HStack(spacing: 0) {
                progressRail
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        stepContent
                        if let errorMessage = model.errorMessage {
                            Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                                .font(.system(size: 13))
                                .foregroundStyle(JarvisTheme.error)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(24)
                }
            }
            Divider()
            footer
        }
        .preferredColorScheme(.dark)
        .tint(JarvisTheme.cyan)
        .background(JarvisTheme.panelBase)
    }

    private var header: some View {
        HStack(spacing: 12) {
            brandMark
            VStack(alignment: .leading, spacing: 3) {
                Text("Jarvis Line")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text("Setup Assistant")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(JarvisTheme.mutedText)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                Text(model.step.title)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text("Step \(min(model.step.rawValue + 1, 6)) of 6")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(JarvisTheme.goldSoft)
            }
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 13)
        .background(JarvisTheme.panelTop)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(JarvisTheme.cyan.opacity(0.24))
                .frame(height: 1)
        }
    }

    private var brandMark: some View {
        Group {
            if let image = NSImage(named: "BrandMark") ?? NSImage(named: "AppIcon") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(3)
            } else {
                Image(systemName: "waveform.circle.fill")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(JarvisTheme.cyan)
            }
        }
        .frame(width: 42, height: 42)
    }

    private var progressRail: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(setupSteps.enumerated()), id: \.offset) { index, step in
                HStack(spacing: 9) {
                    Image(systemName: progressIcon(for: index))
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(progressColor(for: index))
                        .frame(width: 18, height: 18)
                    Text(step.title)
                        .font(.system(size: 12, weight: index == currentSetupIndex ? .semibold : .medium))
                        .foregroundStyle(index <= currentSetupIndex ? JarvisTheme.primaryText : JarvisTheme.mutedText)
                        .lineLimit(2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                if index < setupSteps.count - 1 {
                    Rectangle()
                        .fill(index < currentSetupIndex ? JarvisTheme.cyan.opacity(0.45) : JarvisTheme.surfaceRaised)
                        .frame(width: 1, height: 20)
                        .padding(.leading, 8)
                }
            }
            Spacer(minLength: 16)
            Label("Local setup", systemImage: "lock.shield")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(JarvisTheme.goldSoft)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 22)
        .frame(width: 160, alignment: .topLeading)
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .background(JarvisTheme.panelTop.opacity(0.58))
    }

    private var setupSteps: [SetupAssistantModel.Step] {
        [.welcome, .language, .voice, .speech, .agent, .review]
    }

    private var currentSetupIndex: Int {
        min(model.step.rawValue, setupSteps.count - 1)
    }

    private func progressIcon(for index: Int) -> String {
        if model.step == .complete || model.step == .applying || index < currentSetupIndex {
            return "checkmark.circle.fill"
        }
        return index == currentSetupIndex ? "circle.inset.filled" : "circle"
    }

    private func progressColor(for index: Int) -> Color {
        if model.step == .complete || index <= currentSetupIndex {
            return JarvisTheme.cyan
        }
        return JarvisTheme.mutedText.opacity(0.72)
    }

    @ViewBuilder
    private var stepContent: some View {
        switch model.step {
        case .welcome:
            welcome
        case .language:
            language
        case .voice:
            voice
        case .speech:
            speech
        case .agent:
            agentAndScope
        case .review:
            review
        case .applying:
            applying
        case .complete:
            complete
        }
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Set up Jarvis Line")
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(JarvisTheme.primaryText)
            Text("Choose the language, voice behavior, and agent guidance that fit this Mac. Nothing is changed until you review and apply the final plan.")
                .foregroundStyle(JarvisTheme.mutedText)
                .fixedSize(horizontal: false, vertical: true)
            Label("Setup checks stay on this Mac. Audio and network work happen only when you approve them.", systemImage: "lock.shield")
                .font(.system(size: 13))
                .foregroundStyle(JarvisTheme.goldSoft)
        }
    }

    private var language: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionTitle("Choose spoken language", detail: "Use a full language name so Jarvis Line can request compatible backend choices.")
            Picker("Language", selection: Binding(
                get: { model.languageSelection },
                set: { model.selectLanguage($0) }
            )) {
                ForEach(model.languageOptions, id: \.self) { language in
                    Text(language).tag(language)
                }
                Text("Other language...").tag("Other language...")
            }
            .pickerStyle(.menu)
            if model.languageSelection == "Other language..." {
                TextField("Full language name", text: Binding(
                    get: { model.otherLanguage },
                    set: { model.setOtherLanguage($0) }
                ))
                .textFieldStyle(.roundedBorder)
                if let message = model.languageValidationMessage {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(JarvisTheme.error)
                }
            }
        }
    }

    private var voice: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionTitle("Choose voice backend", detail: "Recommendations come from Jarvis Line for the selected language.")
            ForEach(model.visibleBackendOptions) { backend in
                Button {
                    model.selectBackend(backend.id)
                } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: model.plan.tts == backend.id ? "largecircle.fill.circle" : "circle")
                            .foregroundStyle(model.plan.tts == backend.id ? JarvisTheme.cyan : JarvisTheme.mutedText)
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(backend.label)
                                    .font(.system(size: 14, weight: .semibold))
                                if backend.recommended {
                                    Text("Recommended")
                                        .font(.system(size: 11, weight: .medium))
                                        .foregroundStyle(JarvisTheme.goldSoft)
                                }
                            }
                            Text(backend.detail)
                                .font(.system(size: 12))
                                .foregroundStyle(JarvisTheme.mutedText)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        if !backend.available {
                            Text("Unavailable")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(JarvisTheme.error)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 6)
                }
                .buttonStyle(.plain)
                .disabled(!backend.available)
                Divider()
            }
            if model.selectedBackend?.requiresInstall == true {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Kokoro installation")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(JarvisTheme.goldSoft)
                    Text("The final Apply action will download verified Kokoro model assets from the upstream project. The model is Apache-2.0 licensed and is approximately 350 MB.")
                        .font(.system(size: 12))
                        .foregroundStyle(JarvisTheme.mutedText)
                        .fixedSize(horizontal: false, vertical: true)
                    Toggle("I accept the license and approve this download during Apply", isOn: $model.installKokoroAccepted)
                        .font(.system(size: 13))
                }
            }
            if model.isNonEnglish {
                Label("For a matching system voice, open macOS System Settings > Accessibility > Read & Speak and select a matching system language and voice.", systemImage: "speaker.wave.2")
                    .font(.system(size: 12))
                    .foregroundStyle(JarvisTheme.goldSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var speech: some View {
        VStack(alignment: .leading, spacing: 16) {
            sectionTitle("Choose speech behavior", detail: "Speech can stay off, speak final responses, or include meaningful commentary.")
            Toggle("Enable speech", isOn: Binding(
                get: { model.plan.speakMode != "off" },
                set: { model.plan.speakMode = $0 ? "final_only" : "off" }
            ))
            Picker("Speech mode", selection: $model.plan.speakMode) {
                Text("Final responses").tag("final_only")
                Text("Commentary + final").tag("commentary_and_final")
            }
            .pickerStyle(.segmented)
            .disabled(model.plan.speakMode == "off")
            if model.plan.speakMode == "off" {
                Text("Speech is off and will be submitted as speak_mode=off.")
                    .font(.system(size: 12))
                    .foregroundStyle(JarvisTheme.mutedText)
            }
        }
    }

    private var agentAndScope: some View {
        VStack(alignment: .leading, spacing: 16) {
            sectionTitle("Choose agent and instruction scope", detail: "Instructions are generated for manual review. This assistant never writes agent Markdown files.")
            Picker("Agent", selection: Binding(
                get: { model.plan.agentTarget },
                set: { model.setAgentTarget($0) }
            )) {
                Text("Generic").tag("agents")
                Text("Codex").tag("codex")
                Text("Claude").tag("claude")
                Text("Gemini").tag("gemini")
            }
            .pickerStyle(.segmented)
            Picker("Scope", selection: Binding(
                get: { model.plan.instructionScope },
                set: { model.setInstructionScope($0) }
            )) {
                Text("Project").tag("project")
                Text("Global").tag("global")
            }
            .pickerStyle(.segmented)
            if model.plan.instructionScope == "project" {
                HStack {
                    Button {
                        chooseProjectDirectory()
                    } label: {
                        Label("Choose Project Folder", systemImage: "folder")
                    }
                    Text(model.plan.projectPath ?? "No project folder selected")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(model.plan.projectPath == nil ? JarvisTheme.mutedText : JarvisTheme.primaryText)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
            if model.plan.agentTarget == "codex" {
                Toggle("Install or refresh the bundled Codex hook", isOn: $model.plan.installCodexHook)
            }
            Toggle("Start or restart Jarvis Line after Apply", isOn: $model.plan.startRuntime)
            Toggle("Run a voice test during Apply", isOn: $model.plan.testVoice)
        }
    }

    private var review: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionTitle("Review approved actions", detail: "Apply is the only action that changes Jarvis Line configuration or starts runtime work.")
            reviewValue("Language", model.plan.language)
            reviewValue("Voice", model.selectedBackend?.label ?? model.plan.tts)
            reviewValue("Speech", speechLabel(model.plan.speakMode))
            reviewValue("Agent", agentLabel(model.plan.agentTarget))
            reviewValue("Instructions", model.plan.instructionScope == "project" ? "Project folder, manual paste" : "Global instructions, manual paste")
            Divider()
            ForEach(Array(model.reviewActions.enumerated()), id: \.offset) { _, action in
                Label(action, systemImage: action.contains("Download") ? "arrow.down.circle" : "checkmark.circle")
                    .font(.system(size: 13))
                    .foregroundStyle(action.contains("Download") ? JarvisTheme.goldSoft : JarvisTheme.mutedText)
            }
        }
    }

    private var applying: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Applying approved setup")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(JarvisTheme.primaryText)
            ProgressView()
                .controlSize(.regular)
            Text("Jarvis Line is validating the reviewed plan and performing only the actions you approved. This can take a moment.")
                .font(.system(size: 13))
                .foregroundStyle(JarvisTheme.mutedText)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var complete: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Setup complete")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(JarvisTheme.primaryText)
            ForEach(model.result?.steps ?? [], id: \.id) { step in
                Label(completionLabel(for: step), systemImage: step.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(step.ok ? JarvisTheme.cyan : JarvisTheme.error)
            }
            if let instruction = model.result?.instruction {
                Text("Review and paste the generated instruction into \(SetupAssistantModel.instructionDestination(for: instruction)).")
                    .font(.system(size: 13))
                    .foregroundStyle(JarvisTheme.mutedText)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var footer: some View {
        HStack {
            if model.step == .applying {
                ProgressView()
                    .controlSize(.small)
                Text("Applying")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(JarvisTheme.mutedText)
                Spacer()
            } else if model.step == .complete {
                Spacer()
                if model.canCopyInstructions {
                    Button {
                        model.copyInstructions()
                    } label: {
                        Label("Copy Instructions", systemImage: "doc.on.doc")
                    }
                }
                Button {
                    Task { await model.testVoice() }
                } label: {
                    Label("Test Voice", systemImage: "speaker.wave.2")
                }
                .disabled(model.isBusy)
                Button {
                    dismiss()
                } label: {
                    Label("Done", systemImage: "checkmark")
                }
                .buttonStyle(.borderedProminent)
                .tint(JarvisTheme.cyan)
            } else {
                Button {
                    model.back()
                } label: {
                    Label("Back", systemImage: "chevron.left")
                }
                .disabled(model.step == .welcome || !model.canClose)
                Spacer()
                Button {
                    if model.step == .language {
                        Task { await model.continueFromLanguage() }
                    } else if model.step == .review {
                        Task { await model.apply() }
                    } else {
                        model.next()
                    }
                } label: {
                    Label(primaryActionTitle, systemImage: primaryActionIcon)
                }
                .buttonStyle(.borderedProminent)
                .tint(JarvisTheme.cyan)
                .disabled(!model.canContinue)
            }
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 14)
        .background(JarvisTheme.panelTop)
    }

    private var primaryActionTitle: String {
        if model.step == .review { return "Apply Setup" }
        if model.step == .welcome { return "Get Started" }
        return "Continue"
    }

    private var primaryActionIcon: String {
        model.step == .review ? "checkmark.circle.fill" : "arrow.right"
    }

    private func sectionTitle(_ title: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(JarvisTheme.primaryText)
            Text(detail)
                .font(.system(size: 13))
                .foregroundStyle(JarvisTheme.mutedText)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func reviewValue(_ title: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(JarvisTheme.mutedText)
                .frame(width: 88, alignment: .leading)
            Text(value)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(JarvisTheme.primaryText)
        }
    }

    private func chooseProjectDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Choose Folder"
        if panel.runModal() == .OK, let url = panel.url {
            model.selectProjectDirectory(url)
        }
    }

    private func speechLabel(_ mode: String) -> String {
        switch mode {
        case "commentary_and_final": return "Commentary and final responses"
        case "off": return "Off"
        default: return "Final responses"
        }
    }

    private func agentLabel(_ target: String) -> String {
        switch target {
        case "agents": return "Generic AGENTS.md"
        default: return target.capitalized
        }
    }

    private func completionLabel(for step: SetupResultStep) -> String {
        if !step.ok, !step.detail.isEmpty {
            return step.detail
        }
        switch step.id {
        case "kokoro_preflight": return "Kokoro voice is ready"
        case "config_backup": return "Previous configuration backed up"
        case "config_write": return "Configuration saved"
        case "codex_hook": return "Codex hook installed"
        case "runtime": return "Jarvis Line started"
        case "doctor": return "Health check passed"
        case "voice_test": return "Voice test completed"
        default:
            return step.id.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}
