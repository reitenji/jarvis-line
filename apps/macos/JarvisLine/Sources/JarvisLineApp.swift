import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    static var showSettingsWindow: (() -> Void)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.regular)
        if let icon = NSImage(named: "AppIcon") {
            NSApplication.shared.applicationIconImage = icon
        }
        SingleInstanceGuard.enforce()
        DispatchQueue.main.async {
            self.pruneMainMenu()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            Self.showSettingsWindow?()
        }
        return true
    }

    private func pruneMainMenu() {
        guard let mainMenu = NSApplication.shared.mainMenu else {
            return
        }

        for item in mainMenu.items.reversed() where ["File", "Edit", "View", "Window", "Help"].contains(item.title) {
            mainMenu.removeItem(item)
        }
    }
}

enum SingleInstanceGuard {
    static func enforce() {
        guard let bundleIdentifier = Bundle.main.bundleIdentifier else {
            return
        }

        let currentPID = ProcessInfo.processInfo.processIdentifier
        let currentPath = URL(fileURLWithPath: Bundle.main.bundlePath).standardizedFileURL.path
        let otherApps = NSRunningApplication.runningApplications(withBundleIdentifier: bundleIdentifier)
            .filter { $0.processIdentifier != currentPID }

        guard !otherApps.isEmpty else {
            return
        }

        if isPreferredInstallPath(currentPath) {
            otherApps.forEach { $0.terminate() }
            return
        }

        let preferredApp = otherApps.first { app in
            guard let path = app.bundleURL?.standardizedFileURL.path else {
                return false
            }
            return isPreferredInstallPath(path)
        } ?? otherApps.first

        preferredApp?.activate(options: [])
        NSApplication.shared.terminate(nil)
    }

    private static func isPreferredInstallPath(_ path: String) -> Bool {
        if path.hasPrefix("/Applications/") {
            return true
        }

        let userApplicationsPath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Applications")
            .standardizedFileURL
            .path + "/"

        return path.hasPrefix(userApplicationsPath)
    }
}

@main
struct JarvisLineApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model: JarvisLineModel

    init() {
        let model = JarvisLineModel()
        _model = StateObject(wrappedValue: model)
        AppDelegate.showSettingsWindow = {
            Task { @MainActor in
                SettingsWindowController.shared.show(model: model)
            }
        }
    }

    var body: some Scene {
        MenuBarExtra {
            JarvisLinePanel(model: model, mode: .quick)
                .frame(width: 430)
                .task {
                    await model.refresh()
                }
        } label: {
            Image(systemName: model.statusIcon)
        }
        .menuBarExtraStyle(.window)
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button("Settings...") {
                    SettingsWindowController.shared.show(model: model)
                }
                .keyboardShortcut(",", modifiers: .command)
            }
            CommandGroup(after: .appInfo) {
                Button("Refresh Status") {
                    Task { await model.refresh() }
                }
                .keyboardShortcut("r", modifiers: .command)
            }
        }
    }
}

@MainActor
final class JarvisLineModel: ObservableObject {
    @Published var status = RuntimeStatus.empty
    @Published var config = JarvisConfigDraft.defaults
    @Published var cliVersion = "jarvis-line unknown"
    @Published var systemVoices: [String] = [""]
    @Published var doctorText = ""
    @Published var lastOutput = ""
    @Published var isBusy = false
    @Published var errorMessage: String?
    @Published var codexHookInstalled = false

    private let cli = JarvisLineCLI()
    private let configStore = JarvisConfigStore()

    var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "local"
        return "App \(version) (\(build))"
    }

    var statusIcon: String {
        if status.watcherState == "running" {
            if status.queueJobs > 0 {
                return "waveform.badge.magnifyingglass"
            }
            return "waveform.circle.fill"
        }
        return "waveform.circle"
    }

    func refresh() async {
        await run(label: "Refresh") {
            config = try configStore.load()
            cliVersion = (try? await cli.run(["--version"]).trimmingCharacters(in: .whitespacesAndNewlines)) ?? "jarvis-line unavailable"
            systemVoices = JarvisLineCLI.systemVoices(preserving: config.systemVoice)
            let statusOutput = try await cli.run(["status"])
            let doctorOutput = try await cli.run(["doctor"])
            status = RuntimeStatus.parse(statusOutput)
            doctorText = doctorOutput
            codexHookInstalled = DoctorStatus.parse(doctorOutput).codexHookInstalled
            lastOutput = statusOutput
        }
    }

    func start() async {
        await command("Start", ["start"])
        await refresh()
    }

    func stop() async {
        await command("Stop", ["stop"])
        await refresh()
    }

    func restart() async {
        await command("Restart", ["restart"])
        await refresh()
    }

    func repair() async {
        await command("Repair", ["doctor", "--fix"])
        await refresh()
    }

    func installCodexHook() async {
        await command("Install Codex Hook", ["install", "codex"])
        await refresh()
    }

    func testVoice() async {
        await command("Test Voice", ["tts", "test", "--text", "Jarvis line test is ready."])
        await refresh()
    }

    func loadConfig() async {
        await run(label: "Load Config") {
            config = try configStore.load()
            systemVoices = JarvisLineCLI.systemVoices(preserving: config.systemVoice)
            lastOutput = "Loaded config from \(configStore.displayPath)"
        }
    }

    func saveConfig(restart: Bool) async {
        await run(label: "Save Config") {
            try configStore.save(config)
            lastOutput = "Saved config to \(configStore.displayPath)"
            if restart {
                lastOutput += "\n" + (try await cli.run(["restart"]))
            }
            let doctorOutput = try await cli.run(["doctor"])
            doctorText = doctorOutput
            codexHookInstalled = DoctorStatus.parse(doctorOutput).codexHookInstalled
        }
        await refresh()
    }

    func openConfig() {
        open(path: "~/.codex/hooks/jarvis_line_config.json")
    }

    func openWatcherLog() {
        open(path: "~/.codex/hooks/jarvis_line_watcher.log")
    }

    func openAudioWorkerLog() {
        open(path: "~/.codex/hooks/jarvis_line_audio_worker.log")
    }

    private func command(_ label: String, _ args: [String]) async {
        await run(label: label) {
            lastOutput = try await cli.run(args)
        }
    }

    private func run(label: String, operation: () async throws -> Void) async {
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        do {
            try await operation()
        } catch {
            errorMessage = "\(label) failed: \(error.localizedDescription)"
        }
    }

    private func open(path: String) {
        let expanded = NSString(string: path).expandingTildeInPath
        NSWorkspace.shared.open(URL(fileURLWithPath: expanded))
    }
}

@MainActor
final class SettingsWindowController: NSObject, NSWindowDelegate {
    static let shared = SettingsWindowController()
    private var window: NSWindow?

    func show(model: JarvisLineModel) {
        if let window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let rootView = JarvisLinePanel(model: model, mode: .settingsWindow)
            .frame(minWidth: 700, minHeight: 660)
            .task {
                await model.refresh()
            }
        let hostingController = NSHostingController(rootView: rootView)
        let window = NSWindow(contentViewController: hostingController)
        window.title = "Jarvis Line Settings"
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        window.setContentSize(NSSize(width: 760, height: 720))
        window.minSize = NSSize(width: 700, height: 660)
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = NSColor(red: 0.05, green: 0.06, blue: 0.08, alpha: 1)
        window.titlebarAppearsTransparent = false
        window.isMovableByWindowBackground = true
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        self.window = window
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        window = nil
    }
}

struct WindowDragRegion: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = DraggableHeaderView()
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.clear.cgColor
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
    }
}

final class DraggableHeaderView: NSView {
    override var mouseDownCanMoveWindow: Bool {
        true
    }
}

struct JarvisLinePanel: View {
    @ObservedObject var model: JarvisLineModel
    let mode: PanelMode

    var body: some View {
        Group {
            if mode == .quick {
                quickBody
            } else {
                settingsWindowBody
            }
        }
        .preferredColorScheme(.dark)
        .tint(JarvisTheme.cyan)
        .background(panelBackground)
    }

    private var quickBody: some View {
        VStack(spacing: 0) {
            header
            Divider()
            quickView
            Divider()
            footer
        }
    }

    private var settingsWindowBody: some View {
        VStack(spacing: 0) {
            header
            Divider()
            settingsView
            Divider()
            footer
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 14) {
            appMark
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 9) {
                    Text("Jarvis Line")
                        .font(.system(size: 20, weight: .semibold))
                    stateBadge
                }
                Text(model.status.summary)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(JarvisTheme.mutedText)
                HStack(spacing: 6) {
                    versionChip(model.cliVersion.replacingOccurrences(of: "jarvis-line ", with: "CLI "))
                    versionChip(model.appVersion)
                }
            }
            Spacer()
            if model.isBusy {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 22, height: 22)
            } else {
                Button {
                    Task { await model.refresh() }
                } label: {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .frame(width: 24, height: 24)
                }
                .buttonStyle(.borderless)
                .help("Refresh")
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .background(
            LinearGradient(
                colors: [
                    JarvisTheme.panelTop,
                    JarvisTheme.panelBase,
                    JarvisTheme.cyan.opacity(0.12),
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(
                    LinearGradient(
                        colors: [
                            JarvisTheme.gold.opacity(0.42),
                            JarvisTheme.cyan.opacity(0.58),
                            JarvisTheme.gold.opacity(0.24),
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .frame(height: 1)
        }
        .overlay {
            if mode == .settingsWindow {
                HStack(spacing: 0) {
                    WindowDragRegion()
                    Color.clear
                        .frame(width: 58)
                        .allowsHitTesting(false)
                }
            }
        }
    }

    private var appMark: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(JarvisTheme.surfaceRaised)
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(JarvisTheme.gold.opacity(0.42), lineWidth: 1)
                )
            if let image = NSImage(named: "BrandMark") ?? NSImage(named: "AppIcon") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(4)
            } else {
                Image(systemName: model.statusIcon)
                    .font(.system(size: 27, weight: .semibold))
                    .foregroundStyle(JarvisTheme.cyan)
            }
        }
        .shadow(color: JarvisTheme.cyan.opacity(0.18), radius: 12, x: 0, y: 0)
        .frame(width: 54, height: 54)
    }

    private var stateBadge: some View {
        Label(model.status.watcherState == "running" ? "Live" : "Stopped", systemImage: model.status.watcherState == "running" ? "checkmark.circle.fill" : "pause.circle")
            .font(.system(size: 11, weight: .semibold))
            .labelStyle(.titleAndIcon)
            .foregroundStyle(model.status.watcherState == "running" ? JarvisTheme.cyan : JarvisTheme.mutedText)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background((model.status.watcherState == "running" ? JarvisTheme.cyan : JarvisTheme.mutedText).opacity(0.14))
            .clipShape(Capsule())
    }

    private func versionChip(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .medium, design: .monospaced))
            .foregroundStyle(JarvisTheme.goldSoft)
            .lineLimit(1)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(JarvisTheme.gold.opacity(0.11))
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .stroke(JarvisTheme.gold.opacity(0.18), lineWidth: 1)
            )
    }

    private var quickView: some View {
        VStack(alignment: .leading, spacing: 13) {
            heroStatus
            compactStatus
            commandDeck
        }
        .padding(14)
    }

    private var compactStatus: some View {
        VStack(spacing: 8) {
            StatusLine(title: "Watcher", value: display(model.status.watcher), icon: "eye")
            StatusLine(title: "Worker", value: display(model.status.audioWorker), icon: "cpu")
            StatusLine(title: "Queue", value: "\(model.status.queueJobs) lines", icon: "text.line.first.and.arrowtriangle.forward")
        }
        .padding(10)
        .background(sectionFill)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(sectionStroke)
    }

    private var heroStatus: some View {
        HStack(spacing: 14) {
            Image(systemName: model.statusIcon)
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(model.status.watcherState == "running" ? JarvisTheme.cyan : JarvisTheme.mutedText)
                .frame(width: 40, height: 40)
                .background((model.status.watcherState == "running" ? JarvisTheme.cyan : JarvisTheme.mutedText).opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(model.status.watcherState == "running" ? "Voice pipeline is active" : "Voice pipeline needs attention")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text("TTS \(display(model.status.tts)) · \(display(model.status.speakMode)) · queue \(model.status.queueJobs)")
                    .font(.system(size: 12))
                    .foregroundStyle(JarvisTheme.mutedText)
            }
            Spacer()
            Button {
                Task { await model.testVoice() }
            } label: {
                Label("Test", systemImage: "speaker.wave.2.fill")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderedProminent)
            .tint(JarvisTheme.cyan)
            .disabled(model.isBusy)
        }
        .padding(12)
        .background(sectionFill)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(sectionStroke)
    }

    private var commandDeck: some View {
        PanelSection(title: "Controls", icon: "switch.2") {
            VStack(spacing: 8) {
                HStack(spacing: 8) {
                    CommandButton(title: "Start", icon: "play.fill") { Task { await model.start() } }
                    CommandButton(title: "Stop", icon: "stop.fill") { Task { await model.stop() } }
                    CommandButton(title: "Restart", icon: "arrow.clockwise") { Task { await model.restart() } }
                }
                HStack(spacing: 8) {
                    CommandButton(title: "Repair", icon: "wrench.and.screwdriver") { Task { await model.repair() } }
                    if !model.codexHookInstalled {
                        CommandButton(title: "Install Hook", icon: "link.badge.plus") { Task { await model.installCodexHook() } }
                    }
                }
            }
            .disabled(model.isBusy)
        }
    }

    private var settingsView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                PanelSection(title: "Runtime", icon: "slider.horizontal.3") {
                    runtimeSettings
                }
                PanelSection(title: "Voice", icon: "speaker.wave.2") {
                    ttsSettings
                }
                PanelSection(title: "Updates", icon: "arrow.down.circle") {
                    updateSettings
                }
                validationSummary
                settingsActions
                diagnosticsPanel
            }
            .padding(16)
        }
        .frame(height: mode == .settingsWindow ? 540 : 488)
    }

    private var runtimeSettings: some View {
        Form {
            Toggle("Speech enabled", isOn: $model.config.speechEnabled)
            Toggle("Speak without prefix", isOn: $model.config.speakWithoutPrefix)

            Picker("Speak mode", selection: $model.config.speakMode) {
                Text("Final only").tag("final_only")
                Text("Commentary + final").tag("commentary_and_final")
                Text("Off").tag("off")
            }

            Picker("Line language", selection: $model.config.lineLanguage) {
                ForEach(JarvisConfigDraft.lineLanguageOptions, id: \.self) { value in
                    Text(value).tag(value)
                }
            }

            LabeledContent("Assistant") {
                Text("Jarvis")
                    .foregroundStyle(.secondary)
            }

            Picker("Spoken length", selection: $model.config.maxSpokenChars) {
                Text("Short · 120").tag(120)
                Text("Balanced · 180").tag(180)
                Text("Detailed · 240").tag(240)
                Text("Verbose · 300").tag(300)
            }

            Picker("Queue size", selection: $model.config.maxQueueSize) {
                ForEach(JarvisConfigDraft.maxQueueSizeOptions, id: \.self) { value in
                    Text("\(value) lines").tag(value)
                }
            }

            Picker("Quiet hours", selection: $model.config.quietHours) {
                Text("Off").tag("")
                Text("Night · 22:00-08:00").tag("22:00-08:00")
                Text("Evening · 20:00-08:00").tag("20:00-08:00")
                Text("After work · 18:00-09:00").tag("18:00-09:00")
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
    }

    private var ttsSettings: some View {
        VStack(alignment: .leading, spacing: 12) {
            Form {
                Picker("Backend", selection: $model.config.tts) {
                    Text("Kokoro · bundled default").tag("kokoro")
                    Text("System voice").tag("system")
                    Text("macOS say").tag("macos")
                    Text("Custom command").tag("command")
                }

                Picker("Fallback", selection: $model.config.fallbackTTS) {
                    Text("None").tag("none")
                    Text("System").tag("system")
                    Text("macOS").tag("macos")
                    if !model.config.command.isEmpty {
                        Text("Command").tag("command")
                    }
                }

                Toggle("Warm TTS", isOn: $model.config.warmTTS)

                Picker("Warm-up text", selection: $model.config.warmTTSText) {
                    ForEach(options(JarvisConfigDraft.warmTextOptions, preserving: model.config.warmTTSText), id: \.self) { value in
                        Text(value).tag(value)
                    }
                }
            }
            .formStyle(.grouped)
            .scrollContentBackground(.hidden)

            HStack(spacing: 10) {
                Image(systemName: "speaker.wave.1")
                    .foregroundStyle(JarvisTheme.goldSoft)
                Slider(value: $model.config.volume, in: 0...1)
                Text(String(format: "%.2f", model.config.volume))
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .frame(width: 34, alignment: .trailing)
                    .foregroundStyle(JarvisTheme.mutedText)
            }
            .padding(10)
            .background(JarvisTheme.surfaceRaised)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(sectionStroke)

            backendOptions
        }
    }

    @ViewBuilder
    private var backendOptions: some View {
        PanelSection(title: "Backend options", icon: "dial.low") {
            Form {
                if model.config.tts == "kokoro" {
                    Picker("Kokoro voice", selection: $model.config.voice) {
                        Text("George + Lewis blend").tag("bm_george:70,bm_lewis:30")
                        Text("George").tag("bm_george")
                        Text("Lewis").tag("bm_lewis")
                    }
                    Picker("Kokoro language", selection: $model.config.lang) {
                        ForEach(JarvisConfigDraft.kokoroLangOptions, id: \.self) { value in
                            Text(kokoroLangLabel(value)).tag(value)
                        }
                    }
                    Picker("Speed", selection: $model.config.speed) {
                        Text("Calm · 0.90").tag(0.9)
                        Text("Normal · 1.00").tag(1.0)
                        Text("Jarvis default · 1.08").tag(1.08)
                        Text("Fast · 1.20").tag(1.2)
                    }
                }

                if model.config.tts == "system" || model.config.tts == "macos" {
                    Picker("System voice", selection: $model.config.systemVoice) {
                        ForEach(model.systemVoices, id: \.self) { value in
                            Text(value.isEmpty ? "System default" : value).tag(value)
                        }
                    }
                    Picker("System rate", selection: $model.config.systemRate) {
                        ForEach(JarvisConfigDraft.systemRateOptions, id: \.self) { value in
                            Text("\(value)").tag(value)
                        }
                    }
                }

                if model.config.tts == "command" {
                    if model.config.command.isEmpty {
                        Label("Configure a custom command in the config file first.", systemImage: "lock.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        LabeledContent("Command") {
                            Text(shortCommand(model.config.command))
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
            .formStyle(.grouped)
            .scrollContentBackground(.hidden)
        }
    }

    private var updateSettings: some View {
        Form {
            Toggle("Check for updates", isOn: $model.config.updateCheckEnabled)
            Picker("Interval", selection: $model.config.updateCheckIntervalHours) {
                ForEach(JarvisConfigDraft.updateIntervalOptions, id: \.self) { value in
                    Text(value == 168 ? "Weekly" : "\(value) hours").tag(value)
                }
            }
            LabeledContent("Source") {
                Text("Official GitHub")
                    .foregroundStyle(JarvisTheme.mutedText)
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
    }

    @ViewBuilder
    private var validationSummary: some View {
        let issues = model.config.blockingIssues
        let guidance = model.config.guidance
        if !issues.isEmpty || !guidance.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(issues, id: \.self) { issue in
                    Label(issue, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
                ForEach(guidance, id: \.self) { note in
                    Label(note, systemImage: "info.circle")
                        .foregroundStyle(.secondary)
                }
            }
            .font(.system(size: 12))
            .padding(11)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(issues.isEmpty ? JarvisTheme.cyan.opacity(0.08) : JarvisTheme.error.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(issues.isEmpty ? JarvisTheme.cyan.opacity(0.22) : JarvisTheme.error.opacity(0.34), lineWidth: 1)
            )
        }
    }

    private func options(_ base: [String], preserving current: String) -> [String] {
        let value = current.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, !base.contains(value) else {
            return base
        }
        return base + [value]
    }

    private func kokoroLangLabel(_ value: String) -> String {
        switch value {
        case "en-gb": return "English GB"
        case "en-us": return "English US"
        case "fr-fr": return "French"
        case "it": return "Italian"
        case "ja": return "Japanese"
        case "cmn": return "Mandarin"
        default: return value
        }
    }

    private func shortCommand(_ value: String) -> String {
        value.count > 42 ? String(value.prefix(42)) + "..." : value
    }

    private var settingsActions: some View {
        HStack(spacing: 8) {
            Button {
                Task { await model.loadConfig() }
            } label: {
                Label("Reload", systemImage: "arrow.clockwise")
            }
            Spacer()
            Button {
                Task { await model.saveConfig(restart: false) }
            } label: {
                Label("Save", systemImage: "square.and.arrow.down")
            }
            Button {
                Task { await model.saveConfig(restart: true) }
            } label: {
                Label("Save + Restart", systemImage: "arrow.triangle.2.circlepath")
            }
        }
        .buttonStyle(.bordered)
        .tint(JarvisTheme.cyan)
        .disabled(model.isBusy || !model.config.blockingIssues.isEmpty)
    }

    @ViewBuilder
    private var diagnosticsPanel: some View {
        if let error = model.errorMessage {
            PanelSection(title: "Diagnostics", icon: "exclamationmark.triangle") {
                Text(error)
                    .font(.system(size: 12))
                    .foregroundStyle(JarvisTheme.error)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else if !model.doctorText.isEmpty {
            PanelSection(title: "Diagnostics", icon: "stethoscope") {
                ScrollView {
                    Text(model.doctorText)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(JarvisTheme.mutedText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
                .frame(height: mode == .settingsWindow ? 132 : 108)
                .padding(9)
                .background(JarvisTheme.console)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(JarvisTheme.cyan.opacity(0.14), lineWidth: 1)
                )
            }
        }
    }

    private var footer: some View {
        HStack {
            Text("Jarvis Line Manager")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(JarvisTheme.subtleText)
            Spacer()
            if mode == .quick {
                Button {
                    SettingsWindowController.shared.show(model: model)
                } label: {
                    Label("Settings", systemImage: "gearshape")
                }
                .buttonStyle(.link)
                .foregroundStyle(JarvisTheme.cyan)
            }
            Button("Quit") {
                NSApplication.shared.terminate(nil)
            }
            .buttonStyle(.link)
            .foregroundStyle(JarvisTheme.goldSoft)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 9)
        .background(JarvisTheme.panelBase.opacity(0.92))
    }

    private var panelBackground: some View {
        LinearGradient(
            colors: [
                JarvisTheme.panelTop,
                JarvisTheme.panelBase,
                JarvisTheme.panelBottom,
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var sectionFill: some ShapeStyle {
        LinearGradient(
            colors: [
                JarvisTheme.surfaceRaised,
                JarvisTheme.surface,
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var sectionStroke: some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .stroke(
                LinearGradient(
                    colors: [
                        JarvisTheme.gold.opacity(0.22),
                        JarvisTheme.cyan.opacity(0.18),
                        JarvisTheme.border,
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ),
                lineWidth: 1
            )
    }

    private func display(_ value: String) -> String {
        value.isEmpty ? "n/a" : value
    }
}

enum PanelMode {
    case quick
    case settingsWindow
}

enum JarvisTheme {
    static let panelTop = Color(red: 0.07, green: 0.09, blue: 0.12)
    static let panelBase = Color(red: 0.05, green: 0.06, blue: 0.08)
    static let panelBottom = Color(red: 0.02, green: 0.03, blue: 0.04)
    static let surface = Color(red: 0.09, green: 0.12, blue: 0.16)
    static let surfaceRaised = Color(red: 0.14, green: 0.16, blue: 0.19)
    static let console = Color(red: 0.03, green: 0.04, blue: 0.05)
    static let cyan = Color(red: 0.32, green: 0.75, blue: 0.94)
    static let cyanDeep = Color(red: 0.06, green: 0.39, blue: 0.66)
    static let gold = Color(red: 0.71, green: 0.61, blue: 0.49)
    static let goldSoft = Color(red: 0.90, green: 0.86, blue: 0.77)
    static let primaryText = Color(red: 0.94, green: 0.96, blue: 0.98)
    static let mutedText = Color(red: 0.68, green: 0.73, blue: 0.79)
    static let subtleText = Color(red: 0.48, green: 0.54, blue: 0.61)
    static let border = Color(red: 0.25, green: 0.29, blue: 0.35)
    static let error = Color(red: 1.00, green: 0.45, blue: 0.40)
}

private struct StatusLine: View {
    let title: String
    let value: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(JarvisTheme.cyan.opacity(0.82))
                .frame(width: 16)
            Text(title)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(JarvisTheme.mutedText)
            Spacer()
            Text(value)
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(JarvisTheme.primaryText)
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
        }
    }
}

private struct PanelSection<Content: View>: View {
    let title: String
    let icon: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: icon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(JarvisTheme.goldSoft)
            content
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(
                colors: [
                    JarvisTheme.surfaceRaised,
                    JarvisTheme.surface,
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(
                    LinearGradient(
                        colors: [
                            JarvisTheme.gold.opacity(0.20),
                            JarvisTheme.cyan.opacity(0.16),
                            JarvisTheme.border,
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 1
                )
        )
    }
}

private struct CommandButton: View {
    let title: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(JarvisTheme.primaryText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 7)
                .background(
                    LinearGradient(
                        colors: [
                            JarvisTheme.surfaceRaised,
                            JarvisTheme.cyanDeep.opacity(0.40),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(JarvisTheme.cyan.opacity(0.24), lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }
}

struct RuntimeStatus {
    var tts: String
    var watcher: String
    var watcherState: String
    var audioWorker: String
    var audioWorkerRSS: String
    var queueJobs: Int
    var speakMode: String

    static let empty = RuntimeStatus(
        tts: "unknown",
        watcher: "unknown",
        watcherState: "unknown",
        audioWorker: "unknown",
        audioWorkerRSS: "n/a",
        queueJobs: 0,
        speakMode: "unknown"
    )

    var summary: String {
        if watcherState == "running" {
            return queueJobs > 0 ? "Running, \(queueJobs) queued" : "Running"
        }
        return "Stopped or unavailable"
    }

    static func parse(_ output: String) -> RuntimeStatus {
        var values: [String: String] = [:]
        for line in output.split(separator: "\n") {
            let parts = line.split(separator: ":", maxSplits: 1).map { String($0).trimmingCharacters(in: .whitespaces) }
            if parts.count == 2 {
                values[parts[0]] = parts[1]
            }
        }

        let watcher = values["watcher"] ?? "unknown"
        return RuntimeStatus(
            tts: values["tts"] ?? "unknown",
            watcher: watcher,
            watcherState: watcher.split(separator: " ").first.map(String.init) ?? watcher,
            audioWorker: values["audio_worker"] ?? "unknown",
            audioWorkerRSS: values["audio_worker_rss_mb"] ?? "n/a",
            queueJobs: Int(values["queue_jobs"] ?? "0") ?? 0,
            speakMode: values["speak_mode"] ?? "unknown"
        )
    }
}

struct DoctorStatus {
    var codexHookInstalled: Bool

    static let empty = DoctorStatus(codexHookInstalled: false)

    static func parse(_ output: String) -> DoctorStatus {
        for line in output.split(separator: "\n") {
            let text = String(line)
            if text.contains("[OK] Codex hooks.json") {
                return DoctorStatus(codexHookInstalled: true)
            }
            if text.contains("Codex hooks.json") && !text.contains("[OK]") {
                return DoctorStatus(codexHookInstalled: false)
            }
        }
        return .empty
    }
}

struct JarvisLineCLI {
    func run(_ args: [String]) async throws -> String {
        let executable = findExecutable()
        return try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = args

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            process.standardOutput = outputPipe
            process.standardError = errorPipe

            do {
                try process.run()
            } catch {
                continuation.resume(throwing: error)
                return
            }

            process.terminationHandler = { proc in
                let output = String(data: outputPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                let error = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                if proc.terminationStatus == 0 {
                    continuation.resume(returning: output)
                } else {
                    continuation.resume(throwing: CLIError(output + error))
                }
            }
        }
    }

    private func findExecutable() -> String {
        let candidates = [
            "/opt/homebrew/bin/jarvis-line",
            "\(NSHomeDirectory())/.jarvis-line/tts/kokoro-venv/bin/jarvis-line",
            "\(NSHomeDirectory())/.local/bin/jarvis-line",
            "/usr/local/bin/jarvis-line",
        ]
        for candidate in candidates where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        return "/opt/homebrew/bin/jarvis-line"
    }

    static func systemVoices(preserving current: String) -> [String] {
        var voices = [""]
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/say")
        process.arguments = ["-v", "?"]
        process.standardOutput = pipe

        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""
            for line in output.split(separator: "\n") {
                let parts = line.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
                guard let localeIndex = parts.firstIndex(where: { $0.contains("_") }), localeIndex > 0 else {
                    continue
                }
                let name = parts[..<localeIndex].joined(separator: " ")
                if !voices.contains(name) {
                    voices.append(name)
                }
            }
        } catch {
            return voices
        }

        let value = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !value.isEmpty && !voices.contains(value) {
            voices.append(value)
        }
        return voices
    }
}

struct CLIError: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var errorDescription: String? {
        message.isEmpty ? "jarvis-line command failed" : message
    }
}
