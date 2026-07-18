# Attention Events Design

## Summary

Jarvis Line will add an optional Attention Events layer for moments when an
agent requires immediate user action. Existing agent-authored commentary and
final summaries remain unchanged. Attention Events share the existing
single-worker queue and TTS backends, but receive higher scheduling priority.

The automatic Codex integration targets both official `PermissionRequest`
hooks and structured `request_user_input` calls already observed by the
session watcher. Other agents can submit `input_required` events through the
public event protocol. Spoken attention messages are generated locally from
safe request metadata; the feature does not add an LLM, cloud request, or
continuously resident model.

## Goals

- Speak a useful, request-specific alert when Codex asks for permission.
- Keep attention events isolated by stable `source + session_id` identity.
- Preserve one-at-a-time playback across every session and event type.
- Avoid repetitive generic alerts when safe request intent can be determined.
- Avoid speaking or logging raw commands, arguments, file contents, or secrets.
- Add no persistent process beyond the existing watcher and audio worker.
- Keep existing installs quiet until the user explicitly enables attention.

## Non-Goals

- Replacing agent-authored `Jarvis line:` commentary or final summaries.
- Using an LLM to compose attention messages.
- Narrating every lifecycle event, tool call, error, or context change.
- Automatically detecting Claude or Gemini permission prompts in this release.
- Interrupting audio that is already playing.
- Speaking full shell commands, paths, prompts, or tool payloads.
- Adding arbitrary formatter code fields to the macOS settings UI.

## User Experience

When attention alerts are enabled, a Codex approval request produces a short
line that describes the safe intent of the request:

```text
npm install
-> Permission is needed to install project dependencies.

git push origin develop
-> Permission is needed to push changes to the remote repository.

curl https://api.example.com/v1/items?token=...
-> Permission is needed to connect to api.example.com.

rm -rf build
-> Permission is needed to delete files.

apply_patch
-> Permission is needed to modify project files.

mcp__github__create_pull_request
-> Permission is needed to create a GitHub pull request.
```

If Jarvis Line cannot determine a safe intent, it falls back to the canonical
tool name without including its arguments:

```text
Permission is required for Bash.
```

The feature is controlled by one `Attention alerts` toggle in the setup flow
and macOS manager. Existing configurations that do not contain the new setting
resolve it as disabled. A new guided setup recommends enabling it when Codex is
selected, but still requires user confirmation before changing configuration or
installing the hook.

## Supported Events

The first release supports two event types:

| Event | Source | Behavior |
|---|---|---|
| `permission_request` | Automatic Codex hook | Locally formats a safe request-specific line. |
| `input_required` | Automatic Codex session adapter or public adapter protocol | Locally summarizes a Codex question or speaks the adapter-provided short line. |

Rate limits, API failures, compaction, context overflow, session greetings, and
general tool failures are deliberately excluded. They can be evaluated later
using real-world noise and latency evidence.

## Event Contract

Protocol version `1` remains valid. The allowed phase set expands from
`commentary | final` to `commentary | final | attention`. Existing payloads are
unchanged.

An attention payload has this shape:

```json
{
  "version": 1,
  "source": "codex",
  "session_id": "stable-session-id",
  "phase": "attention",
  "attention_type": "permission_request",
  "line": "Permission is needed to install project dependencies."
}
```

Rules:

- `attention_type` is required when `phase` is `attention` and rejected for
  unsupported values.
- `line` remains required. The Codex adapter formats the line before creating a
  normalized event; third-party adapters remain responsible for their line.
- Public events do not accept arbitrary `tool_input` or command payloads.
- Existing source, session, control-character, line-length, and standard-input
  size limits continue to apply.
- Queue and diagnostic metadata may retain `attention_type`, but never raw hook
  input.

Example direct adapter command:

```bash
jarvis-line emit \
  --source claude \
  --session session-123 \
  --phase attention \
  --attention-type input_required \
  --line "Your deployment choice is required."
```

## Codex Hook Adapter

The Codex installer adds an idempotent `PermissionRequest` command hook beside
the existing SessionStart integration. The hook reads one JSON object from
standard input and uses the official common fields:

- `session_id`
- `cwd`
- `hook_event_name`
- `tool_name`
- `tool_input`

The adapter performs these steps:

1. Validate the payload type, event name, stable session id, and bounded input.
2. Return immediately when attention is disabled or the event is unsupported.
3. Extract only the minimum fields needed by the local formatter.
4. Generate a bounded spoken line and discard the raw payload.
5. Submit a normalized `attention` event through the existing queue path.
6. Exit `0` without writing to stdout so it cannot alter the approval decision.

The installer also verifies that Codex's current `hooks` feature is enabled. If
it is disabled, guided setup shows the exact pending config change and enables
`[features].hooks = true` only as part of the user-approved apply plan. Legacy
`[features].codex_hooks` is not written. Existing unrelated feature flags and
hook definitions are preserved.

The hook never allows or denies permission. Codex remains the sole owner of the
approval UI and decision. Installation preserves unrelated hooks, creates the
existing backup before the first mutation, and remains safe to run repeatedly.
Uninstall removes only Jarvis Line hook entries.

## Codex Plan And Input Adapter

Plan mode has two distinct user-attention paths:

- An operation that needs approval still arrives through the official
  `PermissionRequest` hook. Its `permission_mode` may be `plan`, but it is
  otherwise handled exactly like any other permission request.
- A normal Plan-mode question uses Codex's `request_user_input` tool. Codex
  does not currently expose a dedicated lifecycle hook for this call, so the
  existing session watcher recognizes its structured `response_item` entry.

The watcher accepts only a `response_item` whose payload type is
`function_call`, whose exact name is `request_user_input`, and whose bounded
JSON arguments contain a non-empty `questions` array. It uses only the first
question's bounded `header` and `question` fields to classify and compose a
short local line; option labels, descriptions, free-form answers, and the raw
arguments are never copied to queue metadata or diagnostics. An invalid or
future incompatible payload is ignored without affecting ordinary Jarvis Line
processing.

The call id is transformed into a short one-way correlation token. When the
watcher later observes the matching `function_call_output` or
`custom_tool_call_output`, it removes a still-queued `input_required` alert.
The raw call id is not persisted. This avoids speaking a stale question after
the user has already answered while keeping unrelated sessions isolated.

This adapter is intentionally a compatibility layer over the transcript format
the watcher already consumes, not a claimed Codex hook API. Captured minimal
fixtures and fail-soft parsing tests guard the observed shape. If Codex changes
that shape, automatic Plan-mode questions may temporarily become silent, but
permission hooks and commentary/final speech continue to operate.

The initial release does not install `PostToolUse` solely to cancel alerts.
Doing so would start a Python hook for every supported tool call. Attention jobs
instead have a short expiry and are checked again immediately before synthesis,
which avoids permanent overhead while preventing old requests from playing far
behind the active session.

Reference: https://learn.chatgpt.com/docs/hooks

## Safe Local Formatter

The formatter is a pure module with no network, model, TTS, subprocess, or file
system dependency. It returns a normalized intent category plus one spoken line.

Input fields are treated as untrusted. Formatting follows this order:

1. Recognize a canonical tool-specific intent such as `apply_patch` or a known
   MCP operation.
2. For shell requests, parse only enough structure to classify the executable
   and safe subcommand.
3. Use `tool_input.description` only as a classification hint after length
   bounding and secret/path redaction; never speak it verbatim by default.
4. Extract a hostname only through URL parsing and discard user info, ports,
   paths, query strings, and fragments.
5. Fall back to a normalized tool label.

Initial shell intent categories are:

- dependency installation
- remote repository push, pull, or clone
- network connection to a safe hostname
- file deletion
- process termination
- privileged command execution
- test or build execution
- generic shell permission

Initial tool categories are:

- project file modification (`apply_patch`, `Edit`, `Write` aliases)
- MCP operation labels derived from an allowlisted provider and action map
- generic named-tool permission

The formatter must not execute shell parsing through a shell. It may use
`shlex`, `urllib.parse`, strict identifier normalization, and fixed template
maps. Parse errors fall back safely.

For `input_required`, the formatter normalizes the first question, removes
URLs, code spans, control characters, and obvious secret assignments, and caps
the content before placing it in a fixed language template. If no safe question
text remains, it uses the generic equivalent of "Your input is needed to
continue." It never speaks answer choices.

## Language Behavior

Attention output follows the existing full-name `line_language` setting. Fixed
templates are provided for the languages currently exposed by the shared UI
contract:

- English
- Turkish
- French
- Italian
- Japanese
- Chinese

An unknown language uses the English fallback and records a content-free
diagnostic warning. Guided setup recommends attention only when a built-in
template catalog exists for the selected language. Third-party
`input_required` adapters may provide an explicit line in any language that is
compatible with the configured TTS voice.

## Queue Policy

The queue continues to serialize all playback through one worker. Priority is:

1. `attention`
2. `final`
3. `commentary`

Within the same priority, the current cross-session rotation and oldest-first
selection remain in effect.

Scheduling rules:

- A new attention event replaces an older attention event with the same
  `session_key` and `attention_type`.
- A new attention event removes queued commentary from the same session because
  the actionable request is now more relevant.
- A new final event removes all older jobs from the same session, including
  attention, because the session has completed.
- A matching Codex input-tool result removes a still-queued `input_required`
  job through its one-way correlation token.
- Commentary never removes attention or final jobs.
- When the queue is full, the oldest lowest-priority job is removed first.
- Attention jobs expire after 30 seconds. Expiry is enforced both while loading
  the queue and immediately before synthesis/playback.
- No event interrupts audio already playing, and no second player starts in
  parallel.

Message identity includes `session_key`, phase, attention type, and spoken line.
Different sessions in the same repository therefore cannot suppress each other.

## Configuration

The shared configuration contract adds:

```json
{
  "attention_enabled": false
}
```

No free-form formatter configuration is exposed. The standard policies still
apply:

- `speech_enabled = false` disables attention.
- `speak_mode = off` disables attention.
- `final_only` suppresses commentary but does not suppress enabled attention.
- quiet hours and quiet days suppress attention consistently with other speech.
- `max_spoken_chars`, selected TTS, volume, fallback TTS, and worker resource
  limits apply normally.

The macOS app exposes one validated toggle. It does not expose raw event lists,
templates, commands, or formatter rules. CLI `config get/set` supports the same
boolean field through the existing contract validation.

## Diagnostics And Privacy

Privacy-safe traces may record:

- event received, queued, skipped, expired, deduplicated, or played
- hashed session identity
- source
- phase
- attention type
- non-content reason code

They must not record:

- spoken line content unless the existing explicit debug-content setting is on
- raw command or arguments
- `tool_input`
- descriptions
- URLs beyond a formatter-internal hostname that is discarded after line
  generation
- paths, secrets, tokens, environment values, or transcript content

Support reports expose counts and reason codes only. Attention formatting never
contacts an LLM or cloud API. A configured cloud TTS may receive the final
spoken line under the same disclosure and responsibility model as other Jarvis
Line speech.

## Failure Handling

- Invalid hook JSON exits `0`, emits no stdout, and records a bounded
  content-free diagnostic event when possible.
- Missing session identity drops the event rather than using a global key.
- Formatter errors use the safe generic tool fallback.
- Queue lock or write failure is fail-soft and cannot block the Codex approval
  dialog.
- A stopped runtime, disabled speech, quiet period, or disabled attention causes
  an intentional no-op with a diagnostic reason.
- TTS failure follows the existing fallback backend behavior.
- An expired attention event is removed without synthesis.

## Setup And Documentation

Guided setup adds an `Attention alerts` choice when Codex is selected. The
choice remains visible for other agents because they can use the public event
protocol, while the UI clearly labels automatic permission integration as
Codex-only in this release. For Codex, the review screen states whether the
PermissionRequest hook and hooks feature flag will be installed or refreshed.
Apply remains transactional: config validation happens before hook mutation,
and hook failure is reported without rewriting instruction Markdown.

The generated AGENTS/CLAUDE/GEMINI instruction block does not need a new rule
for automatic Codex permission events. Documentation explains that
`input_required` from other agents requires an adapter event and does not infer
user intent from arbitrary transcripts.

README and command documentation cover:

- what Attention Events do
- how they differ from commentary/final summaries
- default and existing-install behavior
- example permission lines
- the privacy boundary
- `emit --phase attention` usage
- installation, status, doctor, and synthetic-test behavior
- the distinction between Plan-mode permission requests and ordinary
  `request_user_input` questions

## Testing

Python tests cover:

- attention event validation and CLI parsing
- unsupported attention types and missing fields
- shell and tool intent classification
- redaction, malformed shell input, unsafe URL input, and fallback behavior
- every built-in language template catalog
- same-repository multi-session isolation
- attention/final/commentary priority and fairness
- queue overflow, coalescing, replacement, and expiry
- quiet hours, disabled attention, disabled speech, and speak-mode interaction
- Codex PermissionRequest mapping
- Codex Plan-mode `request_user_input` detection, safe question formatting,
  malformed transcript compatibility, and matching-result cancellation
- no stdout and exit `0` on malformed hook input
- idempotent hook install/uninstall preserving unrelated entries
- hooks-feature migration from `codex_hooks` to `hooks` without disturbing
  unrelated Codex configuration
- content-free diagnostics and support output

Swift tests cover shared contract decoding, default-off behavior, toggle
validation, setup-plan serialization, and settings persistence.

Smoke verification covers:

1. Install or refresh hooks in a temporary Codex home.
2. Submit a synthetic PermissionRequest payload.
3. Confirm one normalized attention job with the correct session identity.
4. Confirm no raw command appears in queue, trace, or logs.
5. Confirm a final event supersedes same-session attention.
6. Run the full Python, clean-install, Windows/Linux smoke, Swift, and release
   metadata checks already used by the project.

Real-device verification uses the installed macOS runtime with both Kokoro and
system TTS. It measures hook return time, queue-to-play latency, duplicate
behavior, and worker RSS. No release is cut until these checks pass and the
existing Jarvis Line commentary/final flow still works.

The one-shot hook adapter must leave no child process behind and perform no
network or model work. A 30-run local benchmark records median and p95 return
time; p95 must stay below 150 ms on the primary validated macOS machine before
release. CI verifies the adapter path is bounded and hermetic rather than
enforcing a wall-clock threshold on shared runners.

## Release Boundary

Attention Events are a minor feature suitable for the next `0.x` minor release.
The feature remains beta alongside the existing project. Windows and Linux can
consume explicit attention protocol events, but automatic Codex hook behavior
must be described according to the platforms exercised in CI and on real
devices.
