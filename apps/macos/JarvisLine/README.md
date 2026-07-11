# Jarvis Line for macOS

Preview macOS menu bar manager for Jarvis Line.

The app does not replace the CLI. It shells out to the installed `jarvis-line`
command and provides a native control surface for day-to-day management.

## Setup Assistant

The native Setup Assistant uses the same versioned setup engine as the CLI. On
first launch it is offered once only when Jarvis Line has no config. Existing
configured users are not interrupted.

Open it any time from **Settings > Runtime > Run Setup Assistant...**. If setup
is still required, the menu bar quick panel also shows **Complete Setup**.

The assistant guides you through:

1. Full spoken language name
2. Language- and platform-compatible TTS backend
3. Final-only, commentary + final, or disabled speech
4. Codex, Claude, Gemini, or generic agent target
5. Project or global instruction scope
6. One reviewed Apply action

Kokoro download/install requires explicit license consent. Project scope uses a
native folder picker instead of a free-form path. Network work and voice tests
run only when selected and only after Apply. Closing the assistant before Apply
does not change Jarvis Line.

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

The app starts as a regular macOS app with a Dock icon and a status icon in the
macOS menu bar. Look for the waveform icon in the menu bar for the quick panel.
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
- Separate Settings window: controlled presets for speech, speak mode, TTS backend, voice/rate/speed, volume, queue, quiet hours, and a simple GitHub update check interval
- Settings actions stay in a bottom action bar instead of being mixed into the settings form
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

## Packaging Later

The local app bundle is ad-hoc signed. The app remains Preview until a Developer
ID signing and notarization path is available for a smoother public install
experience.
