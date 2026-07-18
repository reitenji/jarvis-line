import Foundation
import Testing
@testable import JarvisLine

struct StorageCleanupTests {
    @Test func decodesCleanupJSONAndFormatsStorage() throws {
        let status = try StorageCleanupStatus.decode(Self.statusJSON)

        #expect(status.mode == "status")
        #expect(status.eligibleFiles == 4)
        #expect(status.eligibleBytes == 50_331_648)
        #expect(status.removedFiles == 0)
        #expect(status.removedBytes == 0)
        #expect(status.skippedFiles == 1)
        #expect(status.errorCount == 0)
        #expect(!status.alreadyRunning)
        #expect(
            status.reclaimableText
                == ByteCountFormatter.string(fromByteCount: 50_331_648, countStyle: .file)
        )
        #expect(status.lastSuccessText == "Never")
    }

    @Test func decoderRequiresTheStableTopLevelContract() {
        let missingMode = Self.statusJSON.replacingOccurrences(
            of: #""mode":"status","#,
            with: ""
        )

        #expect(throws: DecodingError.self) {
            try StorageCleanupStatus.decode(missingMode)
        }
    }

    @Test func decoderToleratesCategoryDetailsWithoutExposingThem() throws {
        let json = Self.statusJSON.replacingOccurrences(
            of: #""categories":{}"#,
            with: #""categories":{"generated_audio":{"eligible_files":4,"eligible_bytes":50331648,"removed_files":0,"removed_bytes":0,"skipped_files":1,"error_count":0,"path":"/Users/private/audio"}}"#
        )

        let status = try StorageCleanupStatus.decode(json)

        #expect(status == StorageCleanupStatus(
            mode: "status",
            eligibleFiles: 4,
            eligibleBytes: 50_331_648,
            removedFiles: 0,
            removedBytes: 0,
            skippedFiles: 1,
            errorCount: 0,
            alreadyRunning: false,
            lastSuccessAt: nil
        ))
        #expect(!String(describing: status).contains("/Users/private/audio"))
    }

    private static let statusJSON = #"""
    {
      "mode":"status",
      "eligible_files":4,
      "eligible_bytes":50331648,
      "removed_files":0,
      "removed_bytes":0,
      "skipped_files":1,
      "error_count":0,
      "errors":[],
      "already_running":false,
      "last_success_at":null,
      "categories":{}
    }
    """#
}
