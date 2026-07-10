import Foundation
import SwiftUI

struct RuntimeTraceEvent: Codable, Identifiable {
    let timestampMS: Int
    let event: String
    let messageID: String?
    let sessionID: String?
    let phase: String?
    let queueDelayMS: Int?
    let durationMS: Int?
    let rssMB: Double?
    let limitMB: Double?
    let backend: String?
    let reason: String?

    var id: String {
        "\(timestampMS)-\(event)-\(messageID ?? sessionID ?? "runtime")"
    }

    var spokenText: String? { nil }

    var timeText: String {
        let date = Date(timeIntervalSince1970: TimeInterval(timestampMS) / 1000)
        return Self.timeFormatter.string(from: date)
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()

    enum CodingKeys: String, CodingKey {
        case timestampMS = "ts_ms"
        case event
        case messageID = "message_id"
        case sessionID = "session_id"
        case phase
        case queueDelayMS = "queue_delay_ms"
        case durationMS = "duration_ms"
        case rssMB = "rss_mb"
        case limitMB = "limit_mb"
        case backend
        case reason
    }
}

struct RuntimeDiagnosticsSummary {
    let events: [RuntimeTraceEvent]

    var latest: RuntimeTraceEvent? { events.last }

    var headline: String {
        switch latest?.event {
        case "worker_rss_exit": return "Worker released memory"
        case "worker_idle_exit": return "Worker is idle"
        case "failed": return "Speech failed"
        case "completed": return "Speech completed"
        case "speaking": return "Speech in progress"
        case "queued": return "Waiting in queue"
        case "received": return "Agent event received"
        case "skipped": return "Playback skipped"
        case "worker_started": return "Worker started"
        default: return "Runtime ready"
        }
    }

    var detail: String {
        guard let latest else { return "No lifecycle events recorded yet" }
        if latest.event == "worker_rss_exit", let rss = latest.rssMB, let limit = latest.limitMB {
            return "\(wholeNumber(rss)) MB used · \(wholeNumber(limit)) MB limit"
        }
        if latest.event == "failed" {
            return latest.reason.map { "Reason: \($0)" } ?? "The selected TTS backend returned an error"
        }
        if latest.event == "completed", let duration = latest.durationMS {
            return "Completed in \(durationText(duration))"
        }
        if latest.event == "speaking" {
            return latest.backend.map { "Using \($0)" } ?? "The audio worker is active"
        }
        if latest.event == "skipped" {
            return latest.reason?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Runtime policy skipped playback"
        }
        return latest.phase?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Lifecycle metadata is current"
    }

    var queueDelayText: String? {
        guard let delay = events.reversed().compactMap(\.queueDelayMS).first else {
            return nil
        }
        if delay >= 1000 {
            return String(format: "%.1f s", Double(delay) / 1000)
        }
        return "\(delay) ms"
    }

    private func durationText(_ milliseconds: Int) -> String {
        if milliseconds >= 1000 {
            return String(format: "%.1f s", Double(milliseconds) / 1000)
        }
        return "\(milliseconds) ms"
    }

    private func wholeNumber(_ value: Double) -> String {
        String(format: "%.0f", value)
    }
}

struct RuntimeDiagnosticsView: View {
    let events: [RuntimeTraceEvent]
    let doctorText: String
    let errorMessage: String?

    private var summary: RuntimeDiagnosticsSummary {
        RuntimeDiagnosticsSummary(events: events)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(JarvisTheme.error)
                    .textSelection(.enabled)
            } else {
                summaryHeader
                Divider().overlay(JarvisTheme.cyan.opacity(0.15))
                eventList
                if !doctorText.isEmpty {
                    DisclosureGroup("Doctor details") {
                        Text(doctorText)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(JarvisTheme.mutedText)
                            .textSelection(.enabled)
                            .padding(.top, 6)
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(JarvisTheme.subtleText)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var summaryHeader: some View {
        HStack(spacing: 10) {
            Image(systemName: icon(for: summary.latest?.event))
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(color(for: summary.latest?.event))
                .frame(width: 26, height: 26)
                .background(color(for: summary.latest?.event).opacity(0.12))
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 2) {
                Text(summary.headline)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text(summary.detail)
                    .font(.system(size: 11))
                    .foregroundStyle(JarvisTheme.mutedText)
            }

            Spacer(minLength: 12)

            if let delay = summary.queueDelayText {
                VStack(alignment: .trailing, spacing: 1) {
                    Text(delay)
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundStyle(JarvisTheme.goldSoft)
                    Text("queue delay")
                        .font(.system(size: 9))
                        .foregroundStyle(JarvisTheme.subtleText)
                }
            }
        }
    }

    @ViewBuilder
    private var eventList: some View {
        if events.isEmpty {
            Text("Lifecycle events will appear after the next queued line.")
                .font(.system(size: 11))
                .foregroundStyle(JarvisTheme.subtleText)
        } else {
            VStack(spacing: 0) {
                ForEach(Array(events.suffix(6).reversed())) { event in
                    HStack(spacing: 8) {
                        Image(systemName: icon(for: event.event))
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(color(for: event.event))
                            .frame(width: 16)
                        Text(label(for: event.event))
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(JarvisTheme.primaryText)
                        if let phase = event.phase {
                            Text(phase.replacingOccurrences(of: "_", with: " "))
                                .font(.system(size: 10))
                                .foregroundStyle(JarvisTheme.subtleText)
                        }
                        Spacer()
                        Text(event.timeText)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(JarvisTheme.subtleText)
                    }
                    .padding(.vertical, 5)
                    if event.id != events.suffix(6).first?.id {
                        Divider().overlay(JarvisTheme.cyan.opacity(0.08))
                    }
                }
            }
        }
    }

    private func label(for event: String) -> String {
        switch event {
        case "worker_rss_exit": return "Memory released"
        case "worker_idle_exit": return "Worker idle"
        case "worker_started": return "Worker started"
        case "received": return "Event received"
        case "queued": return "Queued"
        case "speaking": return "Speaking"
        case "completed": return "Completed"
        case "failed": return "Failed"
        case "skipped": return "Skipped"
        default: return event.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private func icon(for event: String?) -> String {
        switch event {
        case "worker_rss_exit": return "memorychip"
        case "worker_idle_exit": return "moon.zzz"
        case "worker_started": return "bolt.fill"
        case "received": return "arrow.down.circle"
        case "queued": return "text.line.last.and.arrowtriangle.forward"
        case "speaking": return "waveform"
        case "completed": return "checkmark.circle.fill"
        case "failed": return "exclamationmark.triangle.fill"
        case "skipped": return "speaker.slash.fill"
        default: return "stethoscope"
        }
    }

    private func color(for event: String?) -> Color {
        switch event {
        case "failed": return JarvisTheme.error
        case "worker_rss_exit", "skipped": return JarvisTheme.goldSoft
        case "completed": return JarvisTheme.cyan
        default: return JarvisTheme.cyan
        }
    }
}
