import Foundation
import Testing
@testable import JarvisLine

struct SetupContractTests {
    @Test func inspectionDecodesVersionedChoices() throws {
        let inspection = try SetupInspection.decode(#"{"version":1,"config_exists":false,"platform":"Darwin","languages":["English","Turkish"],"backend_options":[{"id":"kokoro","label":"Kokoro local","available":true,"ready":true,"recommended":true,"requires_install":false,"detail":"ready"}],"current":{"language":"English","tts":"kokoro","speak_mode":"final_only"}}"#)

        #expect(inspection.version == 1)
        #expect(inspection.backendOptions.first?.recommended == true)
        #expect(SetupFirstRunPolicy.shouldOffer(configExists: false, wasOffered: false))
        #expect(!SetupFirstRunPolicy.shouldOffer(configExists: true, wasOffered: false))
    }

    @Test func inspectionAcceptsCurrentPythonContractShape() throws {
        let inspection = try SetupInspection.decode(#"""
        {
          "version": 1,
          "environment": {"platform": "Darwin", "config_exists": false},
          "current": {"tts": "system"},
          "language": "English",
          "backend_options": [],
          "ui_options": {"line_language": ["English", "Turkish"]},
          "needs_setup": true
        }
        """#)

        #expect(inspection.configExists == false)
        #expect(inspection.platform == "Darwin")
        #expect(inspection.languages == ["English", "Turkish"])
        #expect(inspection.current.language == "English")
        #expect(inspection.current.tts == "system")
    }

    @Test func inspectionRejectsUnsupportedVersion() {
        #expect(throws: SetupContractError.self) {
            try SetupInspection.decode(#"{"version":2,"config_exists":false,"platform":"Darwin","languages":[],"backend_options":[],"current":{"language":"English","tts":"system","speak_mode":"final_only"}}"#)
        }
    }

    @Test func planEncodingUsesSnakeCaseAndNoInstructionPath() throws {
        let data = try SetupPlanPayload.defaults.encoded()
        let text = String(decoding: data, as: UTF8.self)

        #expect(text.contains("\"agent_target\""))
        #expect(text.contains("\"install_codex_hook\""))
        #expect(!text.contains("instruction_path"))
    }

    @Test func firstRunPolicyOffersOnlyOnceWithoutConfig() {
        #expect(SetupFirstRunPolicy.shouldOffer(configExists: false, wasOffered: false))
        #expect(!SetupFirstRunPolicy.shouldOffer(configExists: true, wasOffered: false))
        #expect(!SetupFirstRunPolicy.shouldOffer(configExists: false, wasOffered: true))
        #expect(!SetupFirstRunPolicy.shouldOffer(configExists: true, wasOffered: true))
    }

    @Test func setupHelpersUseMachineArgumentsAndBoundedPlanStdin() async throws {
        let runner = FakeSetupRunner(
            inspectionOutput: #"{"version":1,"config_exists":false,"platform":"Darwin","languages":["English"],"backend_options":[],"current":{"language":"English","tts":"system","speak_mode":"final_only"}}"#,
            applyOutput: #"{"version":1,"ok":true,"steps":[{"name":"config_write","ok":true}],"instruction":{"command":"jarvis-line instructions print codex --language \"English\"","filename":"AGENTS.md","scope":"project"}}"#
        )

        let inspection = try await inspectSetup(using: runner)
        let result = try await applySetup(SetupPlanPayload(inspection: inspection), using: runner)
        let calls = await runner.calls
        let payload = try #require(calls.last?.stdin)
        let encoded = try #require(JSONSerialization.jsonObject(with: payload) as? [String: Any])

        #expect(calls.map(\.args) == [
            ["setup", "inspect", "--json"],
            ["setup", "apply", "--stdin", "--json"],
        ])
        #expect(encoded["agent_target"] as? String == "codex")
        #expect(encoded["instruction_path"] == nil)
        #expect(result.steps.first?.id == "config_write")
        #expect(result.instruction.filename == "AGENTS.md")
    }

    @Test func applyResultRejectsUnsupportedVersion() {
        #expect(throws: SetupContractError.self) {
            try SetupApplyResult.decode(#"{"version":2,"ok":false,"steps":[],"instruction":{"command":"","filename":"AGENTS.md","scope":"project"}}"#)
        }
    }
}

private actor FakeSetupRunner: JarvisLineCommandRunning {
    struct Call: Sendable {
        let args: [String]
        let stdin: Data?
    }

    let inspectionOutput: String
    let applyOutput: String
    private(set) var calls: [Call] = []

    init(inspectionOutput: String, applyOutput: String) {
        self.inspectionOutput = inspectionOutput
        self.applyOutput = applyOutput
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append(Call(args: args, stdin: stdin))
        return args.contains("inspect") ? inspectionOutput : applyOutput
    }
}
