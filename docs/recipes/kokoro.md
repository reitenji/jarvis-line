# Kokoro Setup

Kokoro is Jarvis Line's recommended local TTS engine.

Jarvis Line expects Kokoro runtime files under:

```text
~/.codex/tts/kokoro-venv
~/.codex/tts/kokoro-models/kokoro-v1.0.onnx
~/.codex/tts/kokoro-models/voices-v1.0.bin
```

## Check Status

```bash
jarvis-line kokoro status
```

This checks:

- Kokoro virtualenv Python
- model file
- voices file
- Python dependencies

## Install Python Dependencies

```bash
jarvis-line kokoro install-deps
```

This creates `~/.codex/tts/kokoro-venv` if needed and installs:

- `kokoro-onnx`
- `sounddevice`
- `soundfile`
- `numpy`

Model files are not bundled with Jarvis Line. Put them in the expected paths, or configure custom paths.

## Add Model Files

Jarvis Line does not download or redistribute Kokoro model files. This keeps the package small and avoids surprising users with large downloads.

Create the model directory:

```bash
mkdir -p ~/.codex/tts/kokoro-models
```

Place these files there:

```text
~/.codex/tts/kokoro-models/kokoro-v1.0.onnx
~/.codex/tts/kokoro-models/voices-v1.0.bin
```

Then verify:

```bash
jarvis-line kokoro status
```

If your files live somewhere else, configure those paths instead of moving the files.

## Configure Custom Model Paths

```bash
jarvis-line kokoro configure \
  --model-path ~/.codex/tts/kokoro-models/kokoro-v1.0.onnx \
  --voices-path ~/.codex/tts/kokoro-models/voices-v1.0.bin \
  --voice "bm_george:70,bm_lewis:30" \
  --lang en-gb
```

Then check:

```bash
jarvis-line kokoro status
jarvis-line tts use kokoro
jarvis-line tts test
```

## Common Problems

### `kokoro venv python missing`

Run:

```bash
jarvis-line kokoro install-deps
```

### `kokoro model missing`

Put `kokoro-v1.0.onnx` at the configured `model_path`, or run:

```bash
jarvis-line kokoro configure --model-path /path/to/kokoro-v1.0.onnx
```

### `kokoro voices missing`

Put `voices-v1.0.bin` at the configured `voices_path`, or run:

```bash
jarvis-line kokoro configure --voices-path /path/to/voices-v1.0.bin
```

### `kokoro python dependencies missing`

Run:

```bash
jarvis-line kokoro install-deps
```

### No audio device

Kokoro live playback uses `sounddevice`. If live playback fails, Jarvis Line falls back to temporary file playback where possible.

Check:

```bash
jarvis-line doctor
jarvis-line tts test
```

## If You Do Not Want Kokoro

Use system TTS:

```bash
jarvis-line tts use system
```

Or connect any TTS through the command backend:

```bash
jarvis-line tts use command --command 'my-tts --text {text_json}'
```
