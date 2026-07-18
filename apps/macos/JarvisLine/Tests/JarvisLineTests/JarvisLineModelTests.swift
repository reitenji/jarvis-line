import Foundation
import Testing
@testable import JarvisLine

@MainActor
struct JarvisLineModelTests {
    @Test func draftTracksEditsAndRevertRestoresSavedConfig() {
        let model = JarvisLineModel(cli: ModelFakeRunner())

        #expect(!model.hasUnsavedChanges)
        model.config.volume = 0.6
        #expect(model.hasUnsavedChanges)
        #expect(model.pendingApplyImpact == .restartRuntime)

        model.revertConfig()

        #expect(!model.hasUnsavedChanges)
        #expect(model.config.volume == JarvisConfigDraft.defaults.volume)
    }

    @Test func updateOnlyApplySavesWithoutRestart() async {
        let runner = ModelFakeRunner(output: "[OK] Codex hooks.json")
        let (store, path) = temporaryConfigStore()
        defer { try? FileManager.default.removeItem(at: path) }
        let model = JarvisLineModel(cli: runner, configStore: store)
        model.config.updateCheckIntervalHours = 48

        let succeeded = await model.applyConfig()

        #expect(succeeded)
        #expect(!model.hasUnsavedChanges)
        #expect(model.settingsConfirmation == "Settings applied")
        let calls = await runner.calls
        #expect(calls == [["doctor"]])
    }

    @Test func runtimeApplyRestartsBeforeCheckingHealth() async {
        let runner = ModelFakeRunner(output: "[OK] Codex hooks.json")
        let (store, path) = temporaryConfigStore()
        defer { try? FileManager.default.removeItem(at: path) }
        let model = JarvisLineModel(cli: runner, configStore: store)
        model.config.volume = 0.6

        let succeeded = await model.applyConfig()

        #expect(succeeded)
        #expect(!model.hasUnsavedChanges)
        #expect(model.settingsConfirmation == "Settings applied and runtime restarted")
        let calls = await runner.calls
        #expect(calls == [["restart"], ["doctor"]])
    }

    @Test func failedApplyKeepsTheEditedDraft() async {
        let runner = ModelFakeRunner(failureMessage: "restart failed")
        let (store, path) = temporaryConfigStore()
        defer { try? FileManager.default.removeItem(at: path) }
        let model = JarvisLineModel(cli: runner, configStore: store)
        model.config.volume = 0.6

        let succeeded = await model.applyConfig()

        #expect(!succeeded)
        #expect(model.hasUnsavedChanges)
        #expect(model.config.volume == 0.6)
        #expect(model.errorMessage == "Apply Settings failed: restart failed")
    }

    @Test func requestSpeechTogglePersistsOnlyTheAttentionFlag() async {
        let runner = ModelFakeRunner(output: "Set attention_enabled = True")
        let model = JarvisLineModel(cli: runner)

        await model.setAttentionAlertsEnabled(true)

        #expect(model.config.attentionEnabled)
        #expect(!model.hasUnsavedChanges)
        #expect(model.errorMessage == nil)
        let calls = await runner.calls
        #expect(calls == [
            ["config", "set", "attention_enabled", "true"],
        ])
    }

    @Test func requestSpeechToggleRollsBackWhenPersistenceFails() async {
        let runner = ModelFakeRunner(failureMessage: "config write failed")
        let model = JarvisLineModel(cli: runner)
        model.config.attentionEnabled = true

        await model.setAttentionAlertsEnabled(false)

        #expect(model.config.attentionEnabled)
        #expect(model.errorMessage == "Disable Request Speech failed: config write failed")
    }

    @Test func invalidDraftCannotBeAppliedFromTheClosePrompt() async {
        let runner = ModelFakeRunner()
        let model = JarvisLineModel(cli: runner)
        model.config.tts = "command"
        model.config.command = ""

        let succeeded = await model.applyConfig()

        #expect(!succeeded)
        #expect(model.hasUnsavedChanges)
        #expect(model.errorMessage?.contains("Command backend requires a command") == true)
        #expect(await runner.calls.isEmpty)
    }

    @Test func updateCheckTreatsTheAvailableExitCodeAsAResult() async {
        let runner = UpdateAvailableRunner()
        let model = JarvisLineModel(cli: runner)

        await model.checkForUpdates()

        #expect(model.errorMessage == nil)
        #expect(model.updateStatusText == "Latest 0.6.0")
        #expect(await runner.calls == [["update", "check"]])
    }

    @Test func clearQueueRunsTheDedicatedCommandBeforeRefreshing() async {
        let runner = ModelFakeRunner()
        let model = JarvisLineModel(cli: runner)

        await model.clearQueue()

        let calls = await runner.calls
        #expect(calls.first == ["queue", "clear"])
        #expect(calls.contains(["status"]))
        #expect(calls.contains(["doctor"]))
    }

    @Test func cleanupStatusAndRunUseDedicatedJSONCommands() async {
        let runner = CleanupModelRunner(
            statusOutput: cleanupJSON(),
            runResponse: .output(cleanupJSON(
                mode: "run",
                eligibleFiles: 12,
                eligibleBytes: 50_331_648,
                removedFiles: 12,
                removedBytes: 50_331_648
            ))
        )
        let model = JarvisLineModel(cli: runner)

        await model.refreshCleanupStatus()
        await model.cleanStorage()

        #expect(await runner.calls == [
            ["cleanup", "status", "--json"],
            ["cleanup", "run", "--json"],
            ["cleanup", "status", "--json"],
        ])
        #expect(model.cleanupStatus.eligibleFiles == 0)
        #expect(
            model.cleanupResultText
                == "12 files removed, \(ByteCountFormatter.string(fromByteCount: 50_331_648, countStyle: .file)) recovered"
        )
    }

    @Test func cleanupUsesDecodableStdoutFromPartialFailure() async {
        let runner = CleanupModelRunner(
            statusOutput: cleanupJSON(),
            runResponse: .failure(
                stdout: cleanupJSON(
                    mode: "run",
                    eligibleFiles: 5,
                    eligibleBytes: 20_000,
                    removedFiles: 3,
                    removedBytes: 12_000,
                    errorCount: 2
                ),
                stderr: "/Users/private/generated.wav"
            )
        )
        let model = JarvisLineModel(cli: runner)

        await model.cleanStorage()

        #expect(model.cleanupResultText.contains("3 files removed"))
        #expect(model.cleanupResultText.contains("2 errors"))
        #expect(model.errorMessage == nil)
        #expect(!model.cleanupResultText.contains("/Users/"))
    }

    @Test func cleanupDistinguishesAlreadyRunningResult() async {
        let runner = CleanupModelRunner(
            statusOutput: cleanupJSON(),
            runResponse: .output(cleanupJSON(mode: "run", alreadyRunning: true))
        )
        let model = JarvisLineModel(cli: runner)

        await model.cleanStorage()

        #expect(model.cleanupResultText == "Cleanup already running")
    }

    @Test func cleanupParseFailurePreservesOrdinaryRuntimeStatusAndPrivacy() async {
        let runner = CleanupModelRunner(
            statusOutput: "not-json /Users/private/audio.wav",
            runResponse: .failure(stdout: "", stderr: "/Users/private/audio.wav")
        )
        let model = JarvisLineModel(cli: runner)
        model.status = RuntimeStatus.parse("watcher: running (pid 42)")
        let originalWatcher = model.status.watcher
        let originalState = model.status.watcherState

        await model.refreshCleanupStatus()

        #expect(model.status.watcher == originalWatcher)
        #expect(model.status.watcherState == originalState)
        #expect(model.cleanupStatus == .empty)
        #expect(model.errorMessage == "Refresh Storage failed: Invalid cleanup response")
        #expect(model.errorMessage?.contains("/Users/") == false)

        await model.cleanStorage()

        #expect(model.status.watcher == originalWatcher)
        #expect(model.status.watcherState == originalState)
        #expect(model.cleanupResultText == "Cleanup failed")
        #expect(model.errorMessage == "Clean Storage failed: Cleanup command failed")
        #expect(model.errorMessage?.contains("/Users/") == false)
    }

    @Test func cleanupCommandsDoNotStartWhileAnotherOperationIsBusy() async {
        let runner = CleanupModelRunner(
            statusOutput: cleanupJSON(),
            runResponse: .output(cleanupJSON(mode: "run"))
        )
        let model = JarvisLineModel(cli: runner)
        model.isBusy = true

        await model.refreshCleanupStatus()
        await model.cleanStorage()

        #expect(await runner.calls.isEmpty)
    }

    @Test func voiceOptionsPreserveAConfiguredVoiceWithoutDuplicates() {
        #expect(
            JarvisLineCLI.voiceOptions(
                ["", "Samantha"],
                preserving: "Siri Voice 2"
            ) == ["", "Samantha", "Siri Voice 2"]
        )
        #expect(
            JarvisLineCLI.voiceOptions(
                ["", "Samantha"],
                preserving: "Samantha"
            ) == ["", "Samantha"]
        )
    }
}

private func cleanupJSON(
    mode: String = "status",
    eligibleFiles: Int = 0,
    eligibleBytes: Int = 0,
    removedFiles: Int = 0,
    removedBytes: Int = 0,
    errorCount: Int = 0,
    alreadyRunning: Bool = false
) -> String {
    #"""
    {
      "mode":"\#(mode)",
      "eligible_files":\#(eligibleFiles),
      "eligible_bytes":\#(eligibleBytes),
      "removed_files":\#(removedFiles),
      "removed_bytes":\#(removedBytes),
      "skipped_files":0,
      "error_count":\#(errorCount),
      "errors":[],
      "already_running":\#(alreadyRunning),
      "last_success_at":null,
      "categories":{}
    }
    """#
}

private func temporaryConfigStore() -> (JarvisConfigStore, URL) {
    let path = FileManager.default.temporaryDirectory
        .appendingPathComponent("jarvis-line-model-\(UUID().uuidString).json")
    return (JarvisConfigStore(path: path), path)
}

private actor ModelFakeRunner: JarvisLineCommandRunning {
    private let output: String
    private let failureMessage: String?
    private(set) var calls: [[String]] = []

    init(output: String = "", failureMessage: String? = nil) {
        self.output = output
        self.failureMessage = failureMessage
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append(args)
        if let failureMessage {
            throw CLIError(failureMessage)
        }
        return output
    }
}

private actor UpdateAvailableRunner: JarvisLineCommandRunning {
    private(set) var calls: [[String]] = []

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append(args)
        throw CLIError(
            stdout: "Current version: 0.5.0\nLatest version: 0.6.0\nUpdate available.",
            stderr: ""
        )
    }
}

private actor CleanupModelRunner: JarvisLineCommandRunning {
    enum Response: Sendable {
        case output(String)
        case failure(stdout: String, stderr: String)
    }

    private let statusOutput: String
    private let runResponse: Response
    private(set) var calls: [[String]] = []

    init(statusOutput: String, runResponse: Response) {
        self.statusOutput = statusOutput
        self.runResponse = runResponse
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append(args)
        if args == ["cleanup", "status", "--json"] {
            return statusOutput
        }
        switch runResponse {
        case let .output(output):
            return output
        case let .failure(stdout, stderr):
            throw CLIError(stdout: stdout, stderr: stderr)
        }
    }
}
