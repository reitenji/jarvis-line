import Foundation
import Testing
@testable import JarvisLine

struct ReliabilityContractTests {
    @Test func snapshotDecodesVersionOne() throws {
        let snapshot = try ReliabilitySnapshot.decode(snapshotJSON())

        #expect(snapshot.version == 1)
        #expect(snapshot.health == .degraded)
        #expect(snapshot.runtime.watcher.state == "running")
        #expect(snapshot.runtime.worker.rssMB == 84.5)
        #expect(snapshot.queue.active == 1)
        #expect(snapshot.queue.phaseCounts == ["final": 1])
        #expect(snapshot.tts.backend == "system")
        #expect(snapshot.deliveries.first?.state == "failed")
        #expect(snapshot.recommendations.first?.executableAction == .testTTS)
    }

    @Test func snapshotRejectsUnsupportedVersion() {
        #expect(throws: ReliabilityContractError.self) {
            try ReliabilitySnapshot.decode(snapshotJSON(version: 2))
        }
    }

    @Test func snapshotDoesNotExposeUnknownRecoveryAction() throws {
        let snapshot = try ReliabilitySnapshot.decode(
            snapshotJSON(action: "clear-everything")
        )

        #expect(snapshot.recommendations.first?.actionID == "clear-everything")
        #expect(snapshot.recommendations.first?.executableAction == nil)
    }

    @Test func recoveryResultDecodesControlledAction() throws {
        let result = try ReliabilityRecoveryResult.decode(
            """
            {
              "version": 1,
              "ok": true,
              "action": "prune-expired",
              "changed": true,
              "summary": "Removed 1 expired or stale queue entry.",
              "snapshot": \(snapshotJSON())
            }
            """
        )

        #expect(result.action == .pruneExpired)
        #expect(result.changed)
        #expect(result.snapshot.health == .degraded)
    }

    @Test func snapshotRejectsMalformedJSON() {
        #expect(throws: DecodingError.self) {
            try ReliabilitySnapshot.decode(#"{"version":1}"#)
        }
    }
}

private func snapshotJSON(
    version: Int = 1,
    action: String = "test-tts"
) -> String {
    """
    {
      "version": \(version),
      "generated_at_ms": 200000,
      "health": "degraded",
      "runtime": {
        "speech_enabled": true,
        "watcher": {"state": "running", "pid": 11},
        "worker": {"state": "running", "pid": 12, "rss_mb": 84.5}
      },
      "queue": {
        "total": 1,
        "active": 1,
        "expired": 0,
        "stale": 0,
        "oldest_age_ms": 100,
        "phase_counts": {"final": 1},
        "max_size": 8
      },
      "tts": {"backend": "system", "ready": true, "reason": "ready"},
      "deliveries": [
        {
          "message_id": "abcdef012345",
          "session_id": "123456abcdef",
          "phase": "final",
          "state": "failed",
          "received_ts_ms": 100,
          "updated_ts_ms": 140,
          "reason": "backend_error"
        }
      ],
      "recommendations": [
        {
          "id": "recent-speech-failure",
          "severity": "degraded",
          "title": "Test the selected voice",
          "detail": "The most recent delivery failed.",
          "action": "\(action)"
        }
      ]
    }
    """
}
