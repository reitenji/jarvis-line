# macOS Settings Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the long scrolling Jarvis Line Settings form with a polished, two-pane macOS settings window that keeps common controls discoverable, protects advanced configuration, and applies changes predictably.

**Architecture:** A pure settings-state layer defines navigation metadata, dirty-state comparison, and restart impact. `JarvisLineModel` remains the only persistence and CLI boundary and stores both the editable draft and the last loaded snapshot. A dedicated `SettingsWindowView` owns the sidebar, branded header, destination views, validation, and toolbar apply flow while the existing `JarvisLinePanel` remains the compact menu bar surface.

**Tech Stack:** Swift 5.9, SwiftUI, AppKit, Swift Testing, Swift Package Manager, existing Python packaging scripts.

## Global Constraints

- Introduce no new config keys and preserve the Python config contract as the source of truth.
- Keep the quick menu, Setup Assistant, hook behavior, and direct Dock visibility behavior intact.
- Use native toggles, pickers, sliders, disclosure, keyboard focus, and SF Symbols.
- Keep free-form command text exclusively in Advanced and preserve existing validation.
- Do not nest cards or restore a single long settings page.
- Apply update-only changes without restarting; restart the runtime for speech, voice, queue, or command changes.
- Preserve draft edits when changing destinations or when apply fails.
- Do not merge or release this stacked branch until PR #75 lands and the branch is rebased onto current `develop`.

## File Map

- Create `apps/macos/JarvisLine/Sources/SettingsState.swift`: navigation destinations and apply-impact classification.
- Create `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`: sidebar, compact header, destination views, setting rows, validation, and apply toolbar.
- Create `apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift`: destination and impact tests.
- Modify `apps/macos/JarvisLine/Sources/JarvisConfig.swift`: add value equality for draft comparison.
- Modify `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`: model snapshot/apply behavior, settings window host, close confirmation, and removal of the legacy settings-only form.
- Modify `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift`: dirty state, revert, success, failure, and immediate-toggle snapshot coverage.
- Modify `apps/macos/JarvisLine/README.md` only if visible Settings labels or screenshots require alignment.

---

### Task 1: Pure Settings State

**Files:**
- Create: `apps/macos/JarvisLine/Sources/SettingsState.swift`
- Create: `apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisConfig.swift`

- [ ] **Step 1: Write failing destination and impact tests**

Cover the stable order `general`, `speech`, `voice`, `updates`, `diagnostics`, `advanced`; unique SF Symbols; update-only save behavior; runtime restart behavior; and equal drafts producing no action.

```swift
@Test func updateOnlyChangesDoNotRestartRuntime() {
    var draft = JarvisConfigDraft.defaults
    draft.updateCheckIntervalHours = 48
    #expect(SettingsApplyImpact.between(.defaults, draft) == .saveOnly)
}

@Test func speechChangesRestartRuntime() {
    var draft = JarvisConfigDraft.defaults
    draft.volume = 0.6
    #expect(SettingsApplyImpact.between(.defaults, draft) == .restartRuntime)
}
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run: `cd apps/macos/JarvisLine && swift test --filter SettingsStateTests`

Expected: FAIL because the state types and draft equality do not exist.

- [ ] **Step 3: Implement value equality, destinations, and impact classification**

Make `JarvisConfigDraft` conform to `Equatable`. Add `SettingsDestination` with title, icon, and concise accessibility description. Add `SettingsApplyImpact` with `.none`, `.saveOnly`, and `.restartRuntime`; classify only `updateCheckEnabled` and `updateCheckIntervalHours` as save-only differences.

- [ ] **Step 4: Run state tests**

Run: `cd apps/macos/JarvisLine && swift test --filter SettingsStateTests`

Expected: PASS.

- [ ] **Step 5: Commit state primitives**

```bash
git add apps/macos/JarvisLine/Sources/SettingsState.swift apps/macos/JarvisLine/Sources/JarvisConfig.swift apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift
git commit -m "feat: add settings state model"
```

### Task 2: Draft Snapshot And Apply Flow

**Files:**
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift`

- [ ] **Step 1: Write failing model tests**

Cover a clean initial draft, dirty state after editing, revert restoring the saved snapshot, update-only apply omitting `restart`, runtime-impact apply invoking `restart`, failed save preserving the draft, and the quick attention toggle keeping the snapshot synchronized.

- [ ] **Step 2: Run model tests and verify failure**

Run: `cd apps/macos/JarvisLine && swift test --filter JarvisLineModelTests`

Expected: FAIL because snapshot, dirty, revert, and impact-aware apply behavior do not exist.

- [ ] **Step 3: Implement snapshot-backed editing**

Add a private published saved draft, `hasUnsavedChanges`, `pendingApplyImpact`, `revertConfig()`, and `applyConfig() async -> Bool`. Update refresh/load to replace both draft and snapshot. Update successful direct attention persistence to synchronize the corresponding snapshot value. Keep failed drafts untouched and expose a short success message separately from command output.

- [ ] **Step 4: Run model tests**

Run: `cd apps/macos/JarvisLine && swift test --filter JarvisLineModelTests`

Expected: PASS, including legacy attention-toggle tests.

- [ ] **Step 5: Commit model behavior**

```bash
git add apps/macos/JarvisLine/Sources/JarvisLineApp.swift apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift
git commit -m "feat: stage and apply settings safely"
```

### Task 3: Two-Pane Settings Window

**Files:**
- Create: `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`

- [ ] **Step 1: Add a compile-level view test surface**

Keep destination content selected by `SettingsDestination` and expose pure labels/options through internal helpers so state tests can verify bounded choices without snapshot testing private SwiftUI internals.

- [ ] **Step 2: Implement the settings shell**

Build a stable-width sidebar and independently scrolling content pane. Add a compact header with app mark, app/CLI versions, explicit runtime state, and refresh icon. Put Apply and Revert in the window toolbar and show them only while dirty. Preserve minimum size at 700 by 660 and default to approximately 860 by 720.

- [ ] **Step 3: Implement destination views**

Implement:

- General: Setup Assistant, Dock visibility, app/CLI version, runtime state.
- Speech: speech, attention, speak mode, language, spoken length, quiet preset.
- Voice: backend, fallback, volume, backend-compatible voice/language/rate/speed controls, warm-up settings, test voice.
- Updates: update checks, bounded interval, official GitHub source, latest/current version context.
- Diagnostics: watcher, worker, RSS, queue, doctor summary, recent privacy-safe trace, logs, refresh/restart/repair.
- Advanced: queue size, prefix behavior, custom command summary or field, and backend-specific expert values.

Use unframed grouped rows with dividers, no nested cards, and no visible how-to copy except validation or compatibility guidance.

- [ ] **Step 4: Replace the legacy settings host**

Change `SettingsWindowController` to host `SettingsWindowView`. Remove `settingsWindowBody`, `settingsView`, old settings sections, and the persistent footer from `JarvisLinePanel`; keep all quick-menu helpers still referenced by quick mode.

- [ ] **Step 5: Build and fix all compiler errors**

Run: `cd apps/macos/JarvisLine && swift build`

Expected: PASS with no unused settings-only code left in `JarvisLinePanel`.

- [ ] **Step 6: Commit the view redesign**

```bash
git add apps/macos/JarvisLine/Sources/SettingsWindowView.swift apps/macos/JarvisLine/Sources/JarvisLineApp.swift
git commit -m "feat: redesign macos settings window"
```

### Task 4: Dirty Close Confirmation And Error States

**Files:**
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`
- Modify: `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift`

- [ ] **Step 1: Write failing close-decision tests**

Add a pure `SettingsCloseAction` decision surface covering clean close, apply, discard, and cancel. Verify discard calls revert and apply closes only after persistence succeeds.

- [ ] **Step 2: Implement AppKit close confirmation**

Store the model in `SettingsWindowController`. In `windowShouldClose`, allow clean closes immediately; otherwise show a native alert with Apply, Discard, and Cancel. Apply asynchronously and close only on success. Discard restores the snapshot before closing.

- [ ] **Step 3: Add explicit loading, validation, error, and success states**

Disable only affected actions while busy, keep sidebar navigation stable, show blocking validation near Apply, retain failed drafts, and clear the short success confirmation after a brief delay.

- [ ] **Step 4: Run focused and full Swift tests**

Run: `cd apps/macos/JarvisLine && swift test`

Expected: PASS.

- [ ] **Step 5: Commit close and failure handling**

```bash
git add apps/macos/JarvisLine/Sources/JarvisLineApp.swift apps/macos/JarvisLine/Sources/SettingsWindowView.swift apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift
git commit -m "feat: protect unsaved settings changes"
```

### Task 5: Visual And Accessibility QA

**Files:**
- Modify only files required by findings from this task.

- [ ] **Step 1: Build and launch the debug app**

Run: `cd apps/macos/JarvisLine && swift build`

Launch through the repository packaging/run script used by the existing app README. Capture Settings at the 700 by 660 minimum and a wider desktop size.

- [ ] **Step 2: Inspect all destinations and key states**

Check default, dirty, validation error, loading, stopped runtime, empty voice list, custom command, and Advanced states. Verify no clipping, overlap, nested cards, uncontrolled free input, or titlebar drag regression.

- [ ] **Step 3: Verify keyboard and accessibility behavior**

Confirm sidebar selection, tab order, switch/picker labels, toolbar labels/tooltips, visible focus rings, and non-color health descriptions.

- [ ] **Step 4: Apply only evidence-backed polish fixes**

Keep the graphite/cyan/gold brand, corners at 8 points or less, compact type, stable row heights, and restrained transitions. Re-run `swift test` and `swift build` after edits.

- [ ] **Step 5: Commit QA fixes if any**

```bash
git add apps/macos/JarvisLine
git commit -m "fix: polish macos settings experience"
```

### Task 6: Release Build And Local Installation

**Files:**
- Modify packaging files only if the existing scripts fail for a reproducible project reason.

- [ ] **Step 1: Run the full verification suite**

Run:

```bash
cd apps/macos/JarvisLine && swift test
cd apps/macos/JarvisLine && swift build -c release
.venv/bin/python -m pytest tests/test_release_metadata.py -q
git diff --check
```

Expected: all commands pass.

- [ ] **Step 2: Package the app using the repository script**

Use the documented packaging command and confirm the bundle reports version `0.5.0`, has the expected bundle identifier, icon, executable, and only one Jarvis Line app bundle in the generated artifact.

- [ ] **Step 3: Replace the local app safely**

Quit the running Jarvis Line app, replace `/Applications/Jarvis Line.app` with the newly built bundle, launch it once, and confirm one application instance, one watcher, and one audio worker. Preserve `~/.codex/hooks/jarvis_line_config.json` and all user TTS assets.

- [ ] **Step 4: Verify persistence and runtime behavior**

Open Settings, change one update-only setting and one runtime setting, verify the appropriate apply impact, revert both, run a voice test, and confirm the worker remains healthy without duplicate playback.

- [ ] **Step 5: Record final branch state**

Confirm commits are limited to the Settings feature and its plan. Do not push or open the final PR until PR #75 is merged and this branch is rebased onto current `develop`.
