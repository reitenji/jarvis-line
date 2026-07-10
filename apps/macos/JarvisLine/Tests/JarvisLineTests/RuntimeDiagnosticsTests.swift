import Foundation
import Testing
@testable import JarvisLine

struct RuntimeDiagnosticsTests {
    @Test func traceEventsDecodeWithoutPrivateContent() throws {
        let data = #"""
        [
          {
            "ts_ms": 1000,
            "event": "completed",
            "message_id": "abc",
            "session_id": "123456789abc",
            "phase": "final",
            "duration_ms": 2400
          }
        ]
        """#.data(using: .utf8)!

        let events = try JSONDecoder().decode([RuntimeTraceEvent].self, from: data)

        #expect(events.first?.event == "completed")
        #expect(events.first?.messageID == "abc")
        #expect(events.first?.spokenText == nil)
    }

    @Test func diagnosticsSummaryHighlightsMemoryExit() {
        let event = RuntimeTraceEvent(
            timestampMS: 1000,
            event: "worker_rss_exit",
            messageID: nil,
            sessionID: nil,
            phase: nil,
            queueDelayMS: nil,
            durationMS: nil,
            rssMB: 700,
            limitMB: 512,
            backend: nil,
            reason: nil
        )

        let summary = RuntimeDiagnosticsSummary(events: [event])

        #expect(summary.headline == "Worker released memory")
        #expect(summary.detail == "700 MB used · 512 MB limit")
    }

    @Test func diagnosticsSummaryReportsLatestQueueDelay() {
        let event = RuntimeTraceEvent(
            timestampMS: 1000,
            event: "speaking",
            messageID: "abc",
            sessionID: "123456789abc",
            phase: "commentary",
            queueDelayMS: 1800,
            durationMS: nil,
            rssMB: nil,
            limitMB: nil,
            backend: "kokoro",
            reason: nil
        )

        let summary = RuntimeDiagnosticsSummary(events: [event])

        #expect(summary.headline == "Speech in progress")
        #expect(summary.queueDelayText == "1.8 s")
    }
}
