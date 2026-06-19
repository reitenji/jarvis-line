import Foundation

struct JarvisConfigDraft {
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
