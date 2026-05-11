# Custom TTS Command Recipes

Jarvis Line can call any TTS command that accepts text.

## Play Mode

The command plays audio itself.

```bash
jarvis-line tts use command --command 'my-tts --text {text_json}'
```

Supported placeholders:

- `{text}`: raw text
- `{text_json}`: JSON-escaped text
- `{output}`: output file path for file mode

## File Mode

The command writes audio to `{output}`, then Jarvis Line runs a player.

```bash
jarvis-line tts use command \
  --mode file \
  --command 'my-tts --text {text_json} --output {output}' \
  --player 'ffplay -nodisp -autoexit -loglevel quiet {output}'
```

## Advanced Backend Settings

For custom command backends, advanced users may store backend-specific values:

```bash
jarvis-line config set custom_voice_id abc123
jarvis-line config set backend_region eu
```
