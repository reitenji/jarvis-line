import Testing
@testable import JarvisLine

struct RuntimeDiagnosticsTests {
    @Test func healthPresentationUsesSemanticCopy() {
        #expect(ReliabilityPresentation.healthTitle(.healthy) == "All systems ready")
        #expect(ReliabilityPresentation.healthTitle(.degraded) == "Needs attention")
        #expect(ReliabilityPresentation.healthTitle(.actionRequired) == "Action required")
        #expect(ReliabilityPresentation.healthIcon(.healthy) == "checkmark.circle.fill")
        #expect(ReliabilityPresentation.healthIcon(.degraded) == "exclamationmark.circle.fill")
        #expect(ReliabilityPresentation.healthIcon(.actionRequired) == "exclamationmark.triangle.fill")
    }

    @Test func reliabilityPresentationExplainsSkippedDelivery() {
        let delivery = ReliabilityDelivery(
            messageID: "m1",
            sessionID: "abcdef012345",
            phase: "final",
            state: "skipped",
            backend: nil,
            reason: "quiet_hours",
            receivedAtMS: 1,
            updatedAtMS: 2,
            queueDelayMS: nil,
            durationMS: nil
        )

        #expect(ReliabilityPresentation.deliveryTitle(delivery) == "Final update")
        #expect(ReliabilityPresentation.deliveryDetail(delivery) == "Skipped · Quiet hours")
        #expect(ReliabilityPresentation.deliveryIcon(delivery) == "speaker.slash.fill")
    }

    @Test func reliabilityPresentationFormatsCompletedTiming() {
        let delivery = ReliabilityDelivery(
            messageID: "m1",
            sessionID: "",
            phase: "commentary",
            state: "completed",
            backend: "kokoro",
            reason: nil,
            receivedAtMS: 1,
            updatedAtMS: 2,
            queueDelayMS: 1_850,
            durationMS: 2_400
        )

        #expect(ReliabilityPresentation.deliveryTitle(delivery) == "Progress update")
        #expect(
            ReliabilityPresentation.deliveryDetail(delivery)
                == "Completed · Kokoro · 1.9 s queue · 2.4 s speech"
        )
    }

    @Test func recoveryLabelsMatchControlledActions() {
        #expect(ReliabilityAction.restartRuntime.label == "Restart Runtime")
        #expect(ReliabilityAction.pruneExpired.label == "Remove Expired")
        #expect(ReliabilityAction.testTTS.label == "Test Voice")
        #expect(ReliabilityPresentation.actionIcon(.restartRuntime) == "arrow.clockwise")
        #expect(ReliabilityPresentation.actionIcon(.pruneExpired) == "text.badge.minus")
        #expect(ReliabilityPresentation.actionIcon(.testTTS) == "speaker.wave.2.fill")
    }

    @Test func queueSummarySeparatesActiveAndRejectedWork() {
        let queue = ReliabilityQueue(
            total: 5,
            active: 2,
            expired: 2,
            stale: 1,
            oldestAgeMS: 91_200,
            phaseCounts: ["final": 2],
            maxSize: 8
        )

        #expect(ReliabilityPresentation.queueValue(queue) == "2 active · 3 rejected")
        #expect(ReliabilityPresentation.ageText(queue.oldestAgeMS) == "1m 31s")
    }
}
