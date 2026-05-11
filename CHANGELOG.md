# Changelog

## 0.1.0b2

- Fixed Windows CI syntax checks by replacing shell glob expansion with `compileall`.
- Fixed smoke/unit path assertions so they are platform independent.
- Updated GitHub Actions to Node 24-compatible action versions.

## 0.1.0b1

- Added session watcher, latest-message cache, audio queue, and single audio worker.
- Added Kokoro live streaming with tempfile fallback.
- Added macOS, Linux, and Windows tempfile playback fallbacks.
- Added configurable TTS presets: Kokoro, system TTS, macOS, and custom command.
- Added Kokoro status, dependency install, and config commands.
- Added CLI commands for setup, doctor, status, config, install, uninstall, and migration.
- Added config defaults/schema inspection commands.
- Added config profiles, prefix helpers, and additional customization settings.
- Added runtime start/stop/restart, queue, log tail, and doctor JSON commands.
- Added update check/install/configure commands, git update installs, and doctor update notices.
- Added fallback TTS plus custom command retry/env/cwd settings.
- Added instruction replace, doctor, and style options.
- Added clearer CLI next-step guidance.
- Added installable instructions for Codex, Claude, and Gemini-style agent files.
- Added redacted support bundles for issue reports.
- Added a GitHub bug report template that requests support bundles.
- Added smoke tests and pytest-style unit tests.
