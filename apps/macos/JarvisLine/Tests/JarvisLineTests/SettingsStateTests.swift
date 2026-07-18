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

    @Test func speechChangesRestartRuntime() {
        var draft = JarvisConfigDraft.defaults
        draft.volume = 0.6

        #expect(
            SettingsApplyImpact.between(.defaults, draft) == .restartRuntime
        )
    }
}
