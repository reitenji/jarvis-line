# OpenAI TTS Recipe

OpenAI TTS can be connected through the command backend with a small wrapper script.

Example command shape:

```bash
jarvis-line tts use command \
  --mode file \
  --command 'python scripts/openai_tts.py --text {text_json} --output {output}' \
  --player 'ffplay -nodisp -autoexit -loglevel quiet {output}'
```

Recommended environment:

```bash
export OPENAI_API_KEY=...
```

Keep API keys in environment variables. Do not put secrets directly in Jarvis Line config.
