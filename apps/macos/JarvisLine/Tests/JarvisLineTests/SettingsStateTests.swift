import Testing
@testable import JarvisLine

struct SettingsStateTests {
    @Test func destinationsHaveStableOrderAndUniqueIcons() {
        let destinations = SettingsDestination.allCases

        #expect(destinations.map(\.rawValue) == [
            "general",
            "speech",
            "voice",
            "updates",
            "diagnostics",
            "advanced",
        ])
        #expect(Set(destinations.map(\.systemImage)).count == destinations.count)
    }

    @Test func equalDraftsNeedNoApply() {
        #expect(
            SettingsApplyImpact.between(.defaults, .defaults) == .none
        )
    }

    @Test func updateOnlyChangesDoNotRestartRuntime() {
        var draft = JarvisConfigDraft.defaults
        draft.updateCheckIntervalHours = 48

        #expect(
            SettingsApplyImpact.between(.defaults, draft) == .saveOnly
        )
    }

    @Test func cleanupOnlyChangesDoNotRestartRuntime() {
        var draft = JarvisConfigDraft.defaults
        draft.cleanupIntervalHours = 168

        #expect(
            SettingsApplyImpact.between(.defaults, draft) == .saveOnly
        )
    }

    @Test func speechChangesRestartRuntime() {
        var draft = JarvisConfigDraft.defaults
        draft.volume = 0.6

        #expect(
            SettingsApplyImpact.between(.defaults, draft) == .restartRuntime
        )
    }

    @Test func closeDecisionProtectsUnsavedChanges() {
        #expect(
            SettingsCloseDecision.resolve(hasUnsavedChanges: false) == .close
        )
        #expect(
            SettingsCloseDecision.resolve(
                hasUnsavedChanges: true,
                choice: .apply
            ) == .applyAndClose
        )
        #expect(
            SettingsCloseDecision.resolve(
                hasUnsavedChanges: true,
                choice: .discard
            ) == .revertAndClose
        )
        #expect(
            SettingsCloseDecision.resolve(
                hasUnsavedChanges: true,
                choice: .cancel
            ) == .keepOpen
        )
    }

    @Test func customCommandFallbackIsAvailableOnlyWhenConfigured() {
        let withoutCommand = SettingsPresentation.fallbackOptions(
            contract: .empty,
            command: ""
        )
        let withCommand = SettingsPresentation.fallbackOptions(
            contract: .empty,
            command: "speak --text {text_json}"
        )

        #expect(!withoutCommand.contains("command"))
        #expect(withCommand.contains("command"))
        #expect(Set(withCommand).count == withCommand.count)
    }

    @Test func presentationPreservesAnInstalledVoiceOutsideTheContract() {
        #expect(
            SettingsPresentation.options(
                ["System default", "Samantha"],
                preserving: "Siri Voice 2"
            ) == ["System default", "Samantha", "Siri Voice 2"]
        )
    }
}
