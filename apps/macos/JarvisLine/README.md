# Jarvis Line for macOS

Preview macOS menu bar manager for Jarvis Line.

The app does not replace the CLI. It shells out to the installed `jarvis-line`
command and provides a native control surface for day-to-day management.

## Setup Assistant

The native Setup Assistant uses the same versioned setup engine as the CLI. On
first launch it is offered once only when Jarvis Line has no config. Existing
configured users are not interrupted.

Open it any time from **Settings > General > Open Setup Assistant**. If setup
is still required, the menu bar quick panel also shows **Complete Setup**.

The assistant guides you through:

1. Full spoken language name
2. Language- and platform-compatible TTS backend
3. Final-only, commentary + final, or disabled speech
4. Optional attention alerts for permissions and input requests
5. Codex, Claude, Gemini, or generic agent target
6. Project or global instruction scope
7. One reviewed Apply action

Kokoro download/install requires explicit license consent. Project scope uses a
native folder picker instead of a free-form path. Network work and voice tests
run only when selected and only after Apply. Closing the assistant before Apply
does not change Jarvis Line.

The generic agent target is the default. Codex hook installation starts off and
must be enabled separately after choosing Codex. The assistant never receives or
displays custom-command secrets; it can only select a custom backend that was
already configured through the advanced CLI path.

Native CLI calls are bounded so a stalled subprocess cannot lock the assistant
indefinitely. Regular calls time out after 60 seconds; the reviewed setup Apply
flow allows up to 15 minutes for an approved Kokoro download/install. App-owned
CLI work runs in an isolated process group, so timeout cleanup terminates its
installer descendants before returning to Review with a retryable error.

The Setup Assistant never edits agent Markdown. When setup completes, use
**Copy Instructions**, review the generated block, and paste it into the chosen
`AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` yourself.

## Run

```bash
cd apps/macos/JarvisLine
swift run JarvisLine
```

## Build a Clickable App

```bash
cd apps/macos/JarvisLine
./scripts/package-app.sh
open "dist/Jarvis Line.app"
```

The app starts with a Dock icon and a status icon in the macOS menu bar. Disable
**Show in Dock** under **Settings > General** for a menu-bar-only workflow; the
change takes effect immediately. Look for the waveform icon in the menu bar for the quick panel.
The quick panel stays focused on runtime status and frequent actions; use the
Settings button, the app menu, or Command+, to open the full configuration
window. The app menu is intentionally minimal so Jarvis Line does not expose
unused File/Edit/View/Window/Help menus.

The local bundle uses the selected Variant 6 icon.

## Build a DMG

```bash
cd apps/macos/JarvisLine
./scripts/package-dmg.sh
open "dist/JarvisLine-macOS.dmg"
```

The DMG contains `Jarvis Line.app` and an `Applications` shortcut. The local DMG
is ad-hoc signed but not notarized, so macOS may show a Gatekeeper warning
outside development machines.

When installing a newer build, drag `Jarvis Line.app` onto the Applications
shortcut and choose Replace if Finder asks. The app uses a stable bundle
identifier and a single-instance guard, so launching a newer Applications copy
will close older running copies from build or DMG staging folders.

## Current MVP

- Runtime status: watcher, audio worker, queue, TTS, speak mode
- Visible app and CLI version in the header
- Controls: start, stop, restart, repair, test voice
- Regular Dock and minimal app-menu behavior while keeping the menu bar status icon
- Two-pane Settings window with General, Speech, Voice, Updates, Diagnostics, and Advanced destinations
- Controlled presets for speech, attention alerts, speak mode, TTS backend, voice/rate/speed, volume, queue, quiet hours, and GitHub update checks
- Apply and Revert appear in the window toolbar only while the draft differs from the saved config; runtime-impacting changes are marked and restart automatically when applied
- Closing a modified Settings window asks whether to Apply, Discard, or Cancel without losing the draft on command failure
- Quick access: config file, watcher log, audio worker log
- Hook install appears only when the Codex hook is not already installed
- Custom dark Jarvis Line theme derived from the app icon palette
- A detailed high-resolution alpha app icon for Finder, Dock, and packaged DMG installs
- A separate detailed brand mark inside the app panel
- Native menu bar status icon so running and queued states stay easy to read
- Native guided Setup Assistant with first-run detection and Settings relaunch

The Settings window edits common config values without requiring users to open
the JSON file. Unknown/custom config keys are preserved on save. The app favors
pickers and presets over free text, then blocks invalid combinations before
writing config. Update settings are intentionally simple in the app: Jarvis Line
checks the official GitHub release source on the selected interval.

## Storage & Cleanup

Open **Settings > Diagnostics > Storage & Cleanup** to see the read-only
reclaimable-file estimate and last successful cleanup. **Refresh** runs
`jarvis-line cleanup status --json`; **Clean Now** runs
`jarvis-line cleanup run --json` and refreshes the preview. The button is
unavailable while another app action is running.

Use the Automatic cleanup switch and Daily or Weekly picker to change the
shared `cleanup_enabled` and `cleanup_interval_hours` settings. They follow the
existing staged Settings Apply/Revert flow and do not restart the watcher.
Cleanup never shows filesystem paths in the app. See the repository
[command reference](../../../docs/COMMANDS.md#cleanup) and
[configuration guide](../../../docs/CONFIGURATION.md#storage-cleanup) for the
allowlist, retention windows, and CLI behavior.

## Packaging Later

The local app bundle is ad-hoc signed. The app remains Preview until a Developer
ID signing and notarization path is available for a smoother public install
experience.
