# Edge TTS Recipe

Edge TTS can be connected through the command backend.

Install:

```bash
python -m pip install edge-tts
```

Use Turkish voice in play mode by wrapping Edge TTS in a small script, or use file mode:

```bash
jarvis-line tts use command \
  --mode file \
  --command 'edge-tts --voice tr-TR-AhmetNeural --text {text} --write-media {output}' \
  --player 'ffplay -nodisp -autoexit -loglevel quiet {output}'
```

On macOS you can use:

```bash
jarvis-line tts use command \
  --mode file \
  --command 'edge-tts --voice tr-TR-AhmetNeural --text {text} --write-media {output}' \
  --player 'afplay {output}'
```
