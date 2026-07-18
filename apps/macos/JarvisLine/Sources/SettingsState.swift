enum SettingsDestination: String, CaseIterable, Identifiable {
    case general
    case speech
    case voice
    case updates
    case diagnostics
    case advanced

    var id: String { rawValue }

    var title: String {
        switch self {
        case .general: "General"
        case .speech: "Speech"
        case .voice: "Voice"
        case .updates: "Updates"
        case .diagnostics: "Diagnostics"
        case .advanced: "Advanced"
        }
    }

    var systemImage: String {
        switch self {
        case .general: "gearshape"
        case .speech: "text.bubble"
        case .voice: "waveform"
        case .updates: "arrow.triangle.2.circlepath"
        case .diagnostics: "stethoscope"
        case .advanced: "slider.horizontal.3"
        }
    }

    var accessibilityDescription: String {
        switch self {
        case .general: "Application and runtime settings"
        case .speech: "Spoken event behavior"
        case .voice: "Text to speech voice settings"
        case .updates: "Update check settings"
        case .diagnostics: "Runtime health and logs"
        case .advanced: "Expert configuration settings"
        }
    }
}

enum SettingsApplyImpact: Equatable {
    case none
    case saveOnly
    case restartRuntime

    static func between(
        _ saved: JarvisConfigDraft,
        _ draft: JarvisConfigDraft
    ) -> SettingsApplyImpact {
        guard saved != draft else { return .none }

        var normalizedSaved = saved
        normalizedSaved.updateCheckEnabled = draft.updateCheckEnabled
        normalizedSaved.updateCheckIntervalHours = draft.updateCheckIntervalHours

        return normalizedSaved == draft ? .saveOnly : .restartRuntime
    }
}
