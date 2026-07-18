<p align="center">
  <img src="apps/macos/JarvisLine/Resources/AppIcon.png" width="144" alt="Jarvis Line app icon">
</p>

<h1 align="center">Jarvis Line</h1>

<p align="center">
  <strong>Voice notifications for AI coding agents, powered by hook-driven TTS.</strong>
</p>

<p align="center">
  Hear short progress, completion, permission, and input-request summaries without watching every agent session.
</p>

<p align="center">
  <a href="https://github.com/reitenji/jarvis-line/releases"><img alt="GitHub release" src="https://img.shields.io/github/v/release/reitenji/jarvis-line?include_prereleases"></a>
  <a href="https://github.com/reitenji/jarvis-line/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/reitenji/jarvis-line/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-31d6c4"></a>
  <a href="https://github.com/reitenji/jarvis-line/wiki"><img alt="Documentation" src="https://img.shields.io/badge/docs-Wiki-7c6cff"></a>
</p>

Jarvis Line watches supported agent events, extracts one short spoken line, and
sends it through a single audio queue to your selected TTS engine. It is built
for long-running coding work where a concise voice update is more useful than
reading an entire transcript.

```text
Jarvis line: The tests are passing and the branch is ready.
```

> **Release status:** `0.5.0` is beta. The macOS CLI/runtime is the primary
> validated surface. The macOS manager app, Windows, and Linux remain Preview.
> See the [support matrix](docs/SUPPORT-MATRIX.md).

## Quick Start

Install the current GitHub release and run the guided setup:

```bash
python3 -m pip install "git+https://github.com/reitenji/jarvis-line.git@v0.5.0"
jarvis-line setup
jarvis-line doctor
jarvis-line tts test --text "Jarvis line test is ready."
```

Setup asks for the spoken language, a compatible TTS backend, speech behavior,
agent target, instruction scope, optional attention alerts, Codex hooks, and a
voice test. It shows a final review before making changes.

Jarvis Line does not edit `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` by default.
Run the instruction command printed by setup, review the block, then paste it
into the project or global instruction file your agent actually reads.

For a non-interactive local default:

```bash
jarvis-line setup --default
```

Read the full [Getting Started guide](https://github.com/reitenji/jarvis-line/wiki/Getting-Started) for language, TTS, agent, and update choices.

## What It Speaks

Jarvis Line has two complementary event paths:

| Event | Example | Source |
|---|---|---|
| Commentary | "The test suite is running." | Explicit agent `Jarvis line:` |
| Final | "The requested change is complete." | Explicit agent `Jarvis line:` |
| Permission | "Permission is needed to push changes." | Codex `PermissionRequest` or explicit protocol event |
| Input required | "Your release choice is required." | Codex `request_user_input` or explicit protocol event |

Attention alerts are opt-in. Entering Plan mode by itself does not speak;
only a user-reviewed permission request or structured question does. Codex
requests handled by its automatic reviewer remain silent. Raw commands, answer
choices, answers, and call IDs are not persisted by the built-in Codex attention
adapters.

See [Attention Alerts](https://github.com/reitenji/jarvis-line/wiki/Attention-Alerts) for behavior and controls.

## Why Jarvis Line

- One audio worker prevents overlapping voices across simultaneous sessions.
- Session-aware queue rules prioritize current requests and discard stale work.
- Kokoro, platform system voices, macOS `say`, and custom TTS commands are supported.
- The event protocol lets other agents and editor extensions use the same runtime.
- Bounded local diagnostics and redacted support reports make issues safer to share.
- CLI setup and the native macOS Setup Assistant use the same config contract.

## Agent Support

| Agent | Current integration |
|---|---|
| Codex | Session watcher, `SessionStart`, `PermissionRequest`, and Plan-question adapter |
| Claude | Generated `CLAUDE.md` instruction plus explicit event protocol |
| Gemini | Generated `GEMINI.md` instruction plus explicit event protocol |
| Other agents | Generated generic instruction or versioned `jarvis-line emit` events |

Other agents can submit a normalized event directly:

```bash
jarvis-line emit \
  --source claude \
  --session session-123 \
  --phase commentary \
  --line "The tests are running."
```

See the [Agent Instructions guide](https://github.com/reitenji/jarvis-line/wiki/Agent-Instructions) and the versioned [event protocol](docs/EVENT-PROTOCOL.md).

## TTS Choices

| Backend | Best fit |
|---|---|
| Kokoro | Recommended local English voice |
| System TTS | Low-friction fallback and OS-managed language voices |
| macOS `say` | Explicit macOS voice and rate control |
| Custom command | Edge TTS, OpenAI TTS, ElevenLabs, local models, or your own API wrapper |

Jarvis Line's bundled Kokoro defaults are English-focused. For another spoken
language, select a matching system voice or configure a compatible custom model.
The generated instruction language and TTS voice language should match.

See [TTS and Voices](https://github.com/reitenji/jarvis-line/wiki/TTS-and-Voices).

## macOS App

The Preview macOS manager adds a menu bar status panel, guided setup, runtime
controls, safe settings, attention-alert controls, diagnostics, and voice tests
while keeping the Python CLI as the core engine.

Public DMGs are currently ad-hoc signed and not Apple-notarized. Build and
packaging details remain in the [macOS app README](apps/macos/JarvisLine/README.md).

## Documentation

Start with the [Jarvis Line Wiki](https://github.com/reitenji/jarvis-line/wiki):

| Guide | Use it for |
|---|---|
| [Getting Started](https://github.com/reitenji/jarvis-line/wiki/Getting-Started) | Installation and first setup |
| [Attention Alerts](https://github.com/reitenji/jarvis-line/wiki/Attention-Alerts) | Permission and input-request speech |
| [Agent Instructions](https://github.com/reitenji/jarvis-line/wiki/Agent-Instructions) | `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` |
| [TTS and Voices](https://github.com/reitenji/jarvis-line/wiki/TTS-and-Voices) | Kokoro, system voices, languages, and custom TTS |
| [Configuration](https://github.com/reitenji/jarvis-line/wiki/Configuration) | Common settings and profiles |
| [CLI Reference](https://github.com/reitenji/jarvis-line/wiki/CLI-Reference) | Command map and common examples |
| [Troubleshooting](https://github.com/reitenji/jarvis-line/wiki/Troubleshooting) | No speech, queue, hook, and support-report checks |
| [macOS App](https://github.com/reitenji/jarvis-line/wiki/macOS-App) | Native manager setup and distribution |
| [Platform and Agent Support](https://github.com/reitenji/jarvis-line/wiki/Platform-and-Agent-Support) | Validated and Preview surfaces |

Version-sensitive technical references stay in the repository:

- [Command examples](docs/COMMANDS.md)
- [Configuration contract](docs/CONFIGURATION.md)
- [Event protocol](docs/EVENT-PROTOCOL.md)
- [Privacy](PRIVACY.md)
- [Security policy](SECURITY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Help And Community

Run this first when speech is not behaving as expected:

```bash
jarvis-line doctor
```

For a reproducible issue, generate a redacted report, review it, and paste only
the useful sections into the issue form:

```bash
jarvis-line support-report --output ./jarvis-line-issue.md
```

- Ask setup questions in [Q&A Discussions](https://github.com/reitenji/jarvis-line/discussions/categories/q-a).
- Propose features in [Ideas](https://github.com/reitenji/jarvis-line/discussions/categories/ideas).
- Report defects with the [bug report form](https://github.com/reitenji/jarvis-line/issues/new?template=bug_report.yml).
- Report vulnerabilities privately through [GitHub Security Advisories](https://github.com/reitenji/jarvis-line/security/advisories/new).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Changes
flow through `feature/*` or `fix/*` into `develop`, then from `develop` to
`main` for a tagged release.

Jarvis Line is available under the [MIT License](LICENSE).
