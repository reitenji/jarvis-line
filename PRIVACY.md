# Privacy

Last updated: July 10, 2026

Jarvis Line is a local developer tool. It does not require an account and the
core project does not include analytics, advertising, crash-reporting, or
telemetry SDKs.

## What Jarvis Line Reads

For Codex integration, the watcher reads session output under
`~/.codex/sessions` so it can find explicit `Jarvis line: ...` status lines.
It does not need to send session transcripts to the Jarvis Line project or its
maintainers.

When optional attention alerts are enabled, the Codex `PermissionRequest` hook
reads the bounded tool name and input needed for local intent classification.
The session watcher recognizes exact structured `request_user_input` calls and
uses only the first question's bounded header and question. Raw tool arguments,
question options, user answers, and call IDs are not retained.

Other agent integrations can submit a short normalized event with
`jarvis-line emit`. Those adapters control what text they provide.

## What Jarvis Line Stores Locally

Jarvis Line keeps runtime data on your machine:

| Location | Contents |
|---|---|
| `~/.codex/hooks/jarvis_line_config.json` | Active configuration, including the selected TTS backend |
| `~/.codex/hooks/jarvis_line_audio_queue.json` | Pending short spoken lines |
| `~/.codex/hooks/jarvis_line_latest_messages.json` | Latest-message cache used to avoid rescanning long sessions |
| `~/.codex/hooks/.jarvis_line_state.json` | Runtime process state |
| `~/.codex/hooks/jarvis_line_trace.jsonl` | Bounded lifecycle events and timing metadata |
| `~/.codex/hooks/*.log` | Watcher and audio-worker diagnostics |
| `~/.jarvis-line/tts` | Optional local Kokoro environment, model files, and temporary audio |

Queue and cache files can contain the short line that will be spoken. Normal
logs avoid full content, but enabling `debug_content_logging` can write spoken
text to local logs. Leave that option disabled unless you are actively
diagnosing a problem.

Attention queue entries contain the safe spoken line, event type, expiry time,
and optionally a short one-way correlation token used to cancel an already
answered request. They do not contain the original Codex request or answer.

Temporary Kokoro audio is deleted after playback by default. A crash or forced
shutdown can leave temporary files behind under `~/.jarvis-line/tts/generated`.

## Network Activity

Jarvis Line's watcher, queue, and system/Kokoro speech paths run locally. The
following actions can use the network:

- Update checks contact the configured GitHub repository or PyPI endpoint.
- `jarvis-line update apply` installs from the update source you configured.
- `jarvis-line kokoro install-deps` asks `pip` to install optional packages.
- `jarvis-line kokoro download --accept-license` downloads the pinned official
  Kokoro model release from GitHub and verifies its size and SHA-256 before use.
- A custom command or API-backed TTS wrapper can send the spoken line to its
  provider. Review that command and the provider's privacy terms before using
  it.

Jarvis Line does not add network transmission to a custom TTS command; the
command you configure defines that behavior. API keys should be supplied by
the wrapper's environment or credential store, not embedded in spoken lines or
public support reports.

## Support Reports

`jarvis-line support-report` creates a redacted Markdown report on your machine.
It masks common secret patterns and shortens content, but automated redaction
cannot guarantee that every private value is recognized. Always open and review
the report before pasting any part of it into a public GitHub issue. Jarvis Line
does not upload the report for you.

## Your Controls

- Pause speech with `jarvis-line config set speech_enabled false`.
- Disable attention only with `jarvis-line config set attention_enabled false`.
- Stop local processes with `jarvis-line stop`.
- Clear pending lines with `jarvis-line queue clear`.
- Clear lifecycle diagnostics with `jarvis-line trace --clear`.
- Remove the Codex hook with `jarvis-line uninstall codex`.
- Delete local Jarvis Line runtime files manually after stopping the service if
  you want to remove retained configuration, logs, models, and queues.

Package uninstallers do not delete user configuration or downloaded model files
automatically. This preserves settings across upgrades and prevents accidental
deletion of large or custom assets.

## Security Reports

Report privacy or security vulnerabilities through GitHub's
[private vulnerability reporting form](https://github.com/reitenji/jarvis-line/security/advisories/new),
not a public issue. See [SECURITY.md](SECURITY.md) for the disclosure policy.
