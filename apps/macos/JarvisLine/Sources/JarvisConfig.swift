import Foundation

struct JarvisConfigDraft {
    static let ttsOptions = ["kokoro", "system", "macos", "command"]
    static let speakModeOptions = ["final_only", "commentary_and_final", "off"]
    static let lineLanguageOptions = ["English", "Turkish", "French", "Italian", "Japanese", "Chinese"]
    static let quietHourOptions = ["", "22:00-08:00", "20:00-08:00", "18:00-09:00"]
    static let maxSpokenCharsOptions = [120, 180, 240, 300]
    static let maxQueueSizeOptions = [4, 8, 16]
    static let fallbackOptions = ["none", "system", "macos", "command"]
    static let warmTextOptions = ["Ready.", "Jarvis ready.", "Speech ready."]
    static let kokoroVoiceOptions = [
        "bm_george:70,bm_lewis:30",
        "bm_george",
        "bm_lewis",
    ]
    static let kokoroLangOptions = ["en-gb", "en-us", "fr-fr", "it", "ja", "cmn"]
    static let speedOptions = [0.9, 1.0, 1.08, 1.2]
    static let systemRateOptions = [160, 180, 200, 220, 240]
    static let updateSourceOptions = ["git", "pypi"]
    static let updateIntervalOptions = [6, 12, 24, 48, 168]
    static let updateRepoOptions = [
        "https://github.com/reitenji/jarvis-line.git",
        "ssh://git@github.com-personal/reitenji/jarvis-line.git",
    ]
    static let updateRefOptions = ["latest", "main", "develop"]

    var tts: String
    var speakMode: String
    var speechEnabled: Bool
    var speakWithoutPrefix: Bool
    var lineLanguage: String
    var assistantName: String
    var maxSpokenChars: Int
    var maxQueueSize: Int
    var quietHours: String
    var volume: Double
    var fallbackTTS: String
    var warmTTS: Bool
    var warmTTSText: String
    var voice: String
    var lang: String
    var speed: Double
    var systemVoice: String
    var systemRate: Int
    var command: String
    var updateCheckEnabled: Bool
    var updateCheckIntervalHours: Int
    var updateSource: String
    var updateGitRepo: String
    var updateGitRef: String

    var blockingIssues: [String] {
        var issues: [String] = []

        if !Self.ttsOptions.contains(tts) {
            issues.append("Choose a supported TTS backend.")
        }
        if !Self.speakModeOptions.contains(speakMode) {
            issues.append("Choose a supported speak mode.")
        }
        if !Self.fallbackOptions.contains(fallbackTTS) {
            issues.append("Choose a supported fallback TTS.")
        }
        if fallbackTTS != "none" && fallbackTTS == tts {
            issues.append("Fallback TTS must be different from the primary TTS.")
        }

        if !Self.lineLanguageOptions.contains(lineLanguage) {
            issues.append("Choose a supported line language.")
        }

        if assistantName != "Jarvis" {
            issues.append("Assistant name is fixed to Jarvis in the app.")
        }
        if !Self.quietHourOptions.contains(quietHours) {
            issues.append("Choose a quiet-hours preset.")
        }

        if !Self.maxSpokenCharsOptions.contains(maxSpokenChars) {
            issues.append("Choose a supported spoken length preset.")
        }
        if !Self.maxQueueSizeOptions.contains(maxQueueSize) {
            issues.append("Choose a supported queue size preset.")
        }
        if !(0...1).contains(volume) {
            issues.append("Volume must be between 0.00 and 1.00.")
        }

        if tts == "kokoro" {
            if !Self.warmTextOptions.contains(warmTTSText) {
                issues.append("Choose a supported warm-up text preset.")
            }
            if !Self.kokoroLangOptions.contains(lang) {
                issues.append("Kokoro language must be one of en-us, en-gb, fr-fr, it, ja, or cmn.")
            }
            if !kokoroLanguageMatchesLineLanguage {
                issues.append("Kokoro language code must match the selected line language.")
            }
            if !Self.kokoroVoiceOptions.contains(voice) {
                issues.append("Choose a supported Kokoro voice preset.")
            }
            if !Self.speedOptions.contains(where: { abs($0 - speed) < 0.001 }) {
                issues.append("Choose a supported Kokoro speed preset.")
            }
        }

        if (tts == "system" || tts == "macos") && !Self.systemRateOptions.contains(systemRate) {
            issues.append("Choose a supported system voice rate preset.")
        }

        if tts == "command" {
            let value = command.trimmingCharacters(in: .whitespacesAndNewlines)
            if value.isEmpty {
                issues.append("Command backend requires a command.")
            }
            if !value.contains("{text}") && !value.contains("{text_json}") {
                issues.append("Command backend must include {text} or {text_json}.")
            }
            if value.contains("\n") || value.contains("\r") {
                issues.append("Command backend must be a single line.")
            }
        }

        if !Self.updateSourceOptions.contains(updateSource) {
            issues.append("Choose a supported update source.")
        }
        if updateSource == "git" {
            let repo = updateGitRepo.trimmingCharacters(in: .whitespacesAndNewlines)
            if repo.isEmpty {
                issues.append("Git update repo is required.")
            } else if !Self.isSafeGitRepo(repo) {
                issues.append("Git update repo must be an https, ssh, or git@ GitHub-style URL.")
            }
            if !Self.isSafeGitRef(updateGitRef) {
                issues.append("Git update ref must be a safe branch, tag, or latest.")
            } else if !Self.updateRefOptions.contains(updateGitRef) && !Self.isVersionTag(updateGitRef) {
                issues.append("Git update ref must be latest, main, develop, or a version tag.")
            }
        }
        if !Self.updateIntervalOptions.contains(updateCheckIntervalHours) {
            issues.append("Choose a supported update interval preset.")
        }

        return issues
    }

    var guidance: [String] {
        var notes: [String] = []
        if tts == "kokoro" && lineLanguage != "English" {
            notes.append("Kokoro only works well when its language code and model support the selected language.")
        }
        if tts == "system" || tts == "macos" {
            notes.append("System/macOS voice quality depends on the voice selected in macOS Read & Speak settings.")
        }
        if tts == "command" {
            notes.append("Keep API keys outside this config; call a wrapper command that reads secrets from environment variables.")
        }
        return notes
    }

    static let defaults = JarvisConfigDraft(
        tts: "kokoro",
        speakMode: "final_only",
        speechEnabled: true,
        speakWithoutPrefix: false,
        lineLanguage: "English",
        assistantName: "Jarvis",
        maxSpokenChars: 240,
        maxQueueSize: 8,
        quietHours: "",
        volume: 0.7,
        fallbackTTS: "none",
        warmTTS: true,
        warmTTSText: "Ready.",
        voice: "bm_george:70,bm_lewis:30",
        lang: "en-gb",
        speed: 1.08,
        systemVoice: "",
        systemRate: 200,
        command: "",
        updateCheckEnabled: true,
        updateCheckIntervalHours: 24,
        updateSource: "git",
        updateGitRepo: "https://github.com/reitenji/jarvis-line.git",
        updateGitRef: "latest"
    )

    init(_ data: [String: Any]) {
        let defaults = JarvisConfigDraft.defaults
        tts = Self.string(data["tts"], defaults.tts)
        speakMode = Self.string(data["speak_mode"], defaults.speakMode)
        speechEnabled = Self.bool(data["speech_enabled"], defaults.speechEnabled)
        speakWithoutPrefix = Self.bool(data["speak_without_prefix"], defaults.speakWithoutPrefix)
        lineLanguage = Self.string(data["line_language"], defaults.lineLanguage)
        assistantName = Self.string(data["assistant_name"], defaults.assistantName)
        maxSpokenChars = Self.int(data["max_spoken_chars"], defaults.maxSpokenChars)
        maxQueueSize = Self.int(data["max_queue_size"], defaults.maxQueueSize)
        quietHours = Self.optionalString(data["quiet_hours"])
        volume = Self.double(data["volume"], defaults.volume)
        fallbackTTS = Self.optionalString(data["fallback_tts"]).isEmpty ? "none" : Self.optionalString(data["fallback_tts"])
        warmTTS = Self.bool(data["warm_tts"], defaults.warmTTS)
        warmTTSText = Self.string(data["warm_tts_text"], defaults.warmTTSText)
        voice = Self.string(data["voice"], defaults.voice)
        lang = Self.string(data["lang"], defaults.lang)
        speed = Self.double(data["speed"], defaults.speed)
        systemVoice = Self.optionalString(data["system_voice"])
        systemRate = Self.int(data["system_rate"], defaults.systemRate)
        command = Self.optionalString(data["command"])
        updateCheckEnabled = Self.bool(data["update_check_enabled"], defaults.updateCheckEnabled)
        updateCheckIntervalHours = Self.int(data["update_check_interval_hours"], defaults.updateCheckIntervalHours)
        updateSource = Self.string(data["update_source"], defaults.updateSource)
        updateGitRepo = Self.string(data["update_git_repo"], defaults.updateGitRepo)
        updateGitRef = Self.string(data["update_git_ref"], defaults.updateGitRef)
    }

    private init(
        tts: String,
        speakMode: String,
        speechEnabled: Bool,
        speakWithoutPrefix: Bool,
        lineLanguage: String,
        assistantName: String,
        maxSpokenChars: Int,
        maxQueueSize: Int,
        quietHours: String,
        volume: Double,
        fallbackTTS: String,
        warmTTS: Bool,
        warmTTSText: String,
        voice: String,
        lang: String,
        speed: Double,
        systemVoice: String,
        systemRate: Int,
        command: String,
        updateCheckEnabled: Bool,
        updateCheckIntervalHours: Int,
        updateSource: String,
        updateGitRepo: String,
        updateGitRef: String
    ) {
        self.tts = tts
        self.speakMode = speakMode
        self.speechEnabled = speechEnabled
        self.speakWithoutPrefix = speakWithoutPrefix
        self.lineLanguage = lineLanguage
        self.assistantName = assistantName
        self.maxSpokenChars = maxSpokenChars
        self.maxQueueSize = maxQueueSize
        self.quietHours = quietHours
        self.volume = volume
        self.fallbackTTS = fallbackTTS
        self.warmTTS = warmTTS
        self.warmTTSText = warmTTSText
        self.voice = voice
        self.lang = lang
        self.speed = speed
        self.systemVoice = systemVoice
        self.systemRate = systemRate
        self.command = command
        self.updateCheckEnabled = updateCheckEnabled
        self.updateCheckIntervalHours = updateCheckIntervalHours
        self.updateSource = updateSource
        self.updateGitRepo = updateGitRepo
        self.updateGitRef = updateGitRef
    }

    func applying(to data: [String: Any]) -> [String: Any] {
        var updated = data
        updated["tts"] = tts
        updated["speak_mode"] = speakMode
        updated["speech_enabled"] = speechEnabled
        updated["speak_without_prefix"] = speakWithoutPrefix
        updated["line_language"] = lineLanguage.trimmedOrDefault("English")
        updated["assistant_name"] = assistantName.trimmedOrDefault("Jarvis")
        updated["max_spoken_chars"] = maxSpokenChars
        updated["max_queue_size"] = maxQueueSize
        updated["quiet_hours"] = quietHours.trimmedNilOrValue
        updated["volume"] = min(max(volume, 0), 1)
        updated["fallback_tts"] = fallbackTTS == "none" ? NSNull() : fallbackTTS
        updated["warm_tts"] = warmTTS
        updated["warm_tts_text"] = warmTTSText.trimmedOrDefault("Ready.")
        updated["voice"] = voice.trimmedOrDefault("bm_george:70,bm_lewis:30")
        updated["lang"] = lang.trimmedOrDefault("en-gb")
        updated["speed"] = speed
        updated["system_voice"] = systemVoice.trimmedNilOrValue
        updated["system_rate"] = systemRate
        updated["command"] = command.trimmedNilOrValue
        updated["update_check_enabled"] = updateCheckEnabled
        updated["update_check_interval_hours"] = updateCheckIntervalHours
        updated["update_source"] = updateSource
        updated["update_git_repo"] = updateGitRepo.trimmedOrDefault("https://github.com/reitenji/jarvis-line.git")
        updated["update_git_ref"] = updateGitRef.trimmedOrDefault("latest")
        return updated
    }

    private var kokoroLanguageMatchesLineLanguage: Bool {
        switch lineLanguage.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "english":
            return ["en-us", "en-gb"].contains(lang)
        case "french":
            return lang == "fr-fr"
        case "italian":
            return lang == "it"
        case "japanese":
            return lang == "ja"
        case "chinese", "mandarin", "mandarin chinese":
            return lang == "cmn"
        default:
            return false
        }
    }

    private static func isSafeGitRepo(_ value: String) -> Bool {
        if value.hasPrefix("-") || value.contains(" ") || value.contains("\n") || value.contains("\r") {
            return false
        }
        return value.hasPrefix("https://") || value.hasPrefix("ssh://") ||
            value.range(of: #"^git@[^:]+:[^ ]+/.+\.git$"#, options: .regularExpression) != nil
    }

    private static func isSafeGitRef(_ value: String) -> Bool {
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty || text.hasPrefix("-") || text.contains(" ") || text.contains("..") {
            return false
        }
        let forbidden = CharacterSet(charactersIn: #"~^:?*[\\"#)
        return text.rangeOfCharacter(from: forbidden) == nil
    }

    private static func isVersionTag(_ value: String) -> Bool {
        value.range(of: #"^v[0-9]+\.[0-9]+\.[0-9]+([ab][0-9]+|rc[0-9]+)?$"#, options: .regularExpression) != nil
    }

    private static func string(_ value: Any?, _ fallback: String) -> String {
        optionalString(value).isEmpty ? fallback : optionalString(value)
    }

    private static func optionalString(_ value: Any?) -> String {
        if value is NSNull {
            return ""
        }
        return String(describing: value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func bool(_ value: Any?, _ fallback: Bool) -> Bool {
        if let value = value as? Bool {
            return value
        }
        if let text = value as? String {
            return text.lowercased() == "true"
        }
        return fallback
    }

    private static func int(_ value: Any?, _ fallback: Int) -> Int {
        if let value = value as? Int {
            return value
        }
        if let value = value as? Double {
            return Int(value)
        }
        if let text = value as? String, let parsed = Int(text) {
            return parsed
        }
        return fallback
    }

    private static func double(_ value: Any?, _ fallback: Double) -> Double {
        if let value = value as? Double {
            return value
        }
        if let value = value as? Int {
            return Double(value)
        }
        if let text = value as? String, let parsed = Double(text) {
            return parsed
        }
        return fallback
    }
}

struct JarvisConfigStore {
    let path = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".codex/hooks/jarvis_line_config.json")

    var displayPath: String {
        "~/.codex/hooks/jarvis_line_config.json"
    }

    func load() throws -> JarvisConfigDraft {
        JarvisConfigDraft(try rawConfig())
    }

    func save(_ draft: JarvisConfigDraft) throws {
        let issues = draft.blockingIssues
        if !issues.isEmpty {
            throw ConfigValidationError(issues: issues)
        }
        let updated = draft.applying(to: try rawConfig())
        let data = try JSONSerialization.data(withJSONObject: updated, options: [.prettyPrinted, .sortedKeys])
        try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: path)
    }

    private func rawConfig() throws -> [String: Any] {
        guard FileManager.default.fileExists(atPath: path.path) else {
            return defaultRawConfig()
        }
        let data = try Data(contentsOf: path)
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }

    private func defaultRawConfig() -> [String: Any] {
        let ttsHome = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".jarvis-line/tts")
        let modelDir = ttsHome.appendingPathComponent("kokoro-models")
        return [
            "tts": "kokoro",
            "speak_mode": "final_only",
            "line_prefixes": ["Jarvis line:"],
            "speak_without_prefix": false,
            "line_language": "English",
            "max_spoken_chars": 240,
            "quiet_hours": NSNull(),
            "quiet_days": [],
            "max_queue_size": 8,
            "dedupe_window_seconds": NSNull(),
            "fallback_tts": NSNull(),
            "warm_tts": true,
            "warm_tts_text": "Ready.",
            "audio_worker_idle_exit_seconds": 60,
            "audio_worker_max_rss_mb": 512,
            "message_template": "{line}",
            "assistant_name": "Jarvis",
            "speech_enabled": true,
            "update_check_enabled": true,
            "update_check_interval_hours": 24,
            "update_index_url": "https://pypi.org/pypi/jarvis-line/json",
            "update_source": "git",
            "update_git_repo": "https://github.com/reitenji/jarvis-line.git",
            "update_git_ref": "latest",
            "last_update_check_ts": 0,
            "model_path": modelDir.appendingPathComponent("kokoro-v1.0.onnx").path,
            "voices_path": modelDir.appendingPathComponent("voices-v1.0.bin").path,
            "voice": "bm_george:70,bm_lewis:30",
            "lang": "en-gb",
            "speed": 1.08,
            "volume": 0.7,
            "play_by_default": true,
            "final_trigger_mode": "notify",
            "playback_mode": "tempfile",
            "fallback_playback_mode": "tempfile",
            "delete_after_play": true,
            "temp_dir": ttsHome.appendingPathComponent("generated").path,
        ]
    }
}

struct ConfigValidationError: LocalizedError {
    let issues: [String]

    var errorDescription: String? {
        "Fix settings before saving:\n" + issues.map { "- \($0)" }.joined(separator: "\n")
    }
}

private extension String {
    func trimmedOrDefault(_ fallback: String) -> String {
        let text = trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? fallback : text
    }

    var trimmedNilOrValue: Any {
        let text = trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? NSNull() : text
    }
}
