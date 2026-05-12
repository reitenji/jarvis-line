# Changelog

## 0.1.0b6

- Added `jarvis-line update apply` for one-command update checks and installs.
- Made git-based updates default to the public GitHub repository and the latest release tag.
- Kept `jarvis-line update check` read-only while giving users a simpler update path.

## 0.1.0b5

- Fixed git-based `jarvis-line update check` so GitHub tag installs can check the latest release without relying on PyPI.
- Added `jarvis-line update check --source git --repo ...` support.
- Updated update command documentation for GitHub tag-based installs.

## 0.1.0b4

- Made `init` agent-agnostic by default and added explicit `--codex` hook setup.
- Changed instruction setup to print reviewed Markdown instead of editing instruction files by default.
- Moved Kokoro runtime/model defaults from `.codex` to `.jarvis-line`.
- Replaced zip support bundles with reviewed Markdown support reports.
- Split detailed command, TTS, config, and instruction documentation into focused `docs/` references.
- Added full-language instruction names such as `"English"` and `"Turkish"` instead of short language codes.

## 0.1.0b3

- Added product-friendly top-level CLI help and a `jarvis-line help` command.
- Documented local dogfood timing observations for Kokoro and system TTS.

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
