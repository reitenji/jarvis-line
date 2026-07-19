import Foundation
import SwiftUI

enum ReliabilityPresentation {
    static func healthTitle(_ health: ReliabilityHealth) -> String {
        switch health {
        case .healthy: "All systems ready"
        case .degraded: "Needs attention"
        case .actionRequired: "Action required"
        }
    }

    static func healthDetail(_ snapshot: ReliabilitySnapshot) -> String {
        guard snapshot.isLoaded else { return "Reliability status has not been checked." }
        switch snapshot.health {
        case .healthy:
            return "The watcher, queue, and selected voice are operating normally."
        case .degraded:
            return "Speech can continue, but recent runtime state should be reviewed."
        case .actionRequired:
            return "Speech needs an explicit recovery action before it can continue reliably."
        }
    }

    static func healthIcon(_ health: ReliabilityHealth) -> String {
        switch health {
        case .healthy: "checkmark.circle.fill"
        case .degraded: "exclamationmark.circle.fill"
        case .actionRequired: "exclamationmark.triangle.fill"
        }
    }

    static func healthColor(_ health: ReliabilityHealth) -> Color {
        switch health {
        case .healthy: JarvisTheme.healthy
        case .degraded: JarvisTheme.goldSoft
        case .actionRequired: JarvisTheme.error
        }
    }

    static func deliveryTitle(_ delivery: ReliabilityDelivery) -> String {
        switch delivery.phase {
        case "final": "Final update"
        case "commentary": "Progress update"
        case "attention": "Attention request"
        default: "Agent update"
        }
    }

    static func deliveryDetail(_ delivery: ReliabilityDelivery) -> String {
        var parts = [stateLabel(delivery.state)]
        if let reason = delivery.reason {
            parts.append(reasonLabel(reason))
        }
        if let backend = delivery.backend {
            parts.append(backendLabel(backend))
        }
        if let delay = delivery.queueDelayMS {
            parts.append("\(durationText(delay)) queue")
        }
        if let duration = delivery.durationMS {
            parts.append("\(durationText(duration)) speech")
        }
        return parts.joined(separator: " · ")
    }

    static func deliveryIcon(_ delivery: ReliabilityDelivery) -> String {
        switch delivery.state {
        case "completed": "checkmark.circle.fill"
        case "failed": "exclamationmark.triangle.fill"
        case "skipped", "cancelled": "speaker.slash.fill"
        case "speaking": "waveform"
        case "queued": "text.line.last.and.arrowtriangle.forward"
        default: "arrow.down.circle"
        }
    }

    static func deliveryColor(_ delivery: ReliabilityDelivery) -> Color {
        switch delivery.state {
        case "completed": JarvisTheme.healthy
        case "failed": JarvisTheme.error
        case "skipped", "cancelled": JarvisTheme.goldSoft
        default: JarvisTheme.cyan
        }
    }

    static func actionIcon(_ action: ReliabilityAction) -> String {
        switch action {
        case .restartRuntime: "arrow.clockwise"
        case .pruneExpired: "text.badge.minus"
        case .testTTS: "speaker.wave.2.fill"
        }
    }

    static func queueValue(_ queue: ReliabilityQueue) -> String {
        let rejected = queue.expired + queue.stale
        if rejected == 0 {
            return queue.active == 1 ? "1 active" : "\(queue.active) active"
        }
        return "\(queue.active) active · \(rejected) rejected"
    }

    static func ageText(_ milliseconds: Int) -> String {
        let seconds = max(0, milliseconds / 1000)
        if seconds < 60 { return "\(seconds)s" }
        return "\(seconds / 60)m \(seconds % 60)s"
    }

    static func backendLabel(_ backend: String) -> String {
        switch backend {
        case "macos": "macOS"
        case "tts": "TTS"
        default: backend.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    static func reasonLabel(_ reason: String) -> String {
        let labels = [
            "backend_error": "Backend error",
            "cancelled": "Cancelled",
            "duplicate": "Duplicate",
            "expired": "Expired",
            "quiet_day": "Quiet day",
            "quiet_hours": "Quiet hours",
            "stale": "Stale",
            "superseded": "Superseded",
            "unknown": "Unknown reason",
        ]
        return labels[reason]
            ?? reason.replacingOccurrences(of: "_", with: " ").capitalized
    }

    static func sessionText(_ delivery: ReliabilityDelivery) -> String {
        guard !delivery.sessionID.isEmpty else { return "Unscoped session" }
        return "Session \(delivery.sessionID.prefix(6))"
    }

    private static func stateLabel(_ state: String) -> String {
        switch state {
        case "completed": "Completed"
        case "failed": "Failed"
        case "skipped": "Skipped"
        case "speaking": "Speaking"
        case "queued": "Queued"
        case "received": "Received"
        case "cancelled": "Cancelled"
        default: state.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private static func durationText(_ milliseconds: Int) -> String {
        if milliseconds >= 1000 {
            return String(format: "%.1f s", Double(milliseconds) / 1000)
        }
        return "\(milliseconds) ms"
    }
}

struct ReliabilityCenterView: View {
    let snapshot: ReliabilitySnapshot
    let resultText: String
    let doctorText: String
    let isBusy: Bool
    let onRefresh: () -> Void
    let onAction: (ReliabilityAction) -> Void

    @State private var confirmRestart = false

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            healthHeader
            currentPath
            recovery
            recentDeliveries
            technicalDetails
        }
        .confirmationDialog(
            "Restart voice runtime?",
            isPresented: $confirmRestart,
            titleVisibility: .visible
        ) {
            Button("Restart Runtime") { onAction(.restartRuntime) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Queued active work is preserved while the watcher and audio worker restart.")
        }
    }

    private var healthHeader: some View {
        let color = snapshot.isLoaded
            ? ReliabilityPresentation.healthColor(snapshot.health)
            : JarvisTheme.mutedText
        return HStack(spacing: 13) {
            Image(systemName: snapshot.isLoaded
                ? ReliabilityPresentation.healthIcon(snapshot.health)
                : "waveform.path.ecg")
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(color)
                .frame(width: 38, height: 38)
                .background(color.opacity(0.12))
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 3) {
                Text(snapshot.isLoaded
                    ? ReliabilityPresentation.healthTitle(snapshot.health)
                    : "Not checked")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text(ReliabilityPresentation.healthDetail(snapshot))
                    .font(.system(size: 11))
                    .foregroundStyle(JarvisTheme.mutedText)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 16)

            Button(action: onRefresh) {
                Image(systemName: "arrow.clockwise")
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.borderless)
            .help("Refresh reliability status")
            .accessibilityLabel("Refresh reliability status")
            .disabled(isBusy)
        }
        .padding(14)
        .background(JarvisTheme.surface.opacity(0.62))
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(color.opacity(0.28), lineWidth: 1)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var currentPath: some View {
        SettingsSection(title: "Current Path") {
            SettingsValueRow(
                title: "Watcher",
                value: snapshot.runtime.watcher.state.capitalized,
                state: processState(snapshot.runtime.watcher.state)
            )
            SettingsValueRow(
                title: "Audio worker",
                value: snapshot.runtime.worker.state.capitalized,
                state: processState(snapshot.runtime.worker.state)
            )
            SettingsValueRow(
                title: "Selected voice",
                value: ReliabilityPresentation.backendLabel(snapshot.tts.backend),
                state: snapshot.tts.ready ? .healthy : .warning
            )
            SettingsValueRow(
                title: "Queue",
                value: ReliabilityPresentation.queueValue(snapshot.queue),
                state: snapshot.queue.expired + snapshot.queue.stale > 0 ? .warning : .healthy
            )
            if let rss = snapshot.runtime.worker.rssMB {
                SettingsValueRow(
                    title: "Worker memory",
                    value: String(format: "%.0f MB", rss)
                )
            }
            if snapshot.queue.total > 0 {
                SettingsValueRow(
                    title: "Oldest queue entry",
                    value: ReliabilityPresentation.ageText(snapshot.queue.oldestAgeMS)
                )
            }
        }
    }

    private var recovery: some View {
        SettingsSection(title: "Recovery") {
            if snapshot.recommendations.isEmpty {
                SettingsRow(
                    title: snapshot.isLoaded ? "No recovery needed" : "Status not checked",
                    detail: snapshot.isLoaded
                        ? "No bounded recovery action is currently recommended."
                        : "Refresh status before running a recovery action."
                ) {
                    Image(systemName: snapshot.isLoaded ? "checkmark.circle.fill" : "minus.circle")
                        .foregroundStyle(snapshot.isLoaded ? JarvisTheme.healthy : JarvisTheme.mutedText)
                }
            } else {
                ForEach(snapshot.recommendations) { recommendation in
                    SettingsRow(title: recommendation.title, detail: recommendation.detail) {
                        if let action = recommendation.executableAction {
                            Button {
                                request(action)
                            } label: {
                                Label(action.label, systemImage: ReliabilityPresentation.actionIcon(action))
                            }
                            .buttonStyle(.bordered)
                            .disabled(isBusy)
                        } else {
                            Image(systemName: "info.circle")
                                .foregroundStyle(JarvisTheme.goldSoft)
                        }
                    }
                }
            }

            if !snapshot.recommendations.contains(where: {
                $0.executableAction == .testTTS
            }) {
                SettingsRow(
                    title: "Voice path",
                    detail: "Selected backend · Fixed local sample"
                ) {
                    Button {
                        onAction(.testTTS)
                    } label: {
                        Label("Test Voice", systemImage: "speaker.wave.2.fill")
                    }
                    .buttonStyle(.bordered)
                    .disabled(isBusy)
                }
            }

            if resultText != "Not checked" {
                Label(resultText, systemImage: "info.circle")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(JarvisTheme.mutedText)
                    .padding(.vertical, 8)
                    .textSelection(.enabled)
            }
        }
    }

    private var recentDeliveries: some View {
        SettingsSection(title: "Recent Deliveries") {
            if snapshot.deliveries.isEmpty {
                Text("No recent delivery activity")
                    .font(.system(size: 11))
                    .foregroundStyle(JarvisTheme.subtleText)
                    .padding(.vertical, 12)
            } else {
                ForEach(Array(snapshot.deliveries.prefix(8))) { delivery in
                    HStack(spacing: 10) {
                        Image(systemName: ReliabilityPresentation.deliveryIcon(delivery))
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(ReliabilityPresentation.deliveryColor(delivery))
                            .frame(width: 18)

                        VStack(alignment: .leading, spacing: 2) {
                            Text(ReliabilityPresentation.deliveryTitle(delivery))
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(JarvisTheme.primaryText)
                            Text(ReliabilityPresentation.deliveryDetail(delivery))
                                .font(.system(size: 10))
                                .foregroundStyle(JarvisTheme.mutedText)
                                .lineLimit(2)
                        }

                        Spacer(minLength: 12)

                        Text(ReliabilityPresentation.sessionText(delivery))
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(JarvisTheme.subtleText)
                            .lineLimit(1)
                    }
                    .padding(.vertical, 8)
                    .overlay(alignment: .bottom) {
                        Rectangle()
                            .fill(JarvisTheme.border.opacity(0.28))
                            .frame(height: 1)
                    }
                }
            }
        }
    }

    private var technicalDetails: some View {
        SettingsSection(title: "Technical Details") {
            DisclosureGroup("Doctor output") {
                Text(doctorText.isEmpty ? "No doctor output available" : doctorText)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(JarvisTheme.mutedText)
                    .textSelection(.enabled)
                    .padding(.top, 8)
            }
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(JarvisTheme.primaryText)
            .padding(.vertical, 11)
        }
    }

    private func processState(_ state: String) -> SettingsStatusState {
        switch state {
        case "running", "idle": .healthy
        case "stopped": .warning
        default: .inactive
        }
    }

    private func request(_ action: ReliabilityAction) {
        if action == .restartRuntime {
            confirmRestart = true
        } else {
            onAction(action)
        }
    }
}
