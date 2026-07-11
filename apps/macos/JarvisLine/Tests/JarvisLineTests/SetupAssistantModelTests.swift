import Foundation
import Testing
@testable import JarvisLine

@MainActor
struct SetupAssistantModelTests {
    @Test func loadAndLanguageReinspectionKeepAvailableCurrentBackend() async throws {
        let runner = AssistantFakeRunner(
            inspections: [
                Self.englishInspection(currentTTS: "system"),
                Self.turkishInspection(currentTTS: "system"),
            ],
            applyOutput: Self.successResult
        )
        let model = SetupAssistantModel(runner: runner)

        await model.load()
        model.selectLanguage("Turkish")
        await model.continueFromLanguage()

        #expect(model.step == .voice)
        #expect(model.plan.language == "Turkish")
        #expect(model.plan.tts == "system")
        let calls = await runner.calls
        #expect(calls.map(\.args) == [
            ["setup", "inspect", "--json"],
            ["setup", "inspect", "--json", "--language", "Turkish"],
        ])
    }

    @Test func languageReinspectionFallsBackToRecommendedAvailableBackend() async throws {
        let runner = AssistantFakeRunner(
            inspections: [
                Self.englishInspection(currentTTS: "kokoro"),
                Self.turkishInspection(currentTTS: "kokoro"),
            ],
            applyOutput: Self.successResult
        )
        let model = SetupAssistantModel(runner: runner)

        await model.load()
        model.selectLanguage("Turkish")
        await model.continueFromLanguage()

        #expect(model.plan.tts == "system")
    }

    @Test func unavailableBackendAndUnacceptedKokoroInstallBlockContinue() async throws {
        let runner = AssistantFakeRunner(
            inspections: [Self.englishInspection(currentTTS: "system", kokoroReady: false)],
            applyOutput: Self.successResult
        )
        let model = SetupAssistantModel(runner: runner)

        await model.load()
        model.step = .voice
        model.selectBackend("missing")
        #expect(model.plan.tts == "system")

        model.selectBackend("kokoro")
        #expect(!model.canContinue)
        model.installKokoroAccepted = true
        #expect(model.canContinue)
        model.cancel()

        let applyCallCount = await runner.applyCallCount
        #expect(applyCallCount == 0)
    }

    @Test func projectScopeRequiresSelectedDirectory() async {
        let model = SetupAssistantModel(runner: AssistantFakeRunner(inspections: [], applyOutput: Self.successResult))
        model.step = .agent
        model.plan.instructionScope = "project"
        model.plan.projectPath = nil

        #expect(!model.canContinue)
        model.selectProjectDirectory(URL(fileURLWithPath: "/tmp/project", isDirectory: true))
        #expect(model.canContinue)
    }

    @Test func applySubmitsReviewedSnakeCasePlanAndCompletesOnce() async throws {
        let runner = AssistantFakeRunner(
            inspections: [Self.englishInspection(currentTTS: "system")],
            applyOutput: Self.successResult
        )
        var completionCount = 0
        let model = SetupAssistantModel(runner: runner) {
            completionCount += 1
        }

        await model.load()
        model.step = .review
        model.plan.projectPath = "/tmp/project"
        await model.apply()
        await model.apply()

        let lastApplyPayload = await runner.lastApplyPayload
        let payload = try #require(lastApplyPayload)
        let json = try #require(JSONSerialization.jsonObject(with: payload) as? [String: Any])
        #expect(model.step == .complete)
        #expect(model.result?.ok == true)
        #expect(json["agent_target"] as? String == "codex")
        #expect(json["instruction_scope"] as? String == "project")
        #expect(json["instruction_path"] == nil)
        let applyCallCount = await runner.applyCallCount
        #expect(applyCallCount == 1)
        #expect(completionCount == 1)
    }

    @Test func failedBareApplyReturnsToReviewWithReadableError() async {
        let runner = AssistantFakeRunner(
            inspections: [Self.englishInspection(currentTTS: "system")],
            applyOutput: #"{"version":1,"ok":false,"error":"setup plan must be valid JSON"}"#
        )
        let model = SetupAssistantModel(runner: runner)

        await model.load()
        model.step = .review
        model.plan.projectPath = "/tmp/project"
        await model.apply()

        #expect(model.step == .review)
        #expect(model.errorMessage == "setup plan must be valid JSON")
        #expect(model.result?.instruction == nil)
        #expect(!model.canCopyInstructions)
    }

    @Test func firstRunOfferPolicyUsesAuthoritativeConfigAndStoredPreference() {
        #expect(SetupAssistantFirstRunController.shouldOffer(configExists: false, wasOffered: false))
        #expect(!SetupAssistantFirstRunController.shouldOffer(configExists: true, wasOffered: false))
        #expect(!SetupAssistantFirstRunController.shouldOffer(configExists: false, wasOffered: true))
    }

    private static func englishInspection(currentTTS: String, kokoroReady: Bool = true) -> String {
        #"""
        {"version":1,"environment":{"platform":"Darwin","config_exists":false},"current":{"tts":"\#(currentTTS)","line_language":"English","speak_mode":"final_only"},"language":"English","ui_options":{"line_language":["English","Turkish"]},"backend_options":[{"id":"kokoro","label":"Kokoro local","available":true,"ready":\#(kokoroReady),"recommended":true,"requires_install":\#(!kokoroReady),"detail":"\#(kokoroReady ? "ready" : "assets missing")"},{"id":"system","label":"System voice","available":true,"ready":true,"recommended":false,"requires_install":false,"detail":"say"}]}
        """#
    }

    private static func turkishInspection(currentTTS: String) -> String {
        #"""
        {"version":1,"environment":{"platform":"Darwin","config_exists":false},"current":{"tts":"\#(currentTTS)","line_language":"Turkish","speak_mode":"final_only"},"language":"Turkish","ui_options":{"line_language":["English","Turkish"]},"backend_options":[{"id":"kokoro","label":"Kokoro local","available":false,"ready":true,"recommended":false,"requires_install":false,"detail":"Use a matching custom model for non-English speech."},{"id":"system","label":"System voice","available":true,"ready":true,"recommended":true,"requires_install":false,"detail":"say"}]}
        """#
    }

    private static let successResult = #"""
    {"version":1,"ok":true,"steps":[{"name":"config_write","ok":true}],"instruction":{"target":"codex","scope":"project","filename":"AGENTS.md","destination":"/tmp/project","command":"jarvis-line instructions print codex --language \"English\"","text":"## Jarvis Line"}}
    """#
}

private actor AssistantFakeRunner: JarvisLineCommandRunning {
    struct Call: Sendable {
        let args: [String]
        let stdin: Data?
    }

    private var inspections: [String]
    private let applyOutput: String
    private(set) var calls: [Call] = []

    init(inspections: [String], applyOutput: String) {
        self.inspections = inspections
        self.applyOutput = applyOutput
    }

    var applyCallCount: Int {
        calls.filter { $0.args.contains("apply") }.count
    }

    var lastApplyPayload: Data? {
        calls.last { $0.args.contains("apply") }?.stdin
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append(Call(args: args, stdin: stdin))
        if args.contains("inspect") {
            guard !inspections.isEmpty else {
                throw CLIError("unexpected setup inspection")
            }
            return inspections.removeFirst()
        }
        return applyOutput
    }
}
