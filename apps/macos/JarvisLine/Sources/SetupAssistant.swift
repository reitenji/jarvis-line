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
            return Self.isValidFullLanguage(plan.language)
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
        actions.append("Print instructions for manual review and paste")
        return actions
    }

    func load() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            applyInspection(try await inspectSetup(using: runner))
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
            let updatedInspection = try await inspectSetup(language: language, using: runner)
            inspection = updatedInspection
            let available = updatedInspection.backendOptions.filter(\.available)
            let selected = available.first(where: { $0.id == priorBackendID })
                ?? available.first(where: \.recommended)
                ?? available.first
            plan.language = language
            plan.tts = selected?.id ?? "system"
            installKokoroAccepted = false
            plan.installKokoro = false
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
    }

    func setAgentTarget(_ target: String) {
        guard ["codex", "claude", "gemini", "agents"].contains(target) else { return }
        plan.agentTarget = target
        if target != "codex" {
            plan.installCodexHook = false
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

    private func applyInspection(_ inspection: SetupInspection) {
        self.inspection = inspection
        plan = SetupPlanPayload(inspection: inspection)
        languageSelection = languageOptions.contains(plan.language) ? plan.language : "Other language..."
        otherLanguage = languageSelection == "Other language..." ? plan.language : ""
        installKokoroAccepted = false
        plan.installKokoro = false
    }

    private func readableError(for result: SetupApplyResult) -> String {
        result.error
            ?? result.steps.first(where: { !$0.ok })?.detail
            ?? "Setup could not be completed. Review the choices and try again."
    }

    private static func isValidFullLanguage(_ value: String) -> Bool {
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.count <= 80 else { return false }
        if text.unicodeScalars.allSatisfy({ $0.isASCII && CharacterSet.letters.contains($0) }) && text.count <= 3 {
            return false
        }
        return !text.unicodeScalars.contains { CharacterSet.controlCharacters.contains($0) }
    }
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
            Divider()
            footer
        }
        .preferredColorScheme(.dark)
        .tint(JarvisTheme.cyan)
        .background(JarvisTheme.panelBase)
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform.circle.fill")
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(JarvisTheme.cyan)
            VStack(alignment: .leading, spacing: 3) {
                Text("Jarvis Line")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text("Setup Assistant  •  \(model.step.title)")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(JarvisTheme.mutedText)
            }
            Spacer()
            Text("\(min(model.step.rawValue + 1, 6)) of 6")
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .foregroundStyle(JarvisTheme.goldSoft)
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 16)
        .background(JarvisTheme.panelTop)
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
                    Text("The final Apply action will download verified Kokoro model assets from the upstream project. The model is Apache-2.0 licensed and is approximately 300 MB.")
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
                Text("Codex").tag("codex")
                Text("Claude").tag("claude")
                Text("Gemini").tag("gemini")
                Text("Generic").tag("agents")
            }
            .pickerStyle(.segmented)
            Picker("Scope", selection: $model.plan.instructionScope) {
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
                Label(step.detail.isEmpty ? step.id.replacingOccurrences(of: "_", with: " ") : step.detail, systemImage: step.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.system(size: 13))
                    .foregroundStyle(step.ok ? JarvisTheme.cyan : JarvisTheme.error)
            }
            if let instruction = model.result?.instruction {
                Text("Review and paste the generated instruction into \(instruction.destination)/\(instruction.filename).")
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
                    Button("Copy Instructions") {
                        model.copyInstructions()
                    }
                }
                Button("Test Voice") {
                    Task { await model.testVoice() }
                }
                .disabled(model.isBusy)
                Button("Done") {
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .tint(JarvisTheme.cyan)
            } else {
                Button("Back") {
                    model.back()
                }
                .disabled(model.step == .welcome || !model.canClose)
                Spacer()
                Button(model.step == .review ? "Apply" : model.step == .welcome ? "Get Started" : "Continue") {
                    if model.step == .language {
                        Task { await model.continueFromLanguage() }
                    } else if model.step == .review {
                        Task { await model.apply() }
                    } else {
                        model.next()
                    }
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
}
