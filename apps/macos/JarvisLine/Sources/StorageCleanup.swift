import Foundation

struct StorageCleanupStatus: Decodable, Equatable {
    let mode: String
    let eligibleFiles: Int
    let eligibleBytes: Int
    let removedFiles: Int
    let removedBytes: Int
    let skippedFiles: Int
    let errorCount: Int
    let alreadyRunning: Bool
    let lastSuccessAt: Int?

    static let empty = StorageCleanupStatus(
        mode: "status",
        eligibleFiles: 0,
        eligibleBytes: 0,
        removedFiles: 0,
        removedBytes: 0,
        skippedFiles: 0,
        errorCount: 0,
        alreadyRunning: false,
        lastSuccessAt: nil
    )

    var reclaimableText: String {
        Self.byteText(eligibleBytes)
    }

    var recoveredText: String {
        Self.byteText(removedBytes)
    }

    var lastSuccessText: String {
        guard let lastSuccessAt else { return "Never" }
        return Date(timeIntervalSince1970: TimeInterval(lastSuccessAt))
            .formatted(date: .abbreviated, time: .shortened)
    }

    static func decode(_ json: String) throws -> StorageCleanupStatus {
        try JSONDecoder().decode(Self.self, from: Data(json.utf8))
    }

    private enum CodingKeys: String, CodingKey {
        case mode
        case eligibleFiles = "eligible_files"
        case eligibleBytes = "eligible_bytes"
        case removedFiles = "removed_files"
        case removedBytes = "removed_bytes"
        case skippedFiles = "skipped_files"
        case errorCount = "error_count"
        case errors
        case alreadyRunning = "already_running"
        case lastSuccessAt = "last_success_at"
        case categories
    }

    init(
        mode: String,
        eligibleFiles: Int,
        eligibleBytes: Int,
        removedFiles: Int,
        removedBytes: Int,
        skippedFiles: Int,
        errorCount: Int,
        alreadyRunning: Bool,
        lastSuccessAt: Int?
    ) {
        self.mode = mode
        self.eligibleFiles = eligibleFiles
        self.eligibleBytes = eligibleBytes
        self.removedFiles = removedFiles
        self.removedBytes = removedBytes
        self.skippedFiles = skippedFiles
        self.errorCount = errorCount
        self.alreadyRunning = alreadyRunning
        self.lastSuccessAt = lastSuccessAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        mode = try container.decode(String.self, forKey: .mode)
        eligibleFiles = try container.decode(Int.self, forKey: .eligibleFiles)
        eligibleBytes = try container.decode(Int.self, forKey: .eligibleBytes)
        removedFiles = try container.decode(Int.self, forKey: .removedFiles)
        removedBytes = try container.decode(Int.self, forKey: .removedBytes)
        skippedFiles = try container.decode(Int.self, forKey: .skippedFiles)
        errorCount = try container.decode(Int.self, forKey: .errorCount)
        alreadyRunning = try container.decode(Bool.self, forKey: .alreadyRunning)
        lastSuccessAt = try container.decodeIfPresent(Int.self, forKey: .lastSuccessAt)

        _ = try container.decode([DiscardedJSON].self, forKey: .errors)
        _ = try container.decode([String: DiscardedJSON].self, forKey: .categories)

        let counters = [
            eligibleFiles,
            eligibleBytes,
            removedFiles,
            removedBytes,
            skippedFiles,
            errorCount,
        ]
        guard ["status", "run"].contains(mode), counters.allSatisfy({ $0 >= 0 }) else {
            throw DecodingError.dataCorrupted(
                .init(
                    codingPath: container.codingPath,
                    debugDescription: "Invalid cleanup status values"
                )
            )
        }
    }

    private static func byteText(_ value: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(value), countStyle: .file)
    }
}

private struct DiscardedJSON: Decodable {
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil()
            || (try? container.decode(Bool.self)) != nil
            || (try? container.decode(Int.self)) != nil
            || (try? container.decode(Double.self)) != nil
            || (try? container.decode(String.self)) != nil
            || (try? container.decode([DiscardedJSON].self)) != nil
            || (try? container.decode([String: DiscardedJSON].self)) != nil {
            return
        }
        throw DecodingError.dataCorruptedError(
            in: container,
            debugDescription: "Unsupported JSON value"
        )
    }
}
