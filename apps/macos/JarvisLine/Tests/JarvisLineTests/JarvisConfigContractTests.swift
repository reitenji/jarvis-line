import Foundation
import Testing
@testable import JarvisLine

struct JarvisConfigContractTests {
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
