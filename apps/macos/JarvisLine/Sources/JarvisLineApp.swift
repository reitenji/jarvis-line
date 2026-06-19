import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        SingleInstanceGuard.enforce()
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
    @StateObject private var model = JarvisLineModel()

    var body: some Scene {
        MenuBarExtra {
            JarvisLinePanel(model: model)
                .frame(width: 380)
                .task {
                    await model.refresh()
                }
        } label: {
            Image(systemName: model.statusIcon)
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
final class JarvisLineModel: ObservableObject {
    @Published var status = RuntimeStatus.empty
    @Published var config = JarvisConfigDraft.defaults
    @Published var doctorText = ""
    @Published var lastOutput = ""
    @Published var isBusy = false
    @Published var errorMessage: String?

    private let cli = JarvisLineCLI()
    private let configStore = JarvisConfigStore()

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
            let statusOutput = try await cli.run(["status"])
            let doctorOutput = try await cli.run(["doctor"])
            status = RuntimeStatus.parse(statusOutput)
            doctorText = doctorOutput
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

struct JarvisLinePanel: View {
    @ObservedObject var model: JarvisLineModel
    @State private var selectedTab = "runtime"

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            Picker("View", selection: $selectedTab) {
                Text("Runtime").tag("runtime")
                Text("Settings").tag("settings")
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            if selectedTab == "settings" {
                settings
            } else {
                statusGrid
                controls
                links
                output
            }
        }
        .padding(16)
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: model.statusIcon)
                .font(.system(size: 24))
                .foregroundStyle(model.status.watcherState == "running" ? .green : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text("Jarvis Line")
                    .font(.headline)
                Text(model.status.summary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if model.isBusy {
                ProgressView()
                    .controlSize(.small)
            }
        }
    }

    private var statusGrid: some View {
        Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 8) {
            statusRow("TTS", model.status.tts)
            statusRow("Watcher", model.status.watcher)
            statusRow("Worker", model.status.audioWorker)
            statusRow("Queue", "\(model.status.queueJobs)")
            statusRow("Speak Mode", model.status.speakMode)
            statusRow("RSS", model.status.audioWorkerRSS)
        }
        .font(.system(size: 12, design: .monospaced))
        .padding(10)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func statusRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label)
                .foregroundStyle(.secondary)
            Text(value.isEmpty ? "n/a" : value)
                .textSelection(.enabled)
        }
    }

    private var controls: some View {
        VStack(spacing: 8) {
            HStack {
                Button {
                    Task { await model.start() }
                } label: {
                    Label("Start", systemImage: "play.fill")
                }
                Button {
                    Task { await model.stop() }
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                }
                Button {
                    Task { await model.restart() }
                } label: {
                    Label("Restart", systemImage: "arrow.clockwise")
                }
            }
            HStack {
                Button {
                    Task { await model.repair() }
                } label: {
                    Label("Repair", systemImage: "wrench.and.screwdriver")
                }
                Button {
                    Task { await model.testVoice() }
                } label: {
                    Label("Test Voice", systemImage: "speaker.wave.2.fill")
                }
                Button {
                    Task { await model.refresh() }
                } label: {
                    Label("Refresh", systemImage: "arrow.triangle.2.circlepath")
                }
            }
            Button {
                Task { await model.installCodexHook() }
            } label: {
                Label("Install Codex Hook", systemImage: "link.badge.plus")
                    .frame(maxWidth: .infinity)
            }
        }
        .disabled(model.isBusy)
        .buttonStyle(.bordered)
    }

    private var links: some View {
        HStack {
            Button("Config File") { model.openConfig() }
            Button("Watcher Log") { model.openWatcherLog() }
            Button("Audio Log") { model.openAudioWorkerLog() }
            Spacer()
            Button("Quit") { NSApplication.shared.terminate(nil) }
        }
        .buttonStyle(.link)
    }

    private var settings: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                runtimeSettings
                ttsSettings
                updateSettings
                settingsActions
                output
            }
        }
        .frame(height: 500)
    }

    private var runtimeSettings: some View {
        GroupBox("Runtime") {
            VStack(alignment: .leading, spacing: 10) {
                Toggle("Speech enabled", isOn: $model.config.speechEnabled)
                Toggle("Speak without prefix", isOn: $model.config.speakWithoutPrefix)

                Picker("Speak mode", selection: $model.config.speakMode) {
                    Text("Final only").tag("final_only")
                    Text("Commentary + final").tag("commentary_and_final")
                    Text("Off").tag("off")
                }

                TextField("Line language", text: $model.config.lineLanguage)
                TextField("Assistant name", text: $model.config.assistantName)

                Stepper("Max spoken chars: \(model.config.maxSpokenChars)", value: $model.config.maxSpokenChars, in: 60...500, step: 10)
                Stepper("Max queue size: \(model.config.maxQueueSize)", value: $model.config.maxQueueSize, in: 1...50)
                TextField("Quiet hours, e.g. 22:00-08:00", text: $model.config.quietHours)
            }
        }
    }

    private var ttsSettings: some View {
        GroupBox("TTS") {
            VStack(alignment: .leading, spacing: 10) {
                Picker("Backend", selection: $model.config.tts) {
                    Text("Kokoro").tag("kokoro")
                    Text("System").tag("system")
                    Text("macOS").tag("macos")
                    Text("Command").tag("command")
                }

                HStack {
                    Text("Volume")
                    Slider(value: $model.config.volume, in: 0...1)
                    Text(String(format: "%.2f", model.config.volume))
                        .font(.system(size: 11, design: .monospaced))
                        .frame(width: 34, alignment: .trailing)
                }

                Picker("Fallback", selection: $model.config.fallbackTTS) {
                    Text("None").tag("none")
                    Text("System").tag("system")
                    Text("macOS").tag("macos")
                    Text("Command").tag("command")
                }

                Toggle("Warm TTS", isOn: $model.config.warmTTS)
                TextField("Warm-up text", text: $model.config.warmTTSText)

                Divider()
                Text("Backend options")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextField("Kokoro voice", text: $model.config.voice)
                TextField("Kokoro language, e.g. en-gb", text: $model.config.lang)
                HStack {
                    Text("Speed")
                    Slider(value: $model.config.speed, in: 0.6...1.5)
                    Text(String(format: "%.2f", model.config.speed))
                        .font(.system(size: 11, design: .monospaced))
                        .frame(width: 34, alignment: .trailing)
                }
                TextField("System voice", text: $model.config.systemVoice)
                Stepper("System rate: \(model.config.systemRate)", value: $model.config.systemRate, in: 80...360, step: 5)
                TextField("Command backend command", text: $model.config.command)
            }
        }
    }

    private var updateSettings: some View {
        GroupBox("Updates") {
            VStack(alignment: .leading, spacing: 10) {
                Toggle("Check for updates", isOn: $model.config.updateCheckEnabled)
                Stepper("Interval: \(model.config.updateCheckIntervalHours)h", value: $model.config.updateCheckIntervalHours, in: 1...168)
                Picker("Source", selection: $model.config.updateSource) {
                    Text("Git").tag("git")
                    Text("PyPI").tag("pypi")
                }
                TextField("Git repo", text: $model.config.updateGitRepo)
                TextField("Git ref", text: $model.config.updateGitRef)
            }
        }
    }

    private var settingsActions: some View {
        VStack(spacing: 8) {
            HStack {
                Button {
                    Task { await model.loadConfig() }
                } label: {
                    Label("Reload", systemImage: "arrow.clockwise")
                }
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
            .disabled(model.isBusy)
        }
    }

    @ViewBuilder
    private var output: some View {
        if let error = model.errorMessage {
            Text(error)
                .font(.caption)
                .foregroundStyle(.red)
                .textSelection(.enabled)
        } else if !model.doctorText.isEmpty {
            ScrollView {
                Text(model.doctorText)
                    .font(.system(size: 11, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .frame(height: 150)
            .padding(8)
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
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
