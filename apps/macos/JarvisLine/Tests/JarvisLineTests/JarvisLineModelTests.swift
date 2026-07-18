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
