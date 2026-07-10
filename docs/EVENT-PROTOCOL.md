# Agent Event Protocol

Jarvis Line accepts a small versioned event so any agent, editor extension, or hook can use the same queue and TTS runtime without imitating Codex session files.

## Direct Command

```bash
jarvis-line emit \
  --source claude \
  --session "session-123" \
  --phase commentary \
  --line "The test suite is running."
```

```text
Queued Jarvis Line event for claude.
```

Use `--phase final` for the completion line. `final_answer`, `final_response`, and `final-response` are normalized to `final` by the protocol.

## JSON On Standard Input

```bash
printf '%s' '{"version":1,"source":"gemini","session_id":"session-123","phase":"final","line":"The implementation is complete."}' \
  | jarvis-line emit --stdin
```

The event shape is:

```json
{
  "version": 1,
  "source": "custom-agent",
  "session_id": "stable-session-id",
  "phase": "commentary",
  "line": "One short spoken status.",
  "text": "Optional longer local context."
}
```

Required fields:

| Field | Meaning |
|---|---|
| `version` | Protocol version. The current value is `1`. |
| `source` | Adapter or agent name, such as `codex`, `claude`, or `gemini`. |
| `session_id` | Stable identifier supplied by that source. |
| `phase` | `commentary` or `final`. |
| `line` | Short text that should be spoken. |

`text` is optional and remains local. It can give the latest-message cache additional context, but it is never written to the privacy-safe trace.

## Adapter Contract

An adapter only needs to:

1. Observe an assistant commentary or final event.
2. Extract the explicit short spoken line.
3. Supply a stable source/session pair.
4. invoke `jarvis-line emit` with arguments or one JSON object on stdin.

Jarvis Line then applies quiet hours, speech mode, duplicate suppression, final-safe queueing, single-worker playback, fallback TTS, and diagnostics. A valid event returns exit code `0` even when runtime policy intentionally skips playback. Invalid input returns exit code `2` and is not queued.

## Limits And Privacy

- Source and session identifiers are limited to 128 characters and reject control characters.
- Spoken lines are limited to 4,096 input characters before normal Jarvis Line trimming.
- Standard-input payloads are limited to 64 KiB.
- Structured diagnostics hash the source/session key and omit `line`, `text`, and transcript content.
- The existing Codex watcher remains available as a compatibility adapter.
