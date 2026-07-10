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
            applyOutput: #"""
            {"version":1,"ok":true,"steps":[{"name":"config_write","ok":true}],"instruction":{"target":"codex","command":"jarvis-line instructions print codex --language \"English\"","filename":"AGENTS.md","scope":"project","destination":"/tmp/project","text":"## Jarvis Line"}}
            """#
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
        #expect(result.instruction.target == "codex")
        #expect(result.instruction.filename == "AGENTS.md")
        #expect(result.instruction.destination == "/tmp/project")
        #expect(result.instruction.text == "## Jarvis Line")
    }

    @Test func applyResultRejectsUnsupportedVersion() {
        #expect(throws: SetupContractError.self) {
            try SetupApplyResult.decode(#"{"version":2,"ok":false,"steps":[],"instruction":{"command":"","filename":"AGENTS.md","scope":"project"}}"#)
        }
    }

    @Test func applySetupDecodesStructuredResultFromNonzeroCLIExit() async throws {
        let runner = StructuredFailureRunner(
            stdout: #"""
            {"version":1,"ok":false,"steps":[{"name":"runtime","ok":false,"error":"start failed"}],"instruction":{"target":"codex","scope":"project","filename":"AGENTS.md","destination":"/tmp/project","command":"jarvis-line instructions print codex --language \"English\"","text":"## Jarvis Line"},"error":"runtime start failed"}
            """#,
            stderr: "runtime process failed"
        )

        let result = try await applySetup(.defaults, using: runner)

        #expect(!result.ok)
        #expect(result.steps.first?.id == "runtime")
        #expect(result.steps.first?.detail == "start failed")
        #expect(result.instruction.text == "## Jarvis Line")
    }

    @Test func bareApplyContractErrorDecodesWithoutStepsOrInstruction() throws {
        let result = try SetupApplyResult.decode(#"{"version":1,"ok":false,"error":"setup plan must be valid JSON"}"#)

        #expect(!result.ok)
        #expect(result.error == "setup plan must be valid JSON")
        #expect(result.steps.isEmpty)
        #expect(result.instruction.command.isEmpty)
        #expect(result.instruction.text.isEmpty)
    }

    @Test func cliAcceptsExactly64KiBOfStdin() async throws {
        let runner = JarvisLineCLI(executable: "/bin/sh")
        let input = Data(repeating: 120, count: SetupPlanPayload.maximumEncodedBytes)

        let output = try await runner.run(["-c", "wc -c"], stdin: input)

        #expect(output.trimmingCharacters(in: .whitespacesAndNewlines) == "65536")
    }

    @Test func cliRejectsOversizedStdinBeforeSpawning() async {
        let marker = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let runner = JarvisLineCLI(executable: "/bin/sh")
        var rejected = false

        do {
            _ = try await runner.run(
                ["-c", "touch \(marker.path)"],
                stdin: Data(repeating: 120, count: SetupPlanPayload.maximumEncodedBytes + 1)
            )
        } catch is SetupContractError {
            rejected = true
        } catch {
            Issue.record("Expected setup payload limit error, received: \(error)")
        }

        #expect(rejected)
        #expect(!FileManager.default.fileExists(atPath: marker.path))
    }

    @Test func cliReportsSpawnFailure() async {
        let runner = JarvisLineCLI(executable: "/definitely/missing/jarvis-line")
        var failed = false

        do {
            _ = try await runner.run(["setup", "inspect", "--json"])
        } catch {
            failed = true
        }

        #expect(failed)
    }

    @Test func cliPreservesStdoutAndStderrFromEarlyNonzeroExit() async {
        let runner = JarvisLineCLI(executable: "/bin/sh")
        var captured: CLIError?

        do {
            _ = try await runner.run(["-c", #"printf '{"ok":false}'; printf 'runtime failed' >&2; exit 7"#])
        } catch let error as CLIError {
            captured = error
        } catch {
            Issue.record("Expected CLIError, received: \(error)")
        }

        #expect(captured?.stdout == #"{"ok":false}"#)
        #expect(captured?.stderr == "runtime failed")
    }

    @Test func cliProcessStateResumesContinuationOnlyOnce() async throws {
        let state = CLIProcessState()
        state.setOutput(Data("first".utf8))

        let output: String = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<String, Error>) in
            state.resume(continuation, terminationStatus: 0)
            state.resume(continuation, terminationStatus: 1)
        }

        #expect(output == "first")
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

private actor StructuredFailureRunner: JarvisLineCommandRunning {
    let stdout: String
    let stderr: String

    init(stdout: String, stderr: String) {
        self.stdout = stdout
        self.stderr = stderr
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        throw CLIError(stdout: stdout, stderr: stderr)
    }
}
