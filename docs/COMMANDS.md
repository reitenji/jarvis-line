# Jarvis Line Command Reference

This page shows practical usage and example output for each top-level `jarvis-line` command.

Exact paths, process IDs, versions, warnings, and audio behavior depend on your operating system, selected TTS backend, installed voices, queue state, and config. Treat these examples as shape-of-output references rather than exact snapshots.

## `help`

```bash
jarvis-line help
```

```text
usage: jarvis-line [-h] [--version] {help,setup,init,...} ...
Voice notifications for AI coding agents, powered by hook-driven TTS.
```

## `setup`

Recommended interactive setup:

```bash
jarvis-line setup
```

```text
Jarvis line language
  1. English
  2. Turkish
  ...
Choose a number [1]:

Voice backend
  1. Kokoro local (recommended) - ready
  2. System voice - say
  ...

Review setup:
  Language: English
  Voice backend: Kokoro local
  Speech mode: commentary_and_final
  Agent: Generic AGENTS.md-compatible agent
  Instruction guidance: project AGENTS.md at /path/to/project
  Instruction files are guidance only and will not be written.
Apply this setup? [y/N]:

Setup complete.
Next: run `jarvis-line instructions print agents --language "English"`, review the output, and paste it into /path/to/project/AGENTS.md.
```

The wizard does not mutate config, install hooks, start runtime work, access the
network, or play audio before the final confirmation. `Ctrl-C` or EOF before
that confirmation prints `Setup cancelled. No changes were made.` Kokoro
downloads and a voice test are separate explicit choices. The default agent is
generic, and Codex hook installation appears only after Codex is selected.

When unavailable English Kokoro is selected, setup prints the pinned upstream
source, Apache-2.0 model license, and approximate 350 MB download size before
asking for explicit acceptance. Declining leaves network work unapproved.

For a non-interactive low-friction local default:

```bash
jarvis-line setup --default
```

```text
[OK] watcher script
[OK] audio worker script
Selected TTS: kokoro
Next: run `jarvis-line tts test` to hear a sample.
```

The default path chooses ready Kokoro for English and ready system TTS for other
languages. It stops without writing config when the compatible backend is not
ready.

### Machine Setup Interface

The following commands are for native apps and automation. Casual users should
prefer `jarvis-line setup` or the macOS Setup Assistant.

Inspect choices for a full language name:

```bash
jarvis-line setup inspect --language "Turkish" --json
```

```json
{
  "version": 1,
  "language": "Turkish",
  "config_exists": true,
  "current": {
    "tts": "system",
    "line_language": "Turkish",
    "speak_mode": "commentary_and_final"
  },
  "backend_options": [
    {"id": "kokoro", "available": false, "recommended": false},
    {"id": "system", "available": true, "recommended": true}
  ]
}
```

Without `--language`, inspection uses the valid configured `line_language`, then
falls back to `English`. Invalid explicit input returns versioned JSON and exit
code `2`. With `--language`, the top-level `language` is the requested preview;
`current.line_language` continues to report the actual configured language.

Create a reviewed plan such as `plan.json`:

```json
{
  "version": 1,
  "language": "Turkish",
  "tts": "system",
  "speak_mode": "commentary_and_final",
  "agent_target": "codex",
  "instruction_scope": "global",
  "project_path": null,
  "install_kokoro": false,
  "accept_kokoro_license": false,
  "install_codex_hook": true,
  "start_runtime": true,
  "test_voice": false
}
```

Apply it through bounded standard input:

```bash
jarvis-line setup apply --stdin --json < plan.json
```

```json
{
  "version": 1,
  "ok": true,
  "steps": [
    {"name": "config_write", "ok": true},
    {"name": "codex_hook", "ok": true},
    {"name": "runtime", "ok": true},
    {"name": "doctor", "ok": true}
  ],
  "instruction": {
    "target": "codex",
    "filename": "AGENTS.md",
    "scope": "global",
    "destination": "~/.codex/AGENTS.md",
    "command": "jarvis-line instructions print codex --language \"Turkish\"",
    "text": "## Jarvis Line\n..."
  }
}
```

Setup plan input is limited to `65,536` UTF-8 bytes, rejects unknown fields,
and validates backend compatibility before config or network mutation. Failure
responses remain versioned JSON on stdout with a non-zero exit code. The machine
interface returns instruction text for manual paste; it does not create or edit
agent Markdown files. Inspection returns only the current TTS, language, and
speech mode; it never echoes custom commands, command environments, working
directories, model paths, or secrets.

For a Kokoro download, both `install_kokoro` and
`accept_kokoro_license` must be `true`; otherwise the plan is rejected before
network or file activity. The bridge also rejects a `command` field. Configure
custom TTS separately with `jarvis-line tts use command --command ...`, then use
`"tts": "command"` to select that existing reviewed command.

## `init`

```bash
jarvis-line init --codex --language "English"
```

```text
Config written: ~/.codex/hooks/jarvis_line_config.json
Installed Codex SessionStart hook.
Jarvis Line instructions were not written automatically.
Next: choose agent and project/global scope, then run `jarvis-line instructions print agents --language "English"` and paste the output into the instruction file your agent reads.
Jarvis Line init complete.
Next: run `jarvis-line doctor` to verify the install, or start using Codex.
```

## `doctor`

```bash
jarvis-line doctor
```

```text
Jarvis Line doctor
[OK] config - ~/.codex/hooks/jarvis_line_config.json
[OK] Codex hooks.json - ~/.codex/hooks.json
[OK] watcher process - pid=12345
[OK] audio worker process - pid=12346
Selected TTS: kokoro
Next: Jarvis Line is healthy. Use `jarvis-line tts test` to test speech.
```

## `status`

```bash
jarvis-line status
```

```text
Jarvis Line status
tts: kokoro
watcher: running 12345
audio_worker: running 12346
queue_jobs: 0
cached_sessions: 2
speak_mode: final_only
```

## `update`

```bash
jarvis-line update check
```

```text
Current version: 0.5.0
Latest version: 0.5.0
Jarvis Line is up to date.
```

For GitHub tag-based installs, check tags from the configured git repository:

```bash
jarvis-line update check --source git --repo https://github.com/reitenji/jarvis-line.git
```

```text
Current version: 0.5.0
Latest version: 0.5.0
Jarvis Line is up to date.
```

To check and install the latest GitHub release tag in one step:

```bash
jarvis-line update apply
```

```text
Current version: 0.4.0
Latest version: 0.5.0
Running: ... pip install --upgrade git+https://github.com/reitenji/jarvis-line.git@v0.5.0
Next: run `jarvis-line --version` and `jarvis-line doctor`.
```

## `start`

```bash
jarvis-line start
```

```text
Config written: ~/.codex/hooks/jarvis_line_config.json
Started Jarvis Line runtime.
Next: run `jarvis-line doctor` to verify the runtime.
```

## `stop`

```bash
jarvis-line stop
```

```text
Stopped Jarvis Line runtime.
Next: run `jarvis-line start` to start it again.
```

## `restart`

```bash
jarvis-line restart
```

```text
Stopped Jarvis Line runtime.
Config written: ~/.codex/hooks/jarvis_line_config.json
Started Jarvis Line runtime.
```

## `queue`

```bash
jarvis-line queue status
```

```text
Jarvis Line queue
jobs: 0
```

## `logs`

```bash
jarvis-line logs tail watcher --lines 40
```

```text
==> ~/.codex/hooks/jarvis_line_watcher.log <==
1715520000.123 watcher-start
1715520001.456 queued-audio phase=final message_id=...
```

## `trace`

Inspect the bounded, metadata-only runtime lifecycle:

```bash
jarvis-line trace --limit 12
```

```text
Jarvis Line trace
- 1715520001000 queued message_id=abc phase=commentary session_id=4f8c2f05a921
- 1715520001400 speaking message_id=abc phase=commentary queue_delay_ms=400 backend=kokoro
- 1715520005200 completed message_id=abc phase=commentary duration_ms=3800
```

Use `--json` for the macOS app or other tools, and `--clear` to remove the trace file.

## `emit`

Submit a spoken event from any agent adapter:

```bash
jarvis-line emit --source claude --session session-123 --phase final --line "The task is complete."
```

```text
Queued Jarvis Line event for claude.
```

For the versioned standard-input format, see [EVENT-PROTOCOL.md](EVENT-PROTOCOL.md).

## `kokoro`

Fast readiness check:

```bash
jarvis-line kokoro status
```

```text
Kokoro status
[OK] venv python - ~/.jarvis-line/tts/kokoro-venv/bin/python
[OK] model - ~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx
[OK] voices - ~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin
[OK] dependencies - ready
Next: run `jarvis-line tts use kokoro` or `jarvis-line tts test`.
```

Download the pinned upstream model assets after reviewing and accepting their
Apache-2.0 license:

```bash
jarvis-line kokoro download --accept-license
```

```text
Kokoro official model download
Source: https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
Model license: Apache-2.0
Downloading model: kokoro-v1.0.onnx
[OK] model - ~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx - downloaded
Downloading voices: voices-v1.0.bin
[OK] voices - ~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin - downloaded
Activated verified model paths in: ~/.codex/hooks/jarvis_line_config.json
Next: run `jarvis-line kokoro verify`, then `jarvis-line kokoro install-deps`.
```

Verify configured files against the pinned official size and SHA-256 manifest:

```bash
jarvis-line kokoro verify
```

```text
Kokoro official asset verification
[OK] model - ~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx - verified
[OK] voices - ~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin - verified
Source: https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
Model license: Apache-2.0
Next: official Kokoro model assets are verified.
```

`download` writes only to Jarvis Line's managed model directory and activates
those paths after both assets succeed. It preserves an existing mismatched
managed file unless `--force` is supplied. `--force` still replaces it only
after the new temporary file passes integrity verification. Custom models are
supported through manual configuration but will not match the official manifest
unless they are byte-for-byte the pinned release assets.

## `support-report`

```bash
jarvis-line support-report --output ./jarvis-line-issue.md
```

```text
Wrote support report: ./jarvis-line-issue.md
Next: review this markdown, then paste the relevant parts into your issue.
```

## `install`

```bash
jarvis-line install codex
```

```text
Installed Codex SessionStart hook.
```

## `uninstall`

```bash
jarvis-line uninstall codex
```

```text
Removed 1 Codex hook(s).
```

## `migrate-config`

```bash
jarvis-line migrate-config
```

```text
Wrote migrated config: ~/.codex/hooks/jarvis_line_config.json
Next: run `jarvis-line doctor`.
```

## `config`

```bash
jarvis-line config get tts
```

```text
kokoro
```

## `instructions`

```bash
jarvis-line instructions print agents --language "English"
```

```markdown
## Jarvis Line

Jarvis Line is enabled for this agent.

Every final assistant response must include exactly one spoken status line using this format:

`Jarvis line: <one short spoken summary>`
```

## `tts`

```bash
jarvis-line tts test --text "Jarvis line test is ready."
```

```text
stream://played
*sound plays*
```

Some system TTS backends may simply play audio and exit without printing extra terminal output.

Timing notes:

- `jarvis-line tts test` measures the full command duration, including synthesis and playback.
- In local macOS dogfood testing, a short Kokoro test line took about `8.24s` end to end.
- The same short line with system TTS took about `3.94s` end to end.
- For queued Jarvis lines, Kokoro typically started the first audible audio chunk in about `2.1s` to `3.2s`; the remaining time was the spoken line itself.
