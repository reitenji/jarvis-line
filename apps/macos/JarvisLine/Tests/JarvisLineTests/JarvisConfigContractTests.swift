import Foundation
import Testing
@testable import JarvisLine

struct JarvisConfigContractTests {
    @Test func cleanupDefaultsAreBoundedAndPersist() {
        var draft = JarvisConfigDraft([:])

        #expect(draft.cleanupEnabled)
        #expect(draft.cleanupIntervalHours == 24)
        draft.cleanupEnabled = false
        draft.cleanupIntervalHours = 168
        let saved = draft.applying(to: [:])
        #expect(saved["cleanup_enabled"] as? Bool == false)
        #expect(saved["cleanup_interval_hours"] as? Int == 168)
    }

    @Test func attentionDefaultsOffAndPersists() {
        var draft = JarvisConfigDraft([:])

        #expect(!draft.attentionEnabled)
        draft.attentionEnabled = true
        #expect(draft.applying(to: [:])["attention_enabled"] as? Bool == true)
    }

    @Test func finalChimeDefaultsOnAndPersists() {
        var draft = JarvisConfigDraft([:])

        #expect(draft.finalChimeEnabled)
        #expect(draft.finalChimeVolume == 1.0)
        draft.finalChimeEnabled = false
        draft.finalChimeVolume = 0.6
        let saved = draft.applying(to: [:])
        #expect(saved["final_chime_enabled"] as? Bool == false)
        #expect(saved["final_chime_volume"] as? Double == 0.6)
    }

    @Test func finalChimeVolumeLoadsAndRejectsOutOfRangeValues() {
        var draft = JarvisConfigDraft(["final_chime_volume": 0.35])

        #expect(draft.finalChimeVolume == 0.35)
        #expect(
            !draft.blockingIssues.contains(
                "Final chime volume must be between 0% and 100%."
            )
        )

        draft.finalChimeVolume = -0.1
        #expect(
            draft.blockingIssues.contains(
                "Final chime volume must be between 0% and 100%."
            )
        )

        draft.finalChimeVolume = 1.1
        #expect(
            draft.blockingIssues.contains(
                "Final chime volume must be between 0% and 100%."
            )
        )
    }

    @Test func configStoreRejectsBooleanNumericValues() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let path = directory.appendingPathComponent("config.json")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        try Data(
            #"{"final_chime_volume":false,"max_queue_size":false,"cleanup_interval_hours":true}"#.utf8
        ).write(to: path)
        let falseDraft = try JarvisConfigStore(path: path).load()
        #expect(falseDraft.finalChimeVolume == 1.0)
        #expect(falseDraft.maxQueueSize == 8)
        #expect(falseDraft.cleanupIntervalHours == 24)

        try Data(#"{"final_chime_volume":true}"#.utf8).write(to: path)
        let trueDraft = try JarvisConfigStore(path: path).load()
        #expect(trueDraft.finalChimeVolume == 1.0)
    }

    @Test func contractDecodesDefaultsAndOptions() throws {
        let json = #"""
        {
          "version": 1,
          "defaults": {"tts": "system", "max_queue_size": 4},
          "fields": {"tts": {"type": "string", "values": ["system", "command"]}},
          "backends": {"system": {"description": "System", "supports": ["tts"], "ignores": []}},
          "ui_options": {"max_queue_size": [4, 8], "speed": [1.0, 1.2]}
        }
        """#

        let contract = try JarvisConfigContract.fromJSON(json)

        #expect(contract.version == 1)
        #expect(contract.stringDefault("tts") == "system")
        #expect(contract.stringOptions("tts") == ["system", "command"])
        #expect(contract.intOptions("max_queue_size") == [4, 8])
        #expect(contract.doubleOptions("speed") == [1.0, 1.2])
    }

    @Test func configStoreUsesContractDefaultsForMissingValues() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let path = directory.appendingPathComponent("config.json")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data(#"{"volume":0.4}"#.utf8).write(to: path)
        let contract = try JarvisConfigContract.fromJSON(#"""
        {
          "version": 1,
          "defaults": {"tts":"system","speak_mode":"commentary_and_final","max_queue_size":4},
          "fields": {},
          "backends": {},
          "ui_options": {}
        }
        """#)

        let draft = try JarvisConfigStore(path: path).load(defaults: contract.defaults)

        #expect(draft.tts == "system")
        #expect(draft.speakMode == "commentary_and_final")
        #expect(draft.maxQueueSize == 4)
        #expect(draft.volume == 0.4)
    }

    @Test func configStorePersistsContractDefaultsOnFirstSave() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let path = directory.appendingPathComponent("config.json")
        defer { try? FileManager.default.removeItem(at: directory) }
        let contract = try JarvisConfigContract.fromJSON(#"""
        {
          "version": 1,
          "defaults": {
            "audio_worker_max_rss_mb": 512,
            "debug_content_logging": false,
            "model_path": "/models/kokoro.onnx"
          },
          "fields": {},
          "backends": {},
          "ui_options": {}
        }
        """#)

        try JarvisConfigStore(path: path).save(.defaults, contract: contract)

        let data = try Data(contentsOf: path)
        let saved = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect(saved["audio_worker_max_rss_mb"] as? Int == 512)
        #expect(saved["debug_content_logging"] as? Bool == false)
        #expect(saved["model_path"] as? String == "/models/kokoro.onnx")
    }

    @Test func macOSBackendRoundTripsMacOSVoiceKeys() {
        var draft = JarvisConfigDraft([
            "tts": "macos",
            "macos_voice": "Samantha",
            "macos_rate": 185,
        ])

        #expect(draft.systemVoice == "Samantha")
        #expect(draft.systemRate == 185)
        #expect(!draft.blockingIssues.contains("Choose a supported system voice rate preset."))

        draft.systemVoice = "Ava"
        draft.systemRate = 200
        let saved = draft.applying(to: [:])

        #expect(saved["macos_voice"] as? String == "Ava")
        #expect(saved["macos_rate"] as? Int == 200)
    }

    @Test func contractControlsBackendValidation() throws {
        let contract = try JarvisConfigContract.fromJSON(#"""
        {
          "version": 1,
          "defaults": {},
          "fields": {"tts": {"type":"string","values":["future"]}},
          "backends": {},
          "ui_options": {}
        }
        """#)
        let draft = JarvisConfigDraft([
            "tts": "future",
            "speak_mode": "final_only",
            "line_language": "English",
            "assistant_name": "Jarvis",
            "max_spoken_chars": 240,
            "max_queue_size": 8,
            "volume": 0.7,
            "update_check_interval_hours": 24,
        ])

        #expect(!draft.blockingIssues(using: contract).contains("Choose a supported TTS backend."))
    }
}
