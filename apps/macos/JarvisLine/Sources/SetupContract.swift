import Foundation

struct SetupInspection: Decodable, Sendable {
    let version: Int
    let configExists: Bool
    let platform: String
    let languages: [String]
    let backendOptions: [SetupBackendOption]
    let current: SetupCurrentValues

    private enum CodingKeys: String, CodingKey {
        case version
        case configExists
        case platform
        case languages
        case backendOptions
        case current
        case environment
        case language
        case uiOptions
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let environment = try container.decodeIfPresent(SetupEnvironment.self, forKey: .environment)
        let selectedLanguage = try container.decodeIfPresent(String.self, forKey: .language)
        let uiOptions = try container.decodeIfPresent(SetupUIOptions.self, forKey: .uiOptions)

        version = try container.decode(Int.self, forKey: .version)
        configExists = try container.decodeIfPresent(Bool.self, forKey: .configExists)
            ?? environment?.configExists
            ?? false
        platform = try container.decodeIfPresent(String.self, forKey: .platform)
            ?? environment?.platform
            ?? ""
        languages = try container.decodeIfPresent([String].self, forKey: .languages)
            ?? uiOptions?.lineLanguage
            ?? selectedLanguage.map { [$0] }
            ?? []
        backendOptions = try container.decodeIfPresent([SetupBackendOption].self, forKey: .backendOptions) ?? []

        var current = try container.decodeIfPresent(SetupCurrentValues.self, forKey: .current) ?? .defaults
        if current.language.isEmpty {
            current.language = selectedLanguage ?? "English"
        }
        self.current = current
    }

    static func decode(_ text: String) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value = try decoder.decode(Self.self, from: Data(text.utf8))
        guard value.version == 1 else {
            throw SetupContractError.unsupportedVersion(value.version)
        }
        return value
    }
}

struct SetupBackendOption: Decodable, Identifiable, Sendable {
    let id: String
    let label: String
    let available: Bool
    let ready: Bool
    let recommended: Bool
    let requiresInstall: Bool
    let detail: String
}

struct SetupCurrentValues: Decodable, Sendable {
    var language: String
    let tts: String
    let speakMode: String

    static let defaults = SetupCurrentValues(language: "", tts: "system", speakMode: "final_only")

    private enum CodingKeys: String, CodingKey {
        case language
        case lineLanguage
        case tts
        case speakMode
    }

    init(language: String, tts: String, speakMode: String) {
        self.language = language
        self.tts = tts
        self.speakMode = speakMode
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        language = try container.decodeIfPresent(String.self, forKey: .language)
            ?? container.decodeIfPresent(String.self, forKey: .lineLanguage)
            ?? ""
        tts = try container.decodeIfPresent(String.self, forKey: .tts) ?? "system"
        speakMode = try container.decodeIfPresent(String.self, forKey: .speakMode) ?? "final_only"
    }
}

struct SetupPlanPayload: Codable, Equatable, Sendable {
    static let maximumEncodedBytes = 65_536

    var version = 1
    var language: String
    var tts: String
    var speakMode: String
    var agentTarget: String
    var instructionScope: String
    var installKokoro: Bool
    var installCodexHook: Bool
    var startRuntime: Bool
    var testVoice: Bool
    var projectPath: String?
    var command: String?

    init(
        version: Int = 1,
        language: String,
        tts: String,
        speakMode: String,
        agentTarget: String,
        instructionScope: String,
        installKokoro: Bool,
        installCodexHook: Bool,
        startRuntime: Bool,
        testVoice: Bool,
        projectPath: String?,
        command: String?
    ) {
        self.version = version
        self.language = language
        self.tts = tts
        self.speakMode = speakMode
        self.agentTarget = agentTarget
        self.instructionScope = instructionScope
        self.installKokoro = installKokoro
        self.installCodexHook = installCodexHook
        self.startRuntime = startRuntime
        self.testVoice = testVoice
        self.projectPath = projectPath
        self.command = command
    }

    static let defaults = SetupPlanPayload(
        language: "English",
        tts: "system",
        speakMode: "final_only",
        agentTarget: "codex",
        instructionScope: "project",
        installKokoro: false,
        installCodexHook: true,
        startRuntime: true,
        testVoice: false,
        projectPath: nil,
        command: nil
    )

    init(inspection: SetupInspection) {
        let available = inspection.backendOptions.filter(\.available)
        let currentBackend = available.first(where: { $0.id == inspection.current.tts })
        let selected = currentBackend ?? available.first(where: \.recommended) ?? available.first

        self = .defaults
        language = inspection.current.language
        tts = selected?.id ?? "system"
        speakMode = inspection.current.speakMode
        installKokoro = selected?.requiresInstall == true
    }

    func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(self)
        guard data.count <= Self.maximumEncodedBytes else {
            throw SetupContractError.payloadTooLarge(data.count)
        }
        return data
    }
}

struct SetupInstructionResult: Decodable, Sendable {
    let command: String
    let filename: String
    let scope: String
    let text: String

    private enum CodingKeys: String, CodingKey {
        case command
        case filename
        case scope
        case text
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        command = try container.decodeIfPresent(String.self, forKey: .command) ?? ""
        filename = try container.decodeIfPresent(String.self, forKey: .filename) ?? ""
        scope = try container.decodeIfPresent(String.self, forKey: .scope) ?? ""
        text = try container.decodeIfPresent(String.self, forKey: .text) ?? ""
    }
}

struct SetupResultStep: Decodable, Sendable {
    let id: String
    let ok: Bool
    let detail: String

    private enum CodingKeys: String, CodingKey {
        case id
        case name
        case ok
        case detail
        case error
        case status
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decodeIfPresent(String.self, forKey: .name)
            ?? "setup"
        ok = try container.decode(Bool.self, forKey: .ok)
        detail = try container.decodeIfPresent(String.self, forKey: .detail)
            ?? container.decodeIfPresent(String.self, forKey: .error)
            ?? container.decodeIfPresent(String.self, forKey: .status)
            ?? ""
    }
}

struct SetupApplyResult: Decodable, Sendable {
    let version: Int
    let ok: Bool
    let steps: [SetupResultStep]
    let instruction: SetupInstructionResult
    let error: String?

    static func decode(_ text: String) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value = try decoder.decode(Self.self, from: Data(text.utf8))
        guard value.version == 1 else {
            throw SetupContractError.unsupportedVersion(value.version)
        }
        return value
    }
}

enum SetupContractError: LocalizedError, Sendable {
    case unsupportedVersion(Int)
    case payloadTooLarge(Int)

    var errorDescription: String? {
        switch self {
        case .unsupportedVersion(let version):
            return "Unsupported setup contract version: \(version)"
        case .payloadTooLarge(let count):
            return "Setup plan exceeds the 64 KiB stdin limit (\(count) bytes)."
        }
    }
}

enum SetupFirstRunPolicy {
    static func shouldOffer(configExists: Bool, wasOffered: Bool) -> Bool {
        !configExists && !wasOffered
    }
}

func inspectSetup(
    using runner: any JarvisLineCommandRunning = JarvisLineCLI()
) async throws -> SetupInspection {
    try SetupInspection.decode(await runner.run(["setup", "inspect", "--json"]))
}

func applySetup(
    _ plan: SetupPlanPayload,
    using runner: any JarvisLineCommandRunning = JarvisLineCLI()
) async throws -> SetupApplyResult {
    let output = try await runner.run(
        ["setup", "apply", "--stdin", "--json"],
        stdin: try plan.encoded()
    )
    return try SetupApplyResult.decode(output)
}

private struct SetupEnvironment: Decodable {
    let platform: String
    let configExists: Bool
}

private struct SetupUIOptions: Decodable {
    let lineLanguage: [String]?
}
