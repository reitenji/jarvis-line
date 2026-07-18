import Foundation

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

enum SettingsCloseChoice {
    case apply
    case discard
    case cancel
}

enum SettingsCloseDecision: Equatable {
    case close
    case applyAndClose
    case revertAndClose
    case keepOpen

    static func resolve(
        hasUnsavedChanges: Bool,
        choice: SettingsCloseChoice? = nil
    ) -> SettingsCloseDecision {
        guard hasUnsavedChanges else { return .close }

        switch choice {
        case .apply: return .applyAndClose
        case .discard: return .revertAndClose
        case .cancel, .none: return .keepOpen
        }
    }
}

enum SettingsPresentation {
    static func fallbackOptions(
        contract: JarvisConfigContract,
        command: String
    ) -> [String] {
        var values = ["none"] + contract.stringOptions(
            "fallback_tts",
            fallback: JarvisConfigDraft.fallbackOptions.filter { $0 != "none" }
        )
        if command.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            values.removeAll { $0 == "command" }
        }
        return unique(values)
    }

    static func options(_ base: [String], preserving current: String) -> [String] {
        let value = current.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, !base.contains(value) else {
            return base
        }
        return base + [value]
    }

    static func speakModeLabel(_ value: String) -> String {
        switch value {
        case "final_only": return "Final only"
        case "commentary_and_final": return "Commentary + final"
        case "off": return "Off"
        default: return value
        }
    }

    static func spokenLengthLabel(_ value: Int) -> String {
        switch value {
        case 120: return "Short · 120"
        case 180: return "Balanced · 180"
        case 240: return "Detailed · 240"
        case 300: return "Verbose · 300"
        default: return "\(value) characters"
        }
    }

    static func quietHoursLabel(_ value: String) -> String {
        switch value {
        case "": return "Off"
        case "22:00-08:00": return "Night · 22:00-08:00"
        case "20:00-08:00": return "Evening · 20:00-08:00"
        case "18:00-09:00": return "After work · 18:00-09:00"
        default: return value
        }
    }

    static func ttsLabel(_ value: String) -> String {
        switch value {
        case "kokoro": return "Kokoro · recommended local"
        case "system": return "System voice"
        case "macos": return "macOS say"
        case "command": return "Custom command"
        default: return value
        }
    }

    static func fallbackLabel(_ value: String) -> String {
        switch value {
        case "none": return "None"
        case "system": return "System"
        case "macos": return "macOS"
        case "command": return "Command"
        default: return value
        }
    }

    static func kokoroVoiceLabel(_ value: String) -> String {
        switch value {
        case "bm_george:70,bm_lewis:30": return "George + Lewis blend"
        case "bm_george": return "George"
        case "bm_lewis": return "Lewis"
        default: return value
        }
    }

    static func kokoroLanguageLabel(_ value: String) -> String {
        switch value {
        case "en-gb": return "English GB"
        case "en-us": return "English US"
        case "fr-fr": return "French"
        case "it": return "Italian"
        case "ja": return "Japanese"
        case "cmn": return "Mandarin"
        default: return value
        }
    }

    static func speedLabel(_ value: Double) -> String {
        if abs(value - 0.9) < 0.001 { return "Calm · 0.90" }
        if abs(value - 1.0) < 0.001 { return "Normal · 1.00" }
        if abs(value - 1.08) < 0.001 { return "Jarvis default · 1.08" }
        if abs(value - 1.2) < 0.001 { return "Fast · 1.20" }
        return String(format: "%.2f", value)
    }

    private static func unique(_ values: [String]) -> [String] {
        values.reduce(into: []) { result, value in
            if !result.contains(value) {
                result.append(value)
            }
        }
    }
}
