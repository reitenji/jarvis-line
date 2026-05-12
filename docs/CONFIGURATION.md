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

## Common Settings

| Setting | Default | Meaning |
|---|---:|---|
| `tts` | `kokoro` | Selected TTS backend |
| `speak_mode` | `final_only` | Speak final responses only, commentary and final, or off |
| `line_prefixes` | `["Jarvis line:"]` | Prefixes accepted as spoken lines |
| `line_language` | `English` | Expected language for spoken lines |
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
  "line_prefixes": ["Jarvis line:"],
  "line_language": "English",
  "max_spoken_chars": 240,
  "quiet_hours": null,
  "model_path": "~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx",
  "voices_path": "~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin",
  "voice": "bm_george:70,bm_lewis:30",
  "lang": "en-gb",
  "speed": 1.08,
  "volume": 0.7,
  "play_by_default": true,
  "final_trigger_mode": "notify",
  "playback_mode": "stream",
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
  "line_prefixes": ["Jarvis line:"],
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
- Put API keys in environment variables or in your own wrapper script.
- Use `jarvis-line tts capabilities` before adding backend-specific fields.

Example quieter config:

```json
{
  "tts": "system",
  "speak_mode": "final_only",
  "line_prefixes": ["Jarvis line:"],
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
