# Agent Event Protocol

Jarvis Line accepts a small versioned event so any agent, editor extension, or
hook can use the same queue and TTS runtime without imitating Codex session
files. Protocol version `1` supports status and opt-in attention events.

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

Submit an attention event with an explicit type:

```bash
jarvis-line emit \
  --source claude \
  --session "session-123" \
  --phase attention \
  --attention-type input_required \
  --line "Your deployment choice is required."
```

```text
Queued Jarvis Line event for claude.
```

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
  "attention_type": null,
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
| `phase` | `commentary`, `final`, or `attention`. |
| `line` | Short text that should be spoken. |

`attention_type` is required only when `phase` is `attention`. Supported values:

| Type | Meaning |
|---|---|
| `permission_request` | An operation needs the user's approval. |
| `input_required` | The agent needs an answer or choice before continuing. |

`text` is optional for commentary and final events and remains local. It can
give the latest-message cache additional context, but it is never written to
the privacy-safe trace. Attention events discard `text` and retain only the
explicit bounded `line` needed for playback.

## Adapter Contract

An adapter only needs to:

1. Observe an assistant commentary, final, permission, or input-required event.
2. Produce one explicit short spoken line.
3. Supply a stable source/session pair.
4. Invoke `jarvis-line emit` with arguments or one JSON object on stdin.

Jarvis Line then applies quiet hours, speech mode, duplicate suppression, final-safe queueing, single-worker playback, fallback TTS, and diagnostics. A valid event returns exit code `0` even when runtime policy intentionally skips playback. Invalid input returns exit code `2` and is not queued.

Attention events also require `attention_enabled = true`. They expire after 30
seconds, take priority over queued final/commentary speech, and never interrupt
audio that is already playing. A final event removes older queued work from the
same session.

## Codex Automatic Adapters

The bundled Codex installer adds `SessionStart` and the official
`PermissionRequest` hook. The permission hook classifies a bounded request
locally and never approves or denies it.

A normal Plan-mode question is different: Codex records it as a structured
`request_user_input` function call rather than a lifecycle hook. The existing
session watcher recognizes that exact shape, uses only the first bounded
`header` and `question`, and emits `input_required`. When the matching result is
observed before playback, the queued alert is cancelled. Entering Plan mode by
itself is not an attention event.

This Plan-mode parser is a fail-soft compatibility adapter over the observed
session format. If Codex changes the shape, the question alert may be skipped;
permission hooks and ordinary commentary/final speech continue to work.
Claude, Gemini, and other agents require explicit protocol events in this
release.

## Limits And Privacy

- Source and session identifiers are limited to 128 characters and reject control characters.
- Spoken lines are limited to 4,096 input characters before normal Jarvis Line trimming.
- Standard-input payloads are limited to 64 KiB.
- Structured diagnostics hash the source/session key and omit `line`, `text`, and transcript content.
- Codex raw tool arguments, question options, answers, and call IDs are not persisted.
- A one-way correlation token may be retained briefly to cancel an answered input request.
- Third-party adapters are responsible for ensuring their explicit `line` is safe to speak.
- The existing Codex watcher remains available as a compatibility adapter.
