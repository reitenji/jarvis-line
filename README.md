# Jarvis Line

Hear what your coding agent just finished without reading the whole session.

Jarvis Line watches agent session output, finds a short line like this:

```text
Jarvis line: The tests are passing and the branch is ready.
```

Then it sends that line to one audio worker and speaks it with your selected TTS engine.

It is built for long-running agent work: test loops, code reviews, refactors, debugging sessions, background tasks, and any workflow where you want a short spoken summary when the agent finishes.

## Highlights

- Speaks short `Jarvis line:` summaries from agent responses.
- Uses a single audio queue so multiple sessions do not talk over each other.
- Tracks the latest message with a cache instead of scanning huge session logs every time.
- Uses Kokoro as the recommended local voice engine.
- Falls back to system TTS if Kokoro is not installed or the user does not want Kokoro.
- Supports custom TTS commands and API wrappers.
- Installs agent instructions for `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`.
- Generates redacted support bundles for safe issue reports.

## Who This Is For

Use Jarvis Line if you:

- run Codex, Claude, Gemini, or another coding agent for longer tasks
- leave agents working while you do something else
- want a spoken completion signal instead of constantly checking the terminal
- want control over which TTS engine reads agent summaries
- want the spoken text to be explicit and safe, not a random chunk of transcript

Do not use Jarvis Line if you want full transcript narration. It is intentionally designed to speak one short status line.

## How It Works

```text
agent response
  -> Jarvis line: ...
  -> session watcher
  -> latest-message cache
  -> notify hook
  -> audio queue
  -> single audio worker
  -> selected TTS engine
```

The important part is the queue. Even if multiple sessions finish close together, Jarvis Line speaks one line at a time.

## Quick Start

Install the package, then run:

```bash
jarvis-line init --language en
```

From this repository checkout, use:

```bash
PYTHONPATH=src python3 -m jarvis_line.cli init --language en
```

What `init` does:

1. Checks whether Kokoro is ready.
2. Uses Kokoro if it is available.
3. Prints a warning if Kokoro is not ready.
4. Falls back to system TTS so Jarvis Line still works.
5. Writes config to `~/.codex/hooks/jarvis_line_config.json`.
6. Starts the watcher/audio worker runtime.
7. Installs the Codex hook.
8. Installs Jarvis Line instructions into `AGENTS.md`.

Kokoro is the preferred default because it gives a consistent local voice. If you do not want Kokoro, keeping the system TTS fallback is fine.

Manual setup is also available:

```bash
jarvis-line setup --default
jarvis-line install codex
jarvis-line instructions install agents --language en
jarvis-line doctor
```

## Agent Instructions

Jarvis Line only speaks lines that the agent explicitly emits. Add the instruction snippet to the file your agent reads.

Codex:

```bash
jarvis-line instructions install agents --language en
```

Claude:

```bash
jarvis-line instructions install claude --path ./CLAUDE.md --language en
```

Gemini:

```bash
jarvis-line instructions install gemini --path ./GEMINI.md --language en
```

Preview before installing:

```bash
jarvis-line instructions print agents --language en
jarvis-line instructions print agents --language en --style minimal
```

The installed instruction tells the agent to include exactly one line like:

```text
Jarvis line: The requested change is implemented and verified.
```

The default instruction is strict on purpose:

- every final response must include exactly one `Jarvis line: ...`
- progress/commentary messages may include one, but do not have to
- normal user-facing text stays in the user's language
- the spoken Jarvis line follows the selected instruction language
- secrets, raw logs, code, and long file contents are forbidden in spoken lines

Default English instruction:

```markdown
## Jarvis Line

Jarvis Line is enabled for this agent.

Every final assistant response must include exactly one spoken status line using this format:

`Jarvis line: <one short spoken summary>`

Rules:
- Any `Jarvis line` must be written in English.
- Include exactly one `Jarvis line: ...` line in every final response.
- You may include an optional `Jarvis line: ...` line in commentary/progress messages.
- Keep each Jarvis line to one short natural sentence.
- Use Jarvis lines only for status, completion, or the next action.
- Do not include secrets, private data, raw logs, code, or long file contents in the Jarvis line.
- Do not start normal messages with phrases like "Jarvis here" or similar persona announcements.
- Keep normal user-facing text in the user's language unless there is a separate reason to switch.
- If the response language differs from the Jarvis line language rule, only the Jarvis line is governed by this section.
- Before sending any final response, verify that it includes exactly one `Jarvis line: ...` line.
```

### Language Choice

The instruction language and TTS language must match.

Recommended default:

```bash
jarvis-line instructions install agents --language en
```

Turkish instructions:

```bash
jarvis-line instructions install agents --language tr --apply-tts
```

Replace or check an existing instruction block:

```bash
jarvis-line instructions install agents --language en --replace
jarvis-line instructions doctor agents
```

User-language mode:

```bash
jarvis-line instructions install agents --language user
```

Notes:

- `--language en` keeps the spoken line English and works well with Kokoro English voices.
- `--language tr --apply-tts` switches away from Kokoro toward a custom command backend, because the current Kokoro ONNX language list does not include Turkish.
- `--language user` is flexible, but you must choose a TTS backend that can read the languages your users will use.

## TTS Engines

Check available engines:

```bash
jarvis-line tts capabilities
```

### Kokoro

Kokoro is the recommended default.

```bash
jarvis-line kokoro status
jarvis-line kokoro install-deps
jarvis-line tts use kokoro
```

Kokoro config supports:

- `voice`
- `lang`
- `speed`
- `volume`
- `model_path`
- `voices_path`
- `playback_mode`
- `fallback_playback_mode`

Jarvis Line tries live streaming first. Temporary audio files are only used if streaming fails.

Kokoro model files are not bundled with Jarvis Line. By default Jarvis Line expects:

```text
~/.codex/tts/kokoro-models/kokoro-v1.0.onnx
~/.codex/tts/kokoro-models/voices-v1.0.bin
```

Use custom paths:

```bash
jarvis-line kokoro configure \
  --model-path ~/.codex/tts/kokoro-models/kokoro-v1.0.onnx \
  --voices-path ~/.codex/tts/kokoro-models/voices-v1.0.bin
```

### System TTS

System TTS is the low-friction fallback.

```bash
jarvis-line tts use system
```

Platform behavior:

- macOS: `say`
- Windows: PowerShell `System.Speech.Synthesis.SpeechSynthesizer`
- Linux: `spd-say`, `espeak-ng`, or `espeak`

System TTS supports:

- `system_voice`
- `system_rate`
- `volume`

### macOS `say`

This preset exists for users who specifically want macOS `say` options.

```bash
jarvis-line tts use macos
```

macOS `say` supports:

- `macos_voice`
- `macos_rate`

### Custom Command

Use this when you want Edge TTS, OpenAI TTS, ElevenLabs, a local model, or your own wrapper script.

Command that speaks directly:

```bash
jarvis-line tts use command --command 'my-tts --text {text_json}'
```

Command that creates an audio file:

```bash
jarvis-line tts use command \
  --mode file \
  --command 'my-tts --text {text_json} --output {output}' \
  --player 'ffplay -nodisp -autoexit -loglevel quiet {output}'
```

Placeholders:

- `{text}`: raw text
- `{text_json}`: JSON-escaped text
- `{output}`: output path for file mode

Advanced command users can store backend-specific settings:

```bash
jarvis-line config set custom_voice_id abc123
jarvis-line config set backend_region eu
```

Custom keys must start with `custom_` or `backend_`.

## Configuration

Jarvis Line stores runtime config here:

```text
~/.codex/hooks/jarvis_line_config.json
```

Read the active config:

```bash
jarvis-line config get
jarvis-line config get tts
jarvis-line config get speak_mode
```

Inspect default configs and supported fields:

```bash
jarvis-line config defaults
jarvis-line config defaults kokoro
jarvis-line config schema
jarvis-line config schema system
```

Change common settings:

```bash
jarvis-line config set speak_mode final_only
jarvis-line config set line_prefixes "Jarvis line:,Friday line:"
jarvis-line config set quiet_hours 22:00-08:00
jarvis-line config set max_spoken_chars 240
jarvis-line config set volume 0.7
jarvis-line config set message_template "Jarvis says: {line}"
jarvis-line config set fallback_tts system
jarvis-line config set quiet_days saturday,sunday
jarvis-line config set speech_enabled false
```

Common settings:

| Setting | Default | Meaning |
|---|---:|---|
| `tts` | `kokoro` | Selected TTS backend |
| `speak_mode` | `final_only` | Speak final responses only, commentary and final, or off |
| `line_prefixes` | `["Jarvis line:"]` | Prefixes accepted as spoken lines |
| `line_language` | `en` | Expected language for spoken lines |
| `max_spoken_chars` | `240` | Maximum spoken summary length |
| `quiet_hours` | `null` | Optional time range where speech is skipped |
| `quiet_days` | `[]` | Optional days where speech is skipped |
| `message_template` | `{line}` | Template for spoken output |
| `fallback_tts` | `null` | Fallback backend if the selected TTS fails |
| `max_queue_size` | `8` | Maximum queued audio jobs |
| `dedupe_window_seconds` | `null` | Optional duplicate suppression override |
| `speech_enabled` | `true` | Global/project switch for speech |
| `volume` | `0.7` | Playback volume where supported |
| `final_trigger_mode` | `notify` | Trigger strategy for final responses |

Manage prefixes:

```bash
jarvis-line config prefix list
jarvis-line config prefix add "Friday line:"
jarvis-line config prefix remove "Friday line:"
```

Save and switch config profiles:

```bash
jarvis-line config profile save work
jarvis-line config profile list
jarvis-line config profile use work
jarvis-line config profile delete work
```

### Default Kokoro Config

Fresh setup starts from this shape:

```json
{
  "tts": "kokoro",
  "speak_mode": "final_only",
  "line_prefixes": ["Jarvis line:"],
  "line_language": "en",
  "max_spoken_chars": 240,
  "quiet_hours": null,
  "model_path": "~/.codex/tts/kokoro-models/kokoro-v1.0.onnx",
  "voices_path": "~/.codex/tts/kokoro-models/voices-v1.0.bin",
  "voice": "bm_george:70,bm_lewis:30",
  "lang": "en-gb",
  "speed": 1.08,
  "volume": 0.7,
  "play_by_default": true,
  "final_trigger_mode": "notify",
  "playback_mode": "stream",
  "fallback_playback_mode": "tempfile",
  "delete_after_play": true,
  "temp_dir": "~/.codex/tts/generated"
}
```

### Default System Fallback Config

If Kokoro is not ready, `setup --default` keeps the behavior defaults and switches only the TTS-specific shape:

```json
{
  "tts": "system",
  "speak_mode": "final_only",
  "line_prefixes": ["Jarvis line:"],
  "line_language": "en",
  "max_spoken_chars": 240,
  "quiet_hours": null,
  "volume": 0.7,
  "play_by_default": true,
  "final_trigger_mode": "notify",
  "delete_after_play": true,
  "temp_dir": "~/.codex/tts/generated",
  "system_voice": null,
  "system_rate": null
}
```

### Manual Config Editing

You can edit `~/.codex/hooks/jarvis_line_config.json` directly.

Rules:

- Keep it valid JSON.
- Run `jarvis-line doctor` after editing.
- Prefer CLI commands for normal changes.
- Do not store API keys directly in the config.
- Put API keys in environment variables or in your own wrapper script.
- Use `jarvis-line tts capabilities` before adding backend-specific fields.

Example quieter config:

```json
{
  "tts": "system",
  "speak_mode": "final_only",
  "line_prefixes": ["Jarvis line:"],
  "line_language": "en",
  "max_spoken_chars": 160,
  "quiet_hours": "22:00-08:00",
  "volume": 0.5,
  "play_by_default": true,
  "final_trigger_mode": "notify",
  "delete_after_play": true,
  "temp_dir": "~/.codex/tts/generated",
  "system_voice": null,
  "system_rate": null
}
```

## Runtime Commands

Install the Codex hook:

```bash
jarvis-line init --language en
jarvis-line install codex
```

Start, stop, or restart the runtime:

```bash
jarvis-line start
jarvis-line stop
jarvis-line restart
```

Remove the Codex hook:

```bash
jarvis-line uninstall codex
```

Check status:

```bash
jarvis-line --version
jarvis-line status
```

Check for updates:

```bash
jarvis-line update check
jarvis-line update install
jarvis-line update install --pre
```

Install updates directly from git:

```bash
jarvis-line update install --source git --repo ssh://git@github.com-personal/YOUR_USER/jarvis-line.git --ref main
```

Configure update notices:

```bash
jarvis-line update configure --enabled true --interval-hours 24
jarvis-line update configure --source git --git-repo ssh://git@github.com-personal/YOUR_USER/jarvis-line.git --git-ref main
jarvis-line update configure --enabled false
```

Run health checks:

```bash
jarvis-line doctor
jarvis-line doctor --json
jarvis-line doctor --fix
```

`doctor` may show an update notice when update checks are enabled and the check interval has elapsed.

Test speech:

```bash
jarvis-line tts test --text "Jarvis line test is ready."
```

Check Kokoro:

```bash
jarvis-line kokoro status
```

Inspect queue and logs:

```bash
jarvis-line queue status
jarvis-line queue clear
jarvis-line logs tail
jarvis-line logs tail watcher --lines 40
```

## Troubleshooting

Run this first:

```bash
jarvis-line doctor
```

Common problems:

| Problem | What To Try |
|---|---|
| No speech | Run `jarvis-line status`, then `jarvis-line doctor --fix` |
| Kokoro warning during setup | Keep system TTS or install Kokoro and run `jarvis-line tts use kokoro` |
| Wrong language pronunciation | Make instruction language and TTS language match |
| Multiple sessions finish together | This is queued; lines should play one at a time |
| Custom command does nothing | Run `jarvis-line tts test`, then check the command placeholders |
| Config edit broke behavior | Fix JSON, then run `jarvis-line doctor` |

## Support Bundles

When opening an issue, generate a support bundle:

```bash
jarvis-line support-bundle --output ./jarvis-line-support.zip
```

The default bundle is intentionally small and redacted. It includes:

- platform summary
- selected TTS
- config warnings
- redacted config
- state summary
- queue summary
- latest-message summary
- watcher log tail
- audio worker log tail

For difficult bugs:

```bash
jarvis-line support-bundle --full --max-log-bytes 5000000 --output ./jarvis-line-support-full.zip
jarvis-line support-bundle --since 1h --output ./jarvis-line-support-recent.zip
```

`--full` includes redacted logs up to `--max-log-bytes` per log file. If a log is larger than the limit, Jarvis Line includes the newest bytes and records `truncated: true` in `summary.json`.

Advanced debugging can include a full redacted config snapshot:

```bash
jarvis-line support-bundle --include-config-full --output ./jarvis-line-support.zip
```

Do not paste raw logs into issues. Attach the support bundle instead.

The GitHub bug report template asks for this bundle by default.

## Config Migration

Older prototypes used:

```text
~/.codex/hooks/kokoro_tts_config.json
```

Jarvis Line now uses:

```text
~/.codex/hooks/jarvis_line_config.json
```

Migrate:

```bash
jarvis-line migrate-config
```

Remove the legacy file after a backup:

```bash
jarvis-line migrate-config --remove-legacy
```

## Recipes

- [Custom command TTS](docs/recipes/tts-command.md)
- [Kokoro setup](docs/recipes/kokoro.md)
- [Edge TTS](docs/recipes/edge-tts.md)
- [OpenAI TTS](docs/recipes/openai-tts.md)

## Development

Install locally:

```bash
python3 -m pip install -e ".[test]"
```

Run smoke checks:

```bash
PYTHONPATH=src python3 tests/run_smoke.py
```

Run pytest:

```bash
python3 -m pytest -q
```

Run syntax checks:

```bash
python3 -m compileall -q src/jarvis_line
```

## Beta Status

Jarvis Line is prepared as a `0.1.0b2` beta package.

Beta-ready project pieces:

- Python package scaffold
- CLI entry point
- CI workflow for macOS, Linux, and Windows
- smoke tests
- pytest-style unit tests
- redacted support bundle command
- user-facing config and TTS documentation
- Kokoro status/configure/dependency commands
- config defaults/schema inspection commands
- config profiles and prefix helper commands
- runtime start/stop/restart, queue, and log commands
- update check/install/configure commands
- fallback TTS and command retry/env/cwd settings
- instruction replace/doctor/style commands
- issue template that requests a redacted support bundle
- system TTS fallback for users who do not want Kokoro

Known beta limits:

- Windows audio should still be validated on a real Windows machine.
- Linux audio should still be validated on a real Linux machine.
- Kokoro model files are not bundled; users must place them locally or configure custom paths.
