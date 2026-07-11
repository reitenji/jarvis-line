# Changelog

## Unreleased

## 0.5.0 - 2026-07-11

- Add a reviewed interactive `jarvis-line setup` wizard with controlled language, TTS, speech, agent, scope, hook, runtime, and voice-test choices.
- Add versioned and 64 KiB-bounded `setup inspect --json` and `setup apply --stdin --json` contracts for native apps and automation.
- Validate language, platform, backend readiness, explicit Kokoro license acceptance, and preconfigured custom-command selection before any setup mutation or network work.
- Redact command secrets and local paths from setup inspection, and reject new custom commands from the native/automation bridge.
- Add a native macOS Setup Assistant with one-time first-run offering, Settings relaunch, explicit Kokoro consent, project-folder selection, manual instruction copy, and bounded process-group cleanup.
- Keep agent Markdown files user-owned; guided setup generates instructions but never writes `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`.
- Add Python 3.11 compatibility coverage for the expanded CLI setup surface.

## 0.4.0 - 2026-07-10

- Add contributor, conduct, security, pull request, and community guidance.
- Replace the obsolete ZIP support-bundle issue flow with reviewed Markdown support reports and Discussion routing.
- Mark the project as beta and publish explicit Preview boundaries for the macOS app, Windows, Linux, and agent/provider adapters.
- Document local data, network behavior, third-party model licensing, and safe support-report review in a dedicated privacy policy.
- Add pinned and atomic Kokoro model downloads with explicit license acceptance and SHA-256 verification.
- Pin GitHub Actions to reviewed commit SHAs, audit optional Python dependencies, configure Dependabot, and attach an SPDX SBOM to releases.
- Verify built wheels through isolated install, CLI smoke, uninstall, and residue checks on macOS, Linux, and Windows CI.

## 0.3.1

- Record queued lifecycle metadata before launching the audio worker so traces stay in causal order.
- Update GitHub artifact actions to their current Node 24-based major versions.

## 0.3.0

- Drain pending audio jobs before an RSS-triggered worker exit to avoid repeated Kokoro reloads during bursts.
- Preserve final messages when trimming the queue and rotate playback fairly across active sessions.
- Add a bounded privacy-safe lifecycle trace and `jarvis-line trace` command.
- Remove spoken text and absolute session paths from default runtime logs.
- Add the versioned `jarvis-line emit` protocol for Codex, Claude, Gemini, and custom adapters.
- Establish a canonical config contract shared by the Python CLI and macOS settings app.
- Add native runtime diagnostics, Swift tests, app/DMG smoke checks, checksums, and tag artifact automation.
- Add a macOS Dock visibility setting and preserve the preference across launches.
- Fix first-save config defaults and macOS voice/rate round-tripping in the manager app.
- Require release tags to originate from `main` and verify Python and native artifacts before publishing.

## 0.1.0b8

- Fixed Jarvis Line speech with newer Codex session history entries where assistant output can appear inside Codex agent history payloads.
- Added direct notify payload handling for final `Jarvis line` messages so speech is less dependent on session file scanning.

## 0.1.0b7

- Redacted secret-like values from support reports before they are pasted into issues.
- Hardened support report Markdown fences against log content that contains backticks.
- Prevented git option injection in update checks and installs.
- Kept `jarvis-line update apply` on the latest tag by default while still allowing explicit `--ref` installs.

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
