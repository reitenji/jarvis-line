# macOS Settings Redesign

## Goal

Turn the Jarvis Line Settings window into a focused macOS product surface that
is easy to scan, difficult to misconfigure, and consistent with the existing
brand. Preserve all current configuration capabilities while separating common
controls from advanced ones.

## Current Problems

- All settings appear in one long scrolling form.
- The large runtime header competes with the settings themselves.
- Nested framed containers weaken hierarchy and reduce usable space.
- Common switches, TTS selection, updates, and diagnostics are mixed together.
- Advanced controls are as prominent as everyday choices.
- Persistent Save and Save + Restart actions do not explain when a restart is
  actually required.

## Considered Directions

### Compact Single Page

Keep the current structure and reduce spacing, header size, and decoration.
This is low risk, but it preserves the long-scroll navigation problem and does
not create a durable structure for future settings.

### Status-First Dashboard

Lead with runtime health and present settings as dashboard modules. This would
look expressive, but routine configuration would take more space and become
slower to scan.

### Sidebar With Progressive Disclosure

Use a compact sidebar for stable categories and expose advanced controls only
in a dedicated section. This is the selected direction because it scales,
matches familiar macOS patterns, and keeps routine decisions clear.

## Information Architecture

The Settings window uses a two-pane layout with these destinations:

1. **General**: app visibility, setup assistant, product versions, and startup
   behavior.
2. **Speech**: speech master switch, attention alerts, speech timing, language,
   spoken length, and quiet scheduling presets.
3. **Voice**: TTS backend, installed voice selection, voice-specific supported
   controls, fallback, and a test action.
4. **Updates**: automatic update checks, check interval, current version, latest
   known version, and a manual check action.
5. **Diagnostics**: watcher and worker health, queue state, doctor summary,
   privacy-safe trace, logs, restart, and queue clearing.
6. **Advanced**: queue limits, custom quiet-hour values, prefix behavior,
   resource limits, custom command backend fields, and other expert-only
   controls.

The sidebar remains visible while content scrolls independently. It uses a
stable width around 180 points and familiar SF Symbols. Selection uses the
brand cyan; attention and warning states use the existing gold accent.

## Window Composition

### Compact Header

The oversized product header is replaced by a compact title row containing the
app icon, Jarvis Line name, app and CLI versions, and a single runtime health
indicator. Refresh is an icon button with a tooltip. The header does not repeat
details that belong in Diagnostics.

### Content Pane

Each destination has one title and an unframed grouped form. Rows align labels
and controls on a consistent grid. Controls use toggles for booleans, pickers
for bounded choices, steppers or menus for numeric presets, and icon buttons
for compact commands. Free-form fields remain only where a custom TTS command
requires expert input and appear exclusively under Advanced.

Cards are not nested. A light divider or subtle grouped background separates
related rows. Helper text is limited to validation, compatibility, or restart
impact and is not used as feature narration.

### Apply Flow

Configuration remains staged in `JarvisConfigDraft`. A window toolbar exposes
`Apply` only while the draft differs from the last loaded configuration. A
secondary revert icon is available while dirty. Settings that require a runtime
restart mark the pending state; applying them uses the existing save-and-restart
path. Settings that are already immediate, such as Dock visibility, retain
their current direct behavior.

Success is shown as a brief inline toolbar confirmation. Errors remain visible
near the toolbar and preserve the draft so the user can correct or retry.

## Component Boundaries

- `SettingsDestination` defines stable navigation categories and metadata.
- `SettingsSidebar` owns destination selection only.
- `SettingsHeader` renders product identity and compact runtime health.
- One view per destination owns layout but binds to the existing shared model.
- Reusable setting rows standardize label, optional detail, control alignment,
  disabled state, and restart indication.
- `JarvisLineModel` remains the command and persistence boundary. Views do not
  invoke the CLI directly.

The existing quick menu remains intentionally small and is not converted into a
second Settings surface.

## Data And State Flow

1. Opening Settings calls the existing model refresh.
2. The model loads runtime status, configuration, contract capabilities, voices,
   and versions.
3. Controls edit the draft in memory.
4. Dirty state compares the draft with the last loaded snapshot.
5. Apply validates through the existing config contract and persists through
   the model.
6. The runtime restarts only when the changed keys require it.
7. A successful apply refreshes the snapshot and clears dirty state.

Changing destinations never discards edits. Closing a dirty window presents a
standard Save, Discard, or Cancel confirmation.

## Validation And Failure States

- Unsupported controls are hidden or disabled based on the selected TTS
  backend and config contract.
- Invalid custom values show a local field error and block Apply.
- Command failures show the existing redacted output without losing edits.
- Loading state keeps navigation stable and disables only affected commands.
- Empty voice lists provide a direct refresh action rather than a free-form
  fallback field.
- Diagnostics failures remain isolated from ordinary configuration sections.

## Accessibility And Interaction

- Sidebar navigation and every control are keyboard reachable.
- Controls retain explicit accessibility labels and native focus rings.
- Color never carries health or validation meaning alone.
- The layout supports the existing 700-point minimum width without clipping.
- Text uses fixed macOS type styles rather than viewport-scaled font sizes.
- Motion is limited to destination transitions, dirty-state feedback, and
  short success confirmation.

## Visual Direction

Keep the dark graphite base and existing cyan/gold brand accents, but reduce
large tinted surfaces. Use cyan for selection and primary actions, green only
for healthy runtime status, gold for attention or restart impact, and red only
for errors. Corners stay at 8 points or less. The result should feel like a
focused native utility, not a dashboard or marketing page.

## Verification

- Unit tests cover destination metadata, dirty-state behavior, restart
  classification, unsupported control states, and close confirmation logic.
- Existing configuration, setup assistant, diagnostics, and model tests remain
  green.
- Swift debug and release builds succeed.
- Visual QA covers default, dirty, error, loading, and advanced states at the
  minimum window size and a wider desktop size.
- Accessibility inspection confirms labels, focus order, and keyboard
  navigation.
- The packaged app is installed locally and checked for a single running
  instance, correct settings persistence, and runtime restart behavior.

## Scope Boundaries

- No new configuration keys are introduced.
- The quick menu keeps its current purpose and control set.
- Setup Assistant behavior is unchanged.
- No release, merge to `develop`, or merge to `main` occurs as part of the UI
  implementation until the stacked attention PR has landed and this branch has
  been rebased.
