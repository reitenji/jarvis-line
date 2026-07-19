import Foundation

enum ReliabilityHealth: String, Decodable, Equatable, Sendable {
    case healthy
    case degraded
    case actionRequired = "action_required"
}

enum ReliabilityAction: String, Codable, CaseIterable, Equatable, Sendable {
    case restartRuntime = "restart-runtime"
    case pruneExpired = "prune-expired"
    case testTTS = "test-tts"

    var label: String {
        switch self {
        case .restartRuntime: "Restart Runtime"
        case .pruneExpired: "Remove Expired"
        case .testTTS: "Test Voice"
        }
    }
}

struct ReliabilityProcess: Decodable, Equatable, Sendable {
    let state: String
    let pid: Int?
    let rssMB: Double?

    private enum CodingKeys: String, CodingKey {
        case state
        case pid
        case rssMB = "rss_mb"
    }
}

struct ReliabilityRuntime: Decodable, Equatable, Sendable {
    let speechEnabled: Bool
    let watcher: ReliabilityProcess
    let worker: ReliabilityProcess

    private enum CodingKeys: String, CodingKey {
        case speechEnabled = "speech_enabled"
        case watcher
        case worker
    }
}

struct ReliabilityQueue: Decodable, Equatable, Sendable {
    let total: Int
    let active: Int
    let expired: Int
    let stale: Int
    let oldestAgeMS: Int
    let phaseCounts: [String: Int]
    let maxSize: Int

    private enum CodingKeys: String, CodingKey {
        case total
        case active
        case expired
        case stale
        case oldestAgeMS = "oldest_age_ms"
        case phaseCounts = "phase_counts"
        case maxSize = "max_size"
    }
}

struct ReliabilityTTS: Decodable, Equatable, Sendable {
    let backend: String
    let ready: Bool
    let reason: String
}

struct ReliabilityDelivery: Decodable, Equatable, Identifiable, Sendable {
    let messageID: String
    let sessionID: String
    let phase: String
    let state: String
    let backend: String?
    let reason: String?
    let receivedAtMS: Int
    let updatedAtMS: Int
    let queueDelayMS: Int?
    let durationMS: Int?

    var id: String { messageID }

    private enum CodingKeys: String, CodingKey {
        case messageID = "message_id"
        case sessionID = "session_id"
        case phase
        case state
        case backend
        case reason
        case receivedAtMS = "received_ts_ms"
        case updatedAtMS = "updated_ts_ms"
        case queueDelayMS = "queue_delay_ms"
        case durationMS = "duration_ms"
    }
}

struct ReliabilityRecommendation: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let severity: String
    let title: String
    let detail: String
    let actionID: String?

    var executableAction: ReliabilityAction? {
        actionID.flatMap(ReliabilityAction.init(rawValue:))
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case severity
        case title
        case detail
        case actionID = "action"
    }
}

struct ReliabilitySnapshot: Decodable, Equatable, Sendable {
    static let supportedVersion = 1

    let version: Int
    let generatedAtMS: Int
    let health: ReliabilityHealth
    let runtime: ReliabilityRuntime
    let queue: ReliabilityQueue
    let tts: ReliabilityTTS
    let deliveries: [ReliabilityDelivery]
    let recommendations: [ReliabilityRecommendation]

    static let empty = ReliabilitySnapshot(
        version: supportedVersion,
        generatedAtMS: 0,
        health: .degraded,
        runtime: ReliabilityRuntime(
            speechEnabled: true,
            watcher: ReliabilityProcess(state: "unknown", pid: nil, rssMB: nil),
            worker: ReliabilityProcess(state: "unknown", pid: nil, rssMB: nil)
        ),
        queue: ReliabilityQueue(
            total: 0,
            active: 0,
            expired: 0,
            stale: 0,
            oldestAgeMS: 0,
            phaseCounts: [:],
            maxSize: 0
        ),
        tts: ReliabilityTTS(backend: "unknown", ready: false, reason: "not_checked"),
        deliveries: [],
        recommendations: []
    )

    var isLoaded: Bool { generatedAtMS > 0 }

    static func decode(_ json: String) throws -> ReliabilitySnapshot {
        let value = try JSONDecoder().decode(Self.self, from: Data(json.utf8))
        guard value.version == supportedVersion else {
            throw ReliabilityContractError.unsupportedVersion(value.version)
        }
        return value
    }

    private enum CodingKeys: String, CodingKey {
        case version
        case generatedAtMS = "generated_at_ms"
        case health
        case runtime
        case queue
        case tts
        case deliveries
        case recommendations
    }
}

struct ReliabilityRecoveryResult: Decodable, Equatable, Sendable {
    let version: Int
    let ok: Bool
    let action: ReliabilityAction
    let changed: Bool
    let summary: String
    let snapshot: ReliabilitySnapshot

    static func decode(_ json: String) throws -> ReliabilityRecoveryResult {
        let value = try JSONDecoder().decode(Self.self, from: Data(json.utf8))
        guard value.version == ReliabilitySnapshot.supportedVersion else {
            throw ReliabilityContractError.unsupportedVersion(value.version)
        }
        guard value.snapshot.version == ReliabilitySnapshot.supportedVersion else {
            throw ReliabilityContractError.unsupportedVersion(value.snapshot.version)
        }
        return value
    }
}

enum ReliabilityContractError: LocalizedError {
    case unsupportedVersion(Int)

    var errorDescription: String? {
        switch self {
        case .unsupportedVersion(let version):
            "Unsupported reliability contract version: \(version)."
        }
    }
}
