<p align="center">
  <img src="apps/macos/JarvisLine/Resources/AppIcon.png" width="144" alt="Jarvis Line app icon">
</p>

<h1 align="center">Jarvis Line</h1>

<p align="center">
  <strong>Voice notifications for AI coding agents, powered by hook-driven TTS.</strong>
</p>

<p align="center">
  Hear concise progress, completion, permission, and input-request updates without watching every agent session.
</p>

<p align="center">
  <a href="https://github.com/reitenji/jarvis-line/releases"><img alt="GitHub release" src="https://img.shields.io/github/v/release/reitenji/jarvis-line?include_prereleases"></a>
  <a href="https://github.com/reitenji/jarvis-line/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/reitenji/jarvis-line/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-31d6c4"></a>
  <a href="https://github.com/reitenji/jarvis-line/wiki"><img alt="Documentation" src="https://img.shields.io/badge/docs-Wiki-7c6cff"></a>
</p>

Jarvis Line turns supported agent events into one short spoken status line and
routes it through a single, session-aware audio queue.

```text
Jarvis line: The tests are passing and the branch is ready.
```

> **Release status:** `0.7.0` is beta. The macOS CLI/runtime is the primary
> validated surface. The macOS app, Windows, and Linux are Preview.
> See [platform support](https://github.com/reitenji/jarvis-line/wiki/Platform-and-Agent-Support).

## Quick Start

```bash
python3 -m pip install "git+https://github.com/reitenji/jarvis-line.git@v0.7.0"
jarvis-line setup
jarvis-line doctor
jarvis-line tts test --text "Jarvis line test is ready."
```

The setup assistant configures language, TTS, agent hooks, and optional
attention alerts. It does not edit agent instruction files automatically;
review the generated block and paste it into the project or global file your
agent reads.

Use `jarvis-line setup --default` for non-interactive local defaults.

For installation choices and the first real session, follow
[Getting Started](https://github.com/reitenji/jarvis-line/wiki/Getting-Started).

## What You Get

- Short spoken updates for commentary, completion, permission, and input requests.
- One audio worker across sessions, with stale-job and overlap protection.
- Kokoro, system voices, macOS `say`, and custom TTS command support.
- Codex integration plus generated instructions for Claude, Gemini, and other agents.
- A Preview macOS manager with guided setup, voice controls, updates, and a privacy-safe Reliability Center.

```text
Agent event -> Jarvis Line hook -> session-aware queue -> selected TTS
```

Attention alerts are opt-in and cover permission requests plus structured
`request_user_input` questions. Requests handled by Codex's automatic reviewer
remain silent. Jarvis Line keeps these messages short and avoids persisting raw
commands, answers, or tool payloads.

## macOS App

The optional native manager provides a menu bar status panel and guided settings
while the Python CLI remains the core runtime. Public DMGs are currently
ad-hoc signed and are not Apple-notarized.

See the [macOS App guide](https://github.com/reitenji/jarvis-line/wiki/macOS-App)
for installation and current limitations.

## Documentation

- [Getting Started](https://github.com/reitenji/jarvis-line/wiki/Getting-Started)
- [Agent Instructions](https://github.com/reitenji/jarvis-line/wiki/Agent-Instructions)
- [TTS and Voices](https://github.com/reitenji/jarvis-line/wiki/TTS-and-Voices)
- [Attention Alerts](https://github.com/reitenji/jarvis-line/wiki/Attention-Alerts)
- [Configuration](https://github.com/reitenji/jarvis-line/wiki/Configuration)
- [CLI Reference](https://github.com/reitenji/jarvis-line/wiki/CLI-Reference)
- [Troubleshooting](https://github.com/reitenji/jarvis-line/wiki/Troubleshooting)

Version-sensitive references remain in the repository:
[commands](docs/COMMANDS.md), [configuration contract](docs/CONFIGURATION.md),
[event protocol](docs/EVENT-PROTOCOL.md), [privacy](PRIVACY.md), and
[security](SECURITY.md).

## Help And Contributing

Run `jarvis-line doctor` first when speech is not behaving as expected. Use
[Discussions](https://github.com/reitenji/jarvis-line/discussions) for questions
and ideas, or open a [bug report](https://github.com/reitenji/jarvis-line/issues/new?template=bug_report.yml)
with the relevant, reviewed sections of a redacted support report.

Contributions flow from `feature/*` or `fix/*` into `develop`, then from
`develop` to `main`. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR.

Jarvis Line is available under the [MIT License](LICENSE).
