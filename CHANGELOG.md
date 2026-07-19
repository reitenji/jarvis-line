# Changelog

## Unreleased

## 0.8.0 - 2026-07-19

- Add a versioned privacy-safe reliability snapshot and three bounded recovery actions for runtime restart, expired-job pruning, and a fixed TTS test.
- Replace broad macOS Diagnostics controls with a status-first Reliability Center showing runtime health, queue state, safe recent-delivery outcomes, and recommended recovery.
- Add deterministic quick and extended fake-speech soak modes covering multi-session queue pressure, expiry, deduplication, cancellation, recovery, locks, trace rotation, and runtime resource limits.
- Run quick soak across macOS, Windows, and Linux pull-request CI, with scheduled/manual extended reports that contain aggregate metadata only.

## 0.7.0 - 2026-07-18

- Add bounded cleanup for generated audio, recognized temporary artifacts, rotated logs, and stale locks whose owners are proven dead.
- Schedule cleanup from the existing watcher without adding a daemon, timer, thread, or persistent worker.
- Add `jarvis-line cleanup status` and `jarvis-line cleanup run` with human-readable and JSON reports.
- Add macOS Diagnostics controls for automatic cleanup, daily or weekly frequency, storage status, and Clean Now.
- Harden cleanup across macOS, Windows, and Linux against symlinks, path replacement, concurrent mutation, lock races, and inherited Windows handles.
- Preserve configuration, models, voices, active runtime files, custom paths, and unknown user content by default.

## 0.6.0 - 2026-07-18

- Add opt-in, content-aware attention alerts for Codex permission requests and Plan-mode questions.
- Keep Codex permission alerts silent when the effective reviewer is automatic, while preserving alerts routed to the user.
- Extend the versioned event protocol with `attention`, `permission_request`, and `input_required` events for third-party adapters.
- Prioritize short-lived attention jobs without interrupting active playback, isolate them by session, and cancel answered Plan-mode prompts before playback when possible.
- Keep raw tool input, answer choices, answers, and call IDs out of queue metadata, diagnostics, and support output.
- Add shared CLI/setup configuration and a controlled macOS `Attention alerts` toggle while leaving existing configurations disabled by default.
- Migrate installed Codex integrations from the deprecated `codex_hooks` feature flag to `hooks` through the Codex CLI.
- Improve Turkish, French, and Italian attention phrasing and avoid duplicate terminal punctuation.
- Redesign the Preview macOS Settings window around General, Speech, Voice, Updates, Diagnostics, and Advanced destinations.
- Add draft-aware Apply, Apply & Restart, Revert, and close-confirmation flows that preserve failed edits safely.
- Constrain backend-specific voice controls and improve update status, queue diagnostics, accessibility, and Dock visibility handling.
- Simplify the project README and route detailed setup, TTS, agent, and troubleshooting guidance to the Wiki.

## 0.5.0 - 2026-07-11

- Add a reviewed interactive `jarvis-line setup` wizard with controlled language, TTS, speech, agent, scope, hook, runtime, and voice-test choices.
- Add versioned and 64 KiB-bounded `setup inspect --json` and `setup apply --stdin --json` contracts for native apps and automation.
- Validate language, platform, backend readiness, explicit Kokoro license acceptance, and preconfigured custom-command selection before any setup mutation or network work.
- Redact command secrets and local paths from setup inspection, and reject new custom commands from the native/automation bridge.
- Add a native macOS Setup Assistant with one-time first-run offering, Settings relaunch, explicit Kokoro consent, project-folder selection, manual instruction copy, and bounded process-group cleanup.
- Retry DMG verification only when macOS reports temporary resource contention, while preserving hard failures for invalid images.
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
