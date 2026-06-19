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
                .frame(width: 460)
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
    @Published var cliVersion = "jarvis-line unknown"
    @Published var systemVoices: [String] = [""]
    @Published var doctorText = ""
    @Published var lastOutput = ""
    @Published var isBusy = false
    @Published var errorMessage: String?

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
        .background(.regularMaterial)
    }

    private var header: some View {
        HStack(spacing: 12) {
            appMark
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text("Jarvis Line")
                        .font(.title3.weight(.semibold))
                    statusPill
                }
                Text("\(model.status.summary) • \(model.cliVersion)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(model.appVersion)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
            if model.isBusy {
                ProgressView()
                    .controlSize(.small)
            }
        }
        .padding(12)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var appMark: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.accentColor.opacity(0.16))
            if let image = NSImage(named: "AppIcon") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(5)
            } else {
                Image(systemName: model.statusIcon)
                    .font(.system(size: 25, weight: .semibold))
                    .foregroundStyle(Color.accentColor)
            }
        }
        .frame(width: 48, height: 48)
    }

    private var statusPill: some View {
        Label(model.status.watcherState == "running" ? "Live" : "Stopped", systemImage: model.status.watcherState == "running" ? "checkmark.circle.fill" : "pause.circle")
            .font(.caption.weight(.semibold))
            .labelStyle(.titleAndIcon)
            .foregroundStyle(model.status.watcherState == "running" ? .green : .secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background((model.status.watcherState == "running" ? Color.green : Color.secondary).opacity(0.12))
            .clipShape(Capsule())
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
        .padding(12)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 10))
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
                validationSummary
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

                Picker("Line language", selection: $model.config.lineLanguage) {
                    ForEach(JarvisConfigDraft.lineLanguageOptions, id: \.self) { value in
                        Text(value).tag(value)
                    }
                }

                LabeledContent("Assistant") {
                    Text("Jarvis").foregroundStyle(.secondary)
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
        }
    }

    private var ttsSettings: some View {
        GroupBox("TTS") {
            VStack(alignment: .leading, spacing: 10) {
                Picker("Backend", selection: $model.config.tts) {
                    Text("Kokoro · bundled default").tag("kokoro")
                    Text("System voice").tag("system")
                    Text("macOS say").tag("macos")
                    Text("Custom command").tag("command")
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

                Divider()
                Text("Backend options")
                    .font(.caption)
                    .foregroundStyle(.secondary)

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
        }
    }

    private var updateSettings: some View {
        GroupBox("Updates") {
            VStack(alignment: .leading, spacing: 10) {
                Toggle("Check for updates", isOn: $model.config.updateCheckEnabled)
                Picker("Interval", selection: $model.config.updateCheckIntervalHours) {
                    ForEach(JarvisConfigDraft.updateIntervalOptions, id: \.self) { value in
                        Text(value == 168 ? "Weekly" : "\(value) hours").tag(value)
                    }
                }
                Picker("Source", selection: $model.config.updateSource) {
                    Text("Git").tag("git")
                    Text("PyPI").tag("pypi")
                }
                if model.config.updateSource == "git" {
                    Picker("Git repo", selection: $model.config.updateGitRepo) {
                        ForEach(options(JarvisConfigDraft.updateRepoOptions, preserving: model.config.updateGitRepo), id: \.self) { value in
                            Text(repoLabel(value)).tag(value)
                        }
                    }
                    Picker("Git ref", selection: $model.config.updateGitRef) {
                        ForEach(options(JarvisConfigDraft.updateRefOptions, preserving: model.config.updateGitRef), id: \.self) { value in
                            Text(refLabel(value)).tag(value)
                        }
                    }
                }
            }
        }
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
            .font(.caption)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 8))
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

    private func repoLabel(_ value: String) -> String {
        if value == "https://github.com/reitenji/jarvis-line.git" {
            return "Official GitHub"
        }
        if value == "ssh://git@github.com-personal/reitenji/jarvis-line.git" {
            return "Personal SSH"
        }
        return "Current custom repo"
    }

    private func refLabel(_ value: String) -> String {
        switch value {
        case "latest": return "Latest release"
        case "main": return "main"
        case "develop": return "develop"
        default: return value
        }
    }

    private func shortCommand(_ value: String) -> String {
        value.count > 42 ? String(value.prefix(42)) + "..." : value
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
            .disabled(model.isBusy || !model.config.blockingIssues.isEmpty)
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
