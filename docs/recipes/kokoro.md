# Kokoro Setup

Kokoro is Jarvis Line's recommended local TTS engine.

Jarvis Line expects Kokoro runtime files under:

```text
~/.jarvis-line/tts/kokoro-venv
~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx
~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin
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

`status` is a fast readiness check. Use the explicit integrity command when you
want to hash the official model files:

```bash
jarvis-line kokoro verify
```

## Install Python Dependencies

```bash
jarvis-line kokoro install-deps
```

This creates `~/.jarvis-line/tts/kokoro-venv` if needed and installs:

- `kokoro-onnx`
- `sounddevice`
- `soundfile`
- `numpy`

Model files are not bundled with Jarvis Line.

## Download The Official Model Files

Review the upstream
[`model-files-v1.0` release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0)
and its Apache-2.0 model license. Then explicitly accept that license:

```bash
jarvis-line kokoro download --accept-license
jarvis-line kokoro verify
```

The download is optional and is never started by `init`. Jarvis Line pins the
official file sizes and SHA-256 values. Each file is downloaded to a temporary
path and moved into place only after verification succeeds. A mismatched
existing managed file is preserved unless you explicitly use `--force`; even
then, the replacement must pass verification first. The command writes only to
Jarvis Line's managed `~/.jarvis-line/tts/kokoro-models` paths and activates
those paths after both files succeed. Configured custom files elsewhere are not
overwritten.

You can also obtain the files yourself from the same upstream release and place
them under:

```text
~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx
~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin
```

Then run the integrity check and the fast readiness check:

```bash
jarvis-line kokoro verify
jarvis-line kokoro status
```

If your files live somewhere else, configure those paths instead of moving the files.

## Configure Custom Model Paths

```bash
jarvis-line kokoro configure \
  --model-path ~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx \
  --voices-path ~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin \
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

Run `jarvis-line kokoro download --accept-license`, put a trusted model at the
configured `model_path`, or run:

```bash
jarvis-line kokoro configure --model-path /path/to/kokoro-v1.0.onnx
```

### `kokoro voices missing`

Run `jarvis-line kokoro download --accept-license`, put a trusted voices file at
the configured `voices_path`, or run:

```bash
jarvis-line kokoro configure --voices-path /path/to/voices-v1.0.bin
```

### `kokoro python dependencies missing`

Run:

```bash
jarvis-line kokoro install-deps
```

### Official asset verification fails

Do not use the file as an official Jarvis Line default. Download it again from
the pinned release:

```bash
jarvis-line kokoro download --accept-license --force
jarvis-line kokoro verify
```

Custom Kokoro assets are allowed, but they are not expected to match the pinned
official manifest. Configure trusted custom paths and evaluate their source,
license, language support, and compatibility yourself.

### No audio device

Kokoro live playback uses `sounddevice`. If live playback fails, Jarvis Line falls back to temporary file playback where possible.

Check:

```bash
jarvis-line doctor
jarvis-line tts test
```

## If You Do Not Want Kokoro

Use system TTS. On macOS this uses the default system voice, which is often better than forcing a specific older voice:

```bash
jarvis-line tts use system
```

For the default macOS system voice, leave voice overrides unset:

```bash
jarvis-line config set system_voice null
jarvis-line config set system_rate null
```

Or connect any TTS through the command backend:

```bash
jarvis-line tts use command --command 'my-tts --text {text_json}'
```
