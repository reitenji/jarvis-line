# Jarvis Line Configuration

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
jarvis-line config contract
```

`config contract` prints the versioned defaults, field metadata, backend capabilities, and controlled UI options used by both the CLI and macOS manager.

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
jarvis-line config set attention_enabled true
jarvis-line config set cleanup_enabled false
jarvis-line config set cleanup_interval_hours 168
```

## Common Settings

| Setting | Default | Meaning |
|---|---:|---|
| `tts` | `kokoro` | Selected TTS backend |
| `speak_mode` | `final_only` | Speak final responses only, commentary and final, or off |
| `line_prefixes` | `["Jarvis line:"]` | Prefixes accepted as spoken lines |
| `speak_without_prefix` | `false` | Optional fallback: speak a short derived status from assistant messages that do not contain a prefix |
| `line_language` | `English` | Expected language for spoken lines |
| `max_spoken_chars` | `240` | Maximum spoken summary length |
| `quiet_hours` | `null` | Optional time range where speech is skipped |
| `quiet_days` | `[]` | Optional days where speech is skipped |
| `message_template` | `{line}` | Template for spoken output |
| `fallback_tts` | `null` | Fallback backend if the selected TTS fails |
| `max_queue_size` | `8` | Maximum queued audio jobs |
| `dedupe_window_seconds` | `null` | Optional duplicate suppression override |
| `audio_worker_idle_exit_seconds` | `60` | Seconds the audio worker may stay idle before exiting to release TTS memory |
| `audio_worker_max_rss_mb` | `512` | Maximum audio worker RSS in MB before it drains the current burst and exits |
| `speech_enabled` | `true` | Global/project switch for speech |
| `attention_enabled` | `false` | Speak opt-in permission and input-required alerts |
| `cleanup_enabled` | `true` | Run bounded automatic cleanup when maintenance is due |
| `cleanup_interval_hours` | `24` | Automatic cleanup frequency: Daily (`24`) or Weekly (`168`) |
| `debug_content_logging` | `false` | Include spoken text in local legacy logs; the structured trace remains metadata-only |
| `volume` | `0.7` | Playback volume where supported |
| `final_trigger_mode` | `notify` | Trigger strategy for final responses |

## Storage Cleanup

Automatic cleanup is enabled by default. Its only supported intervals are Daily
(`24` hours) and Weekly (`168` hours); other values are rejected. It is not a
daemon, operating-system timer, or separate scheduler. The watcher checks once
at startup and then uses an in-memory hourly gate before consulting its small
maintenance-state record, so actual work happens only after the selected
interval has elapsed.

Automatic cleanup removes generated audio older than 24 hours. A manual
`jarvis-line cleanup run` retains a ten-minute window for generated audio; both
modes also consider recognized temporary artifacts older than one hour, known
rotated logs older than seven days, and stale locks only when their owner is
proven dead. Disabling `cleanup_enabled` affects automatic cleanup only: manual
status and manual cleanup remain available.

The cleanup allowlist is deliberately narrow. It never removes configuration,
hook definitions, queue/state/cache files, current logs or trace data, Kokoro
models or voices, custom TTS/output paths, support reports, user files,
symlinks, unknown entries, or nested content. See [the cleanup command
reference](COMMANDS.md#cleanup) for output, exit behavior, and privacy details.

## Attention Alerts

`attention_enabled` is a strict boolean and defaults to `false`, including when
an older configuration does not contain the key. Guided setup recommends it for
a new Codex setup but does not silently enable it for an existing install.

When enabled, Codex `PermissionRequest` hooks produce locally formatted
permission alerts only when approval is routed to the user. Requests handled by
Codex `auto_review` or the legacy `guardian_subagent` reviewer remain silent.
Blocking Plan-mode `request_user_input` calls produce input-required alerts
through the fail-soft session adapter; questions with an automatic resolution
timer remain silent. Claude, Gemini, and other integrations must submit an
explicit `attention` event through the public protocol.

Attention uses the same TTS, volume, maximum length, quiet-time, queue, and
resource settings as status speech. `final_only` still allows enabled attention
alerts; `speak_mode = off` or `speech_enabled = false` suppresses them. The
toggle does not expose custom templates or raw request formatting rules.

## Prefixes

```bash
jarvis-line config prefix list
jarvis-line config prefix add "Friday line:"
jarvis-line config prefix remove "Friday line:"
```

## Profiles

```bash
jarvis-line config profile save work
jarvis-line config profile list
jarvis-line config profile use work
jarvis-line config profile delete work
```

## Default Kokoro Config

Fresh setup starts from this shape:

```json
{
  "tts": "kokoro",
  "speak_mode": "final_only",
  "attention_enabled": false,
  "cleanup_enabled": true,
  "cleanup_interval_hours": 24,
  "line_prefixes": ["Jarvis line:"],
  "speak_without_prefix": false,
  "line_language": "English",
  "max_spoken_chars": 240,
  "quiet_hours": null,
  "audio_worker_idle_exit_seconds": 60,
  "audio_worker_max_rss_mb": 512,
  "debug_content_logging": false,
  "model_path": "~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx",
  "voices_path": "~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin",
  "voice": "bm_george:70,bm_lewis:30",
  "lang": "en-gb",
  "speed": 1.08,
  "volume": 0.7,
  "play_by_default": true,
  "final_trigger_mode": "notify",
  "playback_mode": "tempfile",
  "fallback_playback_mode": "tempfile",
  "delete_after_play": true,
  "temp_dir": "~/.jarvis-line/tts/generated"
}
```

## Default System Fallback Config

If Kokoro is not ready, or if the user chooses not to use Kokoro, `system` is the recommended default fallback. `setup --default` keeps the behavior defaults and switches only the TTS-specific shape:

```json
{
  "tts": "system",
  "speak_mode": "final_only",
  "attention_enabled": false,
  "cleanup_enabled": true,
  "cleanup_interval_hours": 24,
  "line_prefixes": ["Jarvis line:"],
  "speak_without_prefix": false,
  "line_language": "English",
  "max_spoken_chars": 240,
  "quiet_hours": null,
  "volume": 0.7,
  "play_by_default": true,
  "final_trigger_mode": "notify",
  "delete_after_play": true,
  "temp_dir": "~/.jarvis-line/tts/generated",
  "system_voice": null,
  "system_rate": null
}
```

## Manual Config Editing

You can edit `~/.codex/hooks/jarvis_line_config.json` directly.

Rules:

- Keep it valid JSON.
- Run `jarvis-line doctor` after editing.
- Prefer CLI commands for normal changes.
- Do not store API keys directly in the config.
- Keep `debug_content_logging` disabled unless you are actively diagnosing a local problem.
- Put API keys in environment variables or in your own wrapper script.
- Use `jarvis-line tts capabilities` before adding backend-specific fields.

Example quieter config:

```json
{
  "tts": "system",
  "speak_mode": "final_only",
  "attention_enabled": false,
  "line_prefixes": ["Jarvis line:"],
  "speak_without_prefix": false,
  "line_language": "English",
  "max_spoken_chars": 160,
  "quiet_hours": "22:00-08:00",
  "volume": 0.5,
  "play_by_default": true,
  "final_trigger_mode": "notify",
  "delete_after_play": true,
  "temp_dir": "~/.jarvis-line/tts/generated",
  "system_voice": null,
  "system_rate": null
}
```

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
