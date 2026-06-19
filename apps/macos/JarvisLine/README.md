# Jarvis Line for macOS

Experimental macOS menu bar manager for Jarvis Line.

The app does not replace the CLI. It shells out to the installed `jarvis-line`
command and provides a native control surface for day-to-day management.

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

The app is a menu bar utility, so it does not open a normal window. Look for the
waveform icon in the macOS menu bar.

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

## Current MVP

- Runtime status: watcher, audio worker, queue, TTS, speak mode
- Controls: start, stop, restart, repair, test voice
- Quick access: config, watcher log, audio worker log
- Hook install/repair through `jarvis-line install codex`

## Packaging Later

The local app bundle is ad-hoc signed. The next release step is Developer ID
signing and notarization for a smoother public install experience.
