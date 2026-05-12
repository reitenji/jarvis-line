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

```bash
jarvis-line setup --default
```

```text
[OK] watcher script
[OK] audio worker script
Selected TTS: kokoro
Next: run `jarvis-line tts test` to hear a sample.
```

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
Current version: 0.1.0b5
Latest version: 0.1.0b5
Jarvis Line is up to date.
```

For GitHub tag-based installs, check tags from the configured git repository:

```bash
jarvis-line update check --source git --repo https://github.com/reitenji/jarvis-line.git
```

```text
Current version: 0.1.0b5
Latest version: 0.1.0b5
Jarvis Line is up to date.
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

## `kokoro`

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
