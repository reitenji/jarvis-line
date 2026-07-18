import AppKit
import Darwin
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    static var showSettingsWindow: (() -> Void)?
    static var showSetupWindow: (() -> Void)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        Self.applyDockVisibility(JarvisAppPreferences.showDockIcon)
        if let icon = NSImage(named: "AppIcon") {
            NSApplication.shared.applicationIconImage = icon
        }
        SingleInstanceGuard.enforce()
        DispatchQueue.main.async {
            Self.applyDockVisibility(JarvisAppPreferences.showDockIcon)
            Self.pruneMainMenu()
        }
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        Self.applyDockVisibility(JarvisAppPreferences.showDockIcon)
        Self.pruneMainMenu()
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

    private static func pruneMainMenu() {
        guard let mainMenu = NSApplication.shared.mainMenu else {
            return
        }

        let hiddenMenus = Set(["File", "Edit", "View", "Window", "Help"])
        for item in mainMenu.items.reversed() {
            let titles = [item.title, item.submenu?.title].compactMap { $0 }
            if titles.contains(where: hiddenMenus.contains) {
                mainMenu.removeItem(item)
            }
        }
    }

    static func applyDockVisibility(_ isVisible: Bool) {
        NSApplication.shared.setActivationPolicy(isVisible ? .regular : .accessory)
        if isVisible {
            NSApplication.shared.activate(ignoringOtherApps: true)
        }
    }
}

enum JarvisAppPreferences {
    private static let showDockIconKey = "showDockIcon"

    static var showDockIcon: Bool {
        get {
            guard UserDefaults.standard.object(forKey: showDockIconKey) != nil else {
                return true
            }
            return UserDefaults.standard.bool(forKey: showDockIconKey)
        }
        set {
            UserDefaults.standard.set(newValue, forKey: showDockIconKey)
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
        AppDelegate.showSetupWindow = {
            Task { @MainActor in
                SetupAssistantWindowController.shared.show(mainModel: model)
            }
        }
        model.onInitialSetupInspection = { [weak model] inspection in
            guard let model,
                  SetupAssistantFirstRunController.shouldOffer(
                      configExists: inspection.configExists,
                      wasOffered: SetupAssistantFirstRunController.wasOffered()
                  ) else {
                return
            }
            SetupAssistantFirstRunController.markOffered()
            SetupAssistantWindowController.shared.show(mainModel: model, inspection: inspection)
        }
    }

    var body: some Scene {
        MenuBarExtra {
            JarvisLinePanel(model: model)
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
    @Published private(set) var savedConfig = JarvisConfigDraft.defaults
    @Published var configContract = JarvisConfigContract.empty
    @Published var traceEvents: [RuntimeTraceEvent] = []
    @Published var cliVersion = "jarvis-line unknown"
    @Published var systemVoices: [String] = [""]
    @Published var doctorText = ""
    @Published var lastOutput = ""
    @Published private(set) var updateStatusText = "Not checked in this app session"
    @Published private(set) var cleanupStatus = StorageCleanupStatus.empty
    @Published private(set) var cleanupResultText = "Not checked"
    @Published private(set) var settingsConfirmation: String?
    @Published var isBusy = false
    @Published var errorMessage: String?
    @Published var codexHookInstalled = false
    @Published var showDockIcon = JarvisAppPreferences.showDockIcon
    @Published private(set) var setupRequired = false

    private let cli: any JarvisLineCommandRunning
    private let configStore: JarvisConfigStore
    private var setupInspectionState = SetupFirstRunInspectionState()
    private var confirmationID: UUID?
    private var cleanupStatusRefreshRequested = false
    private(set) var cleanupStatusRefreshTask: Task<Void, Never>?
    var onInitialSetupInspection: ((SetupInspection) -> Void)?

    init(
        cli: any JarvisLineCommandRunning = JarvisLineCLI(),
        configStore: JarvisConfigStore = JarvisConfigStore()
    ) {
        self.cli = cli
        self.configStore = configStore
    }

    var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
        return "App v\(version)"
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

    var validationIssues: [String] {
        config.blockingIssues(using: configContract)
    }

    var hasUnsavedChanges: Bool {
        config != savedConfig
    }

    var pendingApplyImpact: SettingsApplyImpact {
        SettingsApplyImpact.between(savedConfig, config)
    }

    func refresh() async {
        await run(label: "Refresh") {
            let preserveDraft = hasUnsavedChanges
            cliVersion = (try? await cli.run(["--version"]).trimmingCharacters(in: .whitespacesAndNewlines)) ?? "jarvis-line unavailable"
            await refreshConfigContract()
            let loadedConfig = try configStore.load(defaults: configContract.defaults.isEmpty ? nil : configContract.defaults)
            if !preserveDraft {
                config = loadedConfig
                savedConfig = loadedConfig
            }
            systemVoices = await JarvisLineCLI.systemVoices(preserving: config.systemVoice)
            let statusOutput = try await cli.run(["status"])
            let doctorOutput = try await cli.run(["doctor"])
            status = RuntimeStatus.parse(statusOutput)
            doctorText = doctorOutput
            codexHookInstalled = DoctorStatus.parse(doctorOutput).codexHookInstalled
            lastOutput = statusOutput
            await refreshTrace()
            await refreshSetupRequirementIfNeeded()
        }
    }

    func setupCompleted() async {
        setupRequired = false
        await refresh()
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

    func clearQueue() async {
        await command("Clear Queue", ["queue", "clear"])
        await refresh()
    }

    func checkForUpdates() async {
        var output = ""
        let succeeded = await run(label: "Check for Updates") {
            do {
                output = try await cli.run(["update", "check"])
            } catch let error as CLIError
                where error.stdout.localizedCaseInsensitiveContains("update available") {
                output = error.stdout
            }
            lastOutput = output
            updateStatusText = Self.updateStatusSummary(output)
        }
        if !succeeded {
            updateStatusText = "Check failed"
        }
    }

    func refreshCleanupStatus() async {
        await run(label: "Refresh Storage") {
            cleanupStatus = try await loadCleanupStatus()
        }
    }

    func requestCleanupStatusRefresh() {
        cleanupStatusRefreshRequested = true
        startCleanupStatusRefreshIfPossible()
    }

    func cleanStorage() async {
        await run(label: "Clean Storage") {
            var pendingError: Error?
            do {
                let result = try await runCleanupCommand()
                cleanupResultText = cleanupResultSummary(result)
            } catch {
                cleanupResultText = "Cleanup failed"
                pendingError = error
            }

            do {
                cleanupStatus = try await loadCleanupStatus()
            } catch {
                if pendingError == nil {
                    cleanupResultText += ". Status refresh unavailable"
                }
            }

            if let pendingError {
                throw pendingError
            }
        }
    }

    func installCodexHook() async {
        await command("Install Codex Hook", ["install", "codex"])
        await refresh()
    }

    func testVoice() async {
        await command("Test Voice", ["tts", "test", "--text", "Jarvis line test is ready."])
        await refresh()
    }

    func setAttentionAlertsEnabled(_ isEnabled: Bool) async {
        guard config.attentionEnabled != isEnabled else { return }

        let previousValue = config.attentionEnabled
        config.attentionEnabled = isEnabled
        let label = isEnabled ? "Enable Request Speech" : "Disable Request Speech"
        let succeeded = await run(label: label) {
            lastOutput = try await cli.run([
                "config", "set", "attention_enabled", isEnabled ? "true" : "false",
            ])
        }
        if !succeeded {
            config.attentionEnabled = previousValue
        } else {
            savedConfig.attentionEnabled = isEnabled
        }
    }

    func loadConfig() async {
        await run(label: "Load Config") {
            await refreshConfigContract()
            let loadedConfig = try configStore.load(defaults: configContract.defaults.isEmpty ? nil : configContract.defaults)
            config = loadedConfig
            savedConfig = loadedConfig
            systemVoices = await JarvisLineCLI.systemVoices(preserving: config.systemVoice)
            lastOutput = "Loaded config from \(configStore.displayPath)"
        }
    }

    func revertConfig() {
        config = savedConfig
        systemVoices = JarvisLineCLI.voiceOptions(systemVoices, preserving: config.systemVoice)
        errorMessage = nil
        showSettingsConfirmation("Changes reverted")
    }

    @discardableResult
    func applyConfig() async -> Bool {
        let draft = config
        let impact = pendingApplyImpact
        guard impact != .none else { return true }

        let issues = validationIssues
        guard issues.isEmpty else {
            errorMessage = ConfigValidationError(issues: issues).localizedDescription
            return false
        }

        settingsConfirmation = nil
        let succeeded = await run(label: "Apply Settings") {
            try configStore.save(draft, contract: configContract)
            lastOutput = "Saved config to \(configStore.displayPath)"
            if impact == .restartRuntime {
                lastOutput += "\n" + (try await cli.run(["restart"]))
            }
            let doctorOutput = try await cli.run(["doctor"])
            doctorText = doctorOutput
            codexHookInstalled = DoctorStatus.parse(doctorOutput).codexHookInstalled
            savedConfig = draft
        }
        if succeeded {
            showSettingsConfirmation(
                impact == .restartRuntime
                    ? "Settings applied and runtime restarted"
                    : "Settings applied"
            )
        }
        return succeeded
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

    func setDockIconVisible(_ isVisible: Bool) {
        showDockIcon = isVisible
        JarvisAppPreferences.showDockIcon = isVisible
        AppDelegate.applyDockVisibility(isVisible)
    }

    private func command(_ label: String, _ args: [String]) async {
        await run(label: label) {
            lastOutput = try await cli.run(args)
        }
    }

    private func refreshConfigContract() async {
        guard let output = try? await cli.run(["config", "contract"]),
              let contract = try? JarvisConfigContract.fromJSON(output) else {
            return
        }
        configContract = contract
    }

    private func refreshTrace() async {
        guard let output = try? await cli.run(["trace", "--limit", "12", "--json"]),
              let data = output.data(using: .utf8),
              let decoded = try? JSONDecoder().decode([RuntimeTraceEvent].self, from: data) else {
            return
        }
        traceEvents = decoded
    }

    private func loadCleanupStatus() async throws -> StorageCleanupStatus {
        do {
            return try StorageCleanupStatus.decode(
                try await cli.run(["cleanup", "status", "--json"])
            )
        } catch let error as CLIError {
            guard let status = try? StorageCleanupStatus.decode(error.stdout) else {
                throw StorageCleanupModelError.commandFailed
            }
            return status
        } catch is DecodingError {
            throw StorageCleanupModelError.invalidResponse
        }
    }

    private func runCleanupCommand() async throws -> StorageCleanupStatus {
        do {
            return try StorageCleanupStatus.decode(
                try await cli.run(["cleanup", "run", "--json"])
            )
        } catch let error as CLIError {
            guard let status = try? StorageCleanupStatus.decode(error.stdout) else {
                throw StorageCleanupModelError.commandFailed
            }
            return status
        } catch is DecodingError {
            throw StorageCleanupModelError.invalidResponse
        }
    }

    private func cleanupResultSummary(_ result: StorageCleanupStatus) -> String {
        if result.alreadyRunning {
            return "Cleanup already running"
        }

        let fileWord = result.removedFiles == 1 ? "file" : "files"
        let summary = "\(result.removedFiles) \(fileWord) removed, \(result.recoveredText) recovered"
        guard result.errorCount > 0 else { return summary }
        let errorWord = result.errorCount == 1 ? "error" : "errors"
        return "\(summary); \(result.errorCount) \(errorWord)"
    }

    private func refreshSetupRequirementIfNeeded() async {
        guard setupInspectionState.beginInspection() else { return }
        guard let inspection = try? await inspectSetup(using: cli) else {
            setupInspectionState.recordFailedInspection()
            return
        }
        setupInspectionState.recordSuccessfulInspection()
        setupRequired = !inspection.configExists
        onInitialSetupInspection?(inspection)
    }

    private func startCleanupStatusRefreshIfPossible() {
        guard cleanupStatusRefreshRequested,
              !isBusy,
              cleanupStatusRefreshTask == nil else {
            return
        }

        cleanupStatusRefreshTask = Task { @MainActor [weak self] in
            guard let self else { return }
            guard !self.isBusy else {
                self.cleanupStatusRefreshTask = nil
                return
            }

            self.cleanupStatusRefreshRequested = false
            await self.refreshCleanupStatus()
            self.cleanupStatusRefreshTask = nil
            self.startCleanupStatusRefreshIfPossible()
        }
    }

    @discardableResult
    private func run(label: String, operation: () async throws -> Void) async -> Bool {
        guard !isBusy else { return false }
        isBusy = true
        errorMessage = nil
        defer {
            isBusy = false
            startCleanupStatusRefreshIfPossible()
        }

        do {
            try await operation()
            return true
        } catch {
            errorMessage = "\(label) failed: \(error.localizedDescription)"
            return false
        }
    }

    private func open(path: String) {
        let expanded = NSString(string: path).expandingTildeInPath
        NSWorkspace.shared.open(URL(fileURLWithPath: expanded))
    }

    private func showSettingsConfirmation(_ message: String) {
        let id = UUID()
        confirmationID = id
        settingsConfirmation = message
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { [weak self] in
            guard self?.confirmationID == id else { return }
            self?.settingsConfirmation = nil
            self?.confirmationID = nil
        }
    }

    private static func updateStatusSummary(_ output: String) -> String {
        let lines = output
            .split(separator: "\n")
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }

        if let latest = lines.first(where: { $0.hasPrefix("Latest version:") }) {
            return latest.replacingOccurrences(of: "Latest version:", with: "Latest")
        }
        if lines.contains(where: { $0.localizedCaseInsensitiveContains("up to date") }) {
            return "Up to date"
        }
        if lines.contains(where: { $0.localizedCaseInsensitiveContains("update available") }) {
            return "Update available"
        }
        return lines.first ?? "Check completed"
    }
}

private enum StorageCleanupModelError: LocalizedError {
    case invalidResponse
    case commandFailed

    var errorDescription: String? {
        switch self {
        case .invalidResponse: "Invalid cleanup response"
        case .commandFailed: "Cleanup command failed"
        }
    }
}

@MainActor
final class SettingsWindowController: NSObject, NSWindowDelegate {
    static let shared = SettingsWindowController()
    private var window: NSWindow?
    private weak var model: JarvisLineModel?
    private var isClosingAfterDecision = false

    func show(model: JarvisLineModel) {
        if let window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        self.model = model
        let rootView = SettingsWindowView(model: model)
            .frame(minWidth: 700, minHeight: 660)
        let hostingController = NSHostingController(rootView: rootView)
        let window = NSWindow(contentViewController: hostingController)
        window.title = "Jarvis Line Settings"
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        window.setContentSize(NSSize(width: 860, height: 720))
        window.minSize = NSSize(width: 700, height: 660)
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = NSColor(red: 0.05, green: 0.06, blue: 0.08, alpha: 1)
        window.titlebarAppearsTransparent = false
        window.toolbarStyle = .unifiedCompact
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
        model = nil
        isClosingAfterDecision = false
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard !isClosingAfterDecision else { return true }
        guard let model else { return true }

        switch SettingsCloseDecision.resolve(hasUnsavedChanges: model.hasUnsavedChanges) {
        case .close:
            return true
        case .applyAndClose, .revertAndClose, .keepOpen:
            presentCloseConfirmation(for: sender, model: model)
            return false
        }
    }

    private func presentCloseConfirmation(for window: NSWindow, model: JarvisLineModel) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Apply changes before closing?"
        alert.informativeText = "Your unapplied Jarvis Line settings will otherwise be discarded."
        let applyButton = alert.addButton(withTitle: "Apply")
        alert.addButton(withTitle: "Discard")
        alert.addButton(withTitle: "Cancel")
        applyButton.isEnabled = model.validationIssues.isEmpty && !model.isBusy

        alert.beginSheetModal(for: window) { [weak self, weak window] response in
            guard let self, let window else { return }
            let choice: SettingsCloseChoice
            switch response {
            case .alertFirstButtonReturn: choice = .apply
            case .alertSecondButtonReturn: choice = .discard
            default: choice = .cancel
            }

            switch SettingsCloseDecision.resolve(
                hasUnsavedChanges: model.hasUnsavedChanges,
                choice: choice
            ) {
            case .close:
                self.close(window)
            case .applyAndClose:
                Task {
                    if await model.applyConfig() {
                        self.close(window)
                    }
                }
            case .revertAndClose:
                model.revertConfig()
                self.close(window)
            case .keepOpen:
                break
            }
        }
    }

    private func close(_ window: NSWindow) {
        isClosingAfterDecision = true
        window.close()
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

    var body: some View {
        quickBody
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
            quickFooter
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
                    versionChip("Preview")
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
            if model.setupRequired {
                Button {
                    AppDelegate.showSetupWindow?()
                } label: {
                    Label("Complete Setup", systemImage: "checklist")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(JarvisTheme.gold)
            }
            compactStatus
            attentionControl
            commandDeck
        }
        .padding(14)
    }

    private var attentionControl: some View {
        HStack(spacing: 10) {
            Image(systemName: "bell.and.waves.left.and.right")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(JarvisTheme.goldSoft)
                .frame(width: 28, height: 28)
                .background(JarvisTheme.gold.opacity(0.11))
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                Text("Attention alerts")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text("Speak permission and Plan requests")
                    .font(.system(size: 11))
                    .foregroundStyle(JarvisTheme.mutedText)
            }

            Spacer()

            Toggle("Attention alerts", isOn: Binding(
                get: { model.config.attentionEnabled },
                set: { isEnabled in
                    Task { await model.setAttentionAlertsEnabled(isEnabled) }
                }
            ))
            .labelsHidden()
            .toggleStyle(.switch)
            .disabled(model.isBusy || !model.config.speechEnabled || model.config.speakMode == "off")
            .help("Speak a short alert when an agent needs permission or input.")
        }
        .padding(10)
        .background(sectionFill)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(sectionStroke)
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

    private var quickFooter: some View {
        HStack {
            Text("Jarvis Line Manager")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(JarvisTheme.subtleText)
            Spacer()
            Button {
                SettingsWindowController.shared.show(model: model)
            } label: {
                Label("Settings", systemImage: "gearshape")
            }
            .buttonStyle(.link)
            .foregroundStyle(JarvisTheme.cyan)
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
    static let healthy = Color(red: 0.35, green: 0.78, blue: 0.58)
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

protocol JarvisLineCommandRunning: Sendable {
    func run(_ args: [String], stdin: Data?) async throws -> String
}

extension JarvisLineCommandRunning {
    func run(_ args: [String]) async throws -> String {
        try await run(args, stdin: nil)
    }
}

final class CLIProcessState: @unchecked Sendable {
    private let lock = NSLock()
    private var output = Data()
    private var error = Data()
    private var didResume = false
    private var timeoutTimer: DispatchSourceTimer?

    func armTimeout(
        after seconds: TimeInterval,
        process: Process,
        processGroupIsolated: Bool,
        continuation: CheckedContinuation<String, Error>
    ) {
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            self.timeout(
                continuation,
                after: seconds,
                process: process,
                processGroupIsolated: processGroupIsolated
            )
        }
        timer.schedule(deadline: .now() + seconds)

        lock.lock()
        guard !didResume else {
            lock.unlock()
            timer.activate()
            timer.cancel()
            return
        }
        timeoutTimer = timer
        lock.unlock()
        timer.activate()
    }

    private func timeout(
        _ continuation: CheckedContinuation<String, Error>,
        after seconds: TimeInterval,
        process: Process,
        processGroupIsolated: Bool
    ) {
        lock.lock()
        guard !didResume else {
            lock.unlock()
            return
        }
        didResume = true
        let timeoutTimer = timeoutTimer
        self.timeoutTimer = nil
        lock.unlock()
        timeoutTimer?.setEventHandler {}
        timeoutTimer?.cancel()

        let pid = process.processIdentifier
        if processGroupIsolated {
            if Darwin.kill(-pid, SIGKILL) != 0, process.isRunning {
                Darwin.kill(pid, SIGKILL)
            }
        } else if process.isRunning {
            process.terminate()
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 2) {
                if process.isRunning {
                    Darwin.kill(pid, SIGKILL)
                }
            }
        }
        continuation.resume(
            throwing: SetupContractError.commandTimedOut(
                max(1, Int(seconds.rounded(.up)))
            )
        )
    }

    func setOutput(_ data: Data) {
        lock.lock()
        output = data
        lock.unlock()
    }

    func setError(_ data: Data) {
        lock.lock()
        error = data
        lock.unlock()
    }

    func resume(
        _ continuation: CheckedContinuation<String, Error>,
        terminationStatus: Int32
    ) {
        lock.lock()
        guard !didResume else {
            lock.unlock()
            return
        }
        didResume = true
        let timeoutTimer = timeoutTimer
        self.timeoutTimer = nil
        let output = String(data: output, encoding: .utf8) ?? ""
        let error = String(data: error, encoding: .utf8) ?? ""
        lock.unlock()
        timeoutTimer?.setEventHandler {}
        timeoutTimer?.cancel()

        if terminationStatus == 0 {
            continuation.resume(returning: output)
        } else {
            continuation.resume(throwing: CLIError(stdout: output, stderr: error))
        }
    }

    func resume(_ continuation: CheckedContinuation<String, Error>, throwing error: Error) {
        lock.lock()
        guard !didResume else {
            lock.unlock()
            return
        }
        didResume = true
        let timeoutTimer = timeoutTimer
        self.timeoutTimer = nil
        lock.unlock()
        timeoutTimer?.setEventHandler {}
        timeoutTimer?.cancel()
        continuation.resume(throwing: error)
    }
}

struct JarvisLineCLI: JarvisLineCommandRunning {
    private static let maximumStdinBytes = SetupPlanPayload.maximumEncodedBytes
    private let executable: String?
    private let timeoutSeconds: TimeInterval?
    private let isolateProcessGroup: Bool?

    init(
        executable: String? = nil,
        timeoutSeconds: TimeInterval? = nil,
        isolateProcessGroup: Bool? = nil
    ) {
        self.executable = executable
        self.timeoutSeconds = timeoutSeconds
        self.isolateProcessGroup = isolateProcessGroup
    }

    func run(_ args: [String], stdin: Data? = nil) async throws -> String {
        if let stdin, stdin.count > Self.maximumStdinBytes {
            throw SetupContractError.payloadTooLarge(stdin.count)
        }

        let executable = executable ?? findExecutable()
        let timeout = timeoutSeconds ?? defaultTimeout(for: args)
        let processGroupIsolated = isolateProcessGroup
            ?? (URL(fileURLWithPath: executable).lastPathComponent == "jarvis-line")
        return try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = args
            if processGroupIsolated {
                var environment = ProcessInfo.processInfo.environment
                environment["JARVIS_LINE_ISOLATE_PROCESS_GROUP"] = "1"
                process.environment = environment
            }

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            let inputPipe = stdin == nil ? nil : Pipe()
            process.standardOutput = outputPipe
            process.standardError = errorPipe
            process.standardInput = inputPipe

            let state = CLIProcessState()
            let drainGroup = DispatchGroup()
            drainGroup.enter()
            drainGroup.enter()

            process.terminationHandler = { proc in
                drainGroup.notify(queue: .global(qos: .utility)) {
                    state.resume(continuation, terminationStatus: proc.terminationStatus)
                }
            }

            do {
                try process.run()
            } catch {
                state.resume(continuation, throwing: error)
                return
            }
            state.armTimeout(
                after: timeout,
                process: process,
                processGroupIsolated: processGroupIsolated,
                continuation: continuation
            )

            DispatchQueue.global(qos: .utility).async {
                state.setOutput(outputPipe.fileHandleForReading.readDataToEndOfFile())
                drainGroup.leave()
            }
            DispatchQueue.global(qos: .utility).async {
                state.setError(errorPipe.fileHandleForReading.readDataToEndOfFile())
                drainGroup.leave()
            }
            if let stdin, let inputPipe {
                DispatchQueue.global(qos: .utility).async {
                    defer { try? inputPipe.fileHandleForWriting.close() }
                    try? inputPipe.fileHandleForWriting.write(contentsOf: stdin)
                }
            }
        }
    }

    private func defaultTimeout(for args: [String]) -> TimeInterval {
        if args.starts(with: ["setup", "apply"]) {
            return 15 * 60
        }
        return 60
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

    static func systemVoices(preserving current: String) async -> [String] {
        await Task.detached(priority: .utility) {
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
                return voiceOptions(voices, preserving: current)
            }

            return voiceOptions(voices, preserving: current)
        }.value
    }

    static func voiceOptions(_ voices: [String], preserving current: String) -> [String] {
        var options = voices
        if options.first != "" {
            options.insert("", at: 0)
        }

        let value = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !value.isEmpty && !options.contains(value) {
            options.append(value)
        }
        return options
    }
}

struct CLIError: LocalizedError, Sendable {
    let stdout: String
    let stderr: String

    init(_ message: String) {
        self.init(stdout: "", stderr: message)
    }

    init(stdout: String, stderr: String) {
        self.stdout = stdout
        self.stderr = stderr
    }

    var message: String {
        [stdout, stderr]
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var errorDescription: String? {
        message.isEmpty ? "jarvis-line command failed" : message
    }
}
