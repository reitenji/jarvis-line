# Support Matrix

Jarvis Line is currently beta software. This page separates code that is
regularly exercised from integrations that are available as Preview.

## Status Definitions

- **Validated beta**: exercised in CI and in real local use; still subject to
  pre-1.0 change.
- **Preview**: implemented and kept buildable, but real-world platform or
  provider coverage is still limited.
- **Protocol**: Jarvis Line defines and tests the integration boundary; a
  provider-specific adapter may still be supplied by the user or community.

## Platforms

| Platform surface | Status | Current evidence and limits |
|---|---|---|
| macOS CLI, watcher, queue, and Codex hooks | Validated beta | CI plus regular local Codex sessions on Apple silicon; opt-in attention hook latency is benchmarked locally before release |
| macOS system TTS and Kokoro playback | Validated beta | Tested locally; available voices and audio-device behavior still depend on the Mac |
| macOS manager app | Preview | Swift tests and DMG smoke checks run in CI; the public DMG is ad-hoc signed and not notarized |
| Windows CLI, watcher, and queue | Preview | Python 3.10/3.12 CI and clean-install checks; not yet validated in sustained real Windows sessions |
| Windows system TTS | Preview | PowerShell integration is implemented, but playback is not exercised in CI and still needs real-device reports |
| Linux CLI, watcher, and queue | Preview | Python 3.10/3.12 CI and clean-install checks; distribution-specific runtime coverage is limited |
| Linux system TTS | Preview | Supports `spd-say`, `espeak-ng`, or `espeak`; playback is not exercised in CI, and availability/voice quality depend on the host |

## Agent Integrations

| Integration | Status | Notes |
|---|---|---|
| Codex | Validated beta | Session watcher, `SessionStart`, and official `PermissionRequest` hook integration are included; Plan-mode `request_user_input` uses a fail-soft session compatibility adapter |
| Claude | Protocol | Instruction template and explicit commentary, final, and attention `jarvis-line emit` events are available; no bundled native hook adapter yet |
| Gemini | Protocol | Instruction template and explicit commentary, final, and attention `jarvis-line emit` events are available; no bundled native hook adapter yet |
| Other agents and editors | Protocol | Submit versioned events described in [EVENT-PROTOCOL.md](EVENT-PROTOCOL.md) |

## TTS Backends

| Backend | Status | Notes |
|---|---|---|
| Kokoro ONNX English defaults | Validated beta on macOS | Model files are downloaded separately and can be verified against pinned official metadata |
| Platform system TTS | Validated beta on macOS; Preview on Windows/Linux | Voice selection and quality are controlled by the operating system |
| macOS `say` preset | Validated beta | Intended for users who want explicit `say` voice/rate controls |
| Custom command/API wrapper | Protocol | Command execution is tested; provider behavior, privacy, credentials, and output formats remain the user's responsibility |
| Non-English custom Kokoro models | Preview | Users must provide mutually compatible model, voices, language, and phonemizer support |

## Before 1.0

The project is moving toward 1.0 without claiming that level of stability yet.
The remaining evidence should include sustained clean installs and upgrades,
more Windows/Linux real-device reports, a notarized macOS distribution path,
and a period without high-impact queue or watcher regressions.

Please open a reviewed support report when you find a platform-specific rough
edge. See [the issue guide](../README.md#help-and-community) and feel free to
open an issue when the behavior is reproducible.
