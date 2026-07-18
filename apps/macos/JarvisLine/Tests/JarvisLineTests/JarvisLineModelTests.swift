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

    @Test func cleanupSuccessSurvivesFailedStatusRefreshWithoutLeakingDetails() async {
        let priorStatus = cleanupJSON(eligibleFiles: 8, eligibleBytes: 32_000)
        let runner = CleanupModelRunner(
            statusResponses: [
                .output(priorStatus),
                .failure(stdout: "", stderr: "/Users/private/generated.wav: denied"),
            ],
            runResponse: .output(cleanupJSON(
                mode: "run",
                eligibleFiles: 8,
                eligibleBytes: 32_000,
                removedFiles: 8,
                removedBytes: 32_000
            ))
        )
        let model = JarvisLineModel(cli: runner)

        await model.refreshCleanupStatus()
        await model.cleanStorage()

        #expect(model.cleanupStatus.eligibleFiles == 8)
        #expect(model.cleanupResultText.contains("8 files removed"))
        #expect(model.cleanupResultText.hasSuffix(". Status refresh unavailable"))
        #expect(model.errorMessage == nil)
        #expect(!model.cleanupResultText.contains("/Users/"))
        #expect(await runner.calls == [
            ["cleanup", "status", "--json"],
            ["cleanup", "run", "--json"],
            ["cleanup", "status", "--json"],
        ])
    }

    @Test func cleanupPartialResultSurvivesFailedStatusRefreshWithoutLeakingDetails() async {
        let runner = CleanupModelRunner(
            statusResponses: [
                .failure(stdout: "private status output", stderr: "/Users/private/status.json"),
            ],
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

        #expect(model.cleanupStatus == .empty)
        #expect(model.cleanupResultText.contains("3 files removed"))
        #expect(model.cleanupResultText.contains("2 errors"))
        #expect(model.cleanupResultText.hasSuffix(". Status refresh unavailable"))
        #expect(model.errorMessage == nil)
        #expect(!model.cleanupResultText.contains("/Users/"))
        #expect(await runner.calls == [
            ["cleanup", "run", "--json"],
            ["cleanup", "status", "--json"],
        ])
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

    @Test func cleanupStatusRequestsWhileBusyCoalesceAndRunAfterOperationCompletes() async {
        let runner = ControllableCleanupRefreshRunner(statusOutput: cleanupJSON(eligibleFiles: 4))
        let model = JarvisLineModel(cli: runner)
        let operation = Task { await model.checkForUpdates() }
        await runner.waitUntilOperationIsBlocked()

        #expect(model.isBusy)
        model.requestCleanupStatusRefresh()
        model.requestCleanupStatusRefresh()
        model.requestCleanupStatusRefresh()
        #expect(await runner.calls == [["update", "check"]])

        await runner.finishOperation()
        await operation.value
        await runner.waitUntilCleanupStatusIsBlocked()
        #expect(await runner.calls == [
            ["update", "check"],
            ["cleanup", "status", "--json"],
        ])

        let refreshTask = model.cleanupStatusRefreshTask
        await runner.finishCleanupStatus()
        await refreshTask?.value

        #expect(model.cleanupStatus.eligibleFiles == 4)
        #expect(!model.isBusy)
        #expect(await runner.calls.filter { $0 == ["cleanup", "status", "--json"] }.count == 1)
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

    private var statusResponses: [Response]
    private let runResponse: Response
    private(set) var calls: [[String]] = []

    init(statusOutput: String, runResponse: Response) {
        self.statusResponses = [.output(statusOutput)]
        self.runResponse = runResponse
    }

    init(statusResponses: [Response], runResponse: Response) {
        self.statusResponses = statusResponses
        self.runResponse = runResponse
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append(args)
        if args == ["cleanup", "status", "--json"] {
            let response = statusResponses.count == 1
                ? statusResponses[0]
                : statusResponses.removeFirst()
            return try Self.resolve(response)
        }
        return try Self.resolve(runResponse)
    }

    private static func resolve(_ response: Response) throws -> String {
        switch response {
        case let .output(output):
            return output
        case let .failure(stdout, stderr):
            throw CLIError(stdout: stdout, stderr: stderr)
        }
    }
}

private actor ControllableCleanupRefreshRunner: JarvisLineCommandRunning {
    private let statusOutput: String
    private var operationContinuation: CheckedContinuation<Void, Never>?
    private var cleanupStatusContinuation: CheckedContinuation<Void, Never>?
    private var operationWaiters: [CheckedContinuation<Void, Never>] = []
    private var cleanupStatusWaiters: [CheckedContinuation<Void, Never>] = []
    private var operationIsBlocked = false
    private var cleanupStatusIsBlocked = false
    private(set) var calls: [[String]] = []

    init(statusOutput: String) {
        self.statusOutput = statusOutput
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append(args)
        if args == ["update", "check"] {
            operationIsBlocked = true
            operationWaiters.forEach { $0.resume() }
            operationWaiters.removeAll()
            await withCheckedContinuation { operationContinuation = $0 }
            return "Up to date"
        }
        if args == ["cleanup", "status", "--json"] {
            cleanupStatusIsBlocked = true
            cleanupStatusWaiters.forEach { $0.resume() }
            cleanupStatusWaiters.removeAll()
            await withCheckedContinuation { cleanupStatusContinuation = $0 }
            return statusOutput
        }
        return ""
    }

    func waitUntilOperationIsBlocked() async {
        guard !operationIsBlocked else { return }
        await withCheckedContinuation { operationWaiters.append($0) }
    }

    func waitUntilCleanupStatusIsBlocked() async {
        guard !cleanupStatusIsBlocked else { return }
        await withCheckedContinuation { cleanupStatusWaiters.append($0) }
    }

    func finishOperation() {
        operationContinuation?.resume()
        operationContinuation = nil
    }

    func finishCleanupStatus() {
        cleanupStatusContinuation?.resume()
        cleanupStatusContinuation = nil
    }
}
