import Foundation
import Testing
@testable import JarvisLine

@MainActor
struct JarvisLineModelTests {
    @Test func requestSpeechTogglePersistsOnlyTheAttentionFlag() async {
        let runner = ModelFakeRunner(output: "Set attention_enabled = True")
        let model = JarvisLineModel(cli: runner)

        await model.setAttentionAlertsEnabled(true)

        #expect(model.config.attentionEnabled)
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
