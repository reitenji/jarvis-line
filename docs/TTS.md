# TTS Reference

Jarvis Line can speak through Kokoro, platform system TTS, macOS `say`, or a custom command/API wrapper.

## Kokoro

Kokoro is the recommended default for English.

Jarvis Line's provided Kokoro defaults are English-focused: `lang=en-gb` with an English voice mix. If you want Kokoro for another language, configure a Kokoro model, voice, and `lang` that actually support that language. Jarvis Line does not automatically switch Kokoro models based on the instruction language.

For non-English speech, macOS system TTS, Edge TTS, OpenAI TTS, or another custom backend may be a better fit unless you already have a language-compatible Kokoro setup.

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
~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx
~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin
```

Use custom paths:

```bash
jarvis-line kokoro configure \
  --model-path ~/.jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx \
  --voices-path ~/.jarvis-line/tts/kokoro-models/voices-v1.0.bin
```

## System TTS

System TTS is the recommended fallback for users who do not want Kokoro.

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

For the best macOS fallback voice, leave `system_voice` unset:

```bash
jarvis-line config set system_voice null
jarvis-line config set system_rate null
jarvis-line tts use system
```

This lets macOS choose its default system voice instead of forcing a specific voice.

## macOS Read & Speak Voices

On macOS, the `system` backend uses the same default voice that macOS uses for **Read & Speak** when `system_voice` is `null`. This is the best option when you want Jarvis Line to speak a language that is different from your macOS UI language.

To choose the macOS default speech language and voice:

1. Open **System Settings**.
2. Go to **Accessibility**.
3. Open **Read & Speak**.
4. Set **System speech language** to the language you want Jarvis Line to speak.
5. Set **System voice** to a natural voice for that language.
6. Keep Jarvis Line on system TTS with no explicit voice override.
7. Install Jarvis Line instructions in the same language so the agent writes speakable lines for that TTS voice.

```bash
jarvis-line tts use system
jarvis-line config set system_voice null
jarvis-line config set system_rate null
jarvis-line instructions print agents --language "Turkish"
```

If your macOS UI is English, you can still choose a Read & Speak voice for another language and set Jarvis Line's instruction language to match it. These settings are independent.

Make the Read & Speak language, Read & Speak voice, and Jarvis Line instruction language match. For example, if Read & Speak is set to Turkish, print Turkish Jarvis Line instructions; if it is set to German, print German instructions and paste them into your agent instruction file.

Avoid mismatched or low-quality voices if you care about natural speech. For example, an English TTS voice reading Turkish text can sound robotic or badly pronounced. Prefer newer Siri or premium voices from Read & Speak when they are available. Some of those voices may not appear in `say -v '?'`; leaving `system_voice` unset lets macOS use the selected Read & Speak voice.

## macOS `say`

This preset exists for users who specifically want macOS `say` options.

```bash
jarvis-line tts use macos
```

macOS `say` supports:

- `macos_voice`
- `macos_rate`

## Custom Command

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

## Public Libraries And Tools

Jarvis Line's core package intentionally has no required third-party runtime dependencies. The default install gives you the CLI, watcher, queue, config, support report, and system TTS fallback.

Optional integrations use public packages or system tools:

| Name | Used for | Required? | Notes |
|---|---|---:|---|
| [kokoro-onnx](https://pypi.org/project/kokoro-onnx/) | Local Kokoro TTS inference | Optional | Installed only when using the Kokoro backend. |
| [sounddevice](https://pypi.org/project/sounddevice/) | Live audio playback for Kokoro | Optional | Enables streaming playback without writing normal audio files. |
| [soundfile](https://pypi.org/project/soundfile/) | Audio file handling for Kokoro fallback playback | Optional | Used when temporary-file playback is needed. |
| [numpy](https://pypi.org/project/numpy/) | Audio array handling for Kokoro playback | Optional | Installed with the Kokoro extra. |
| [pytest](https://pypi.org/project/pytest/) | Test suite | Development only | Installed with the `test` extra. |
| [edge-tts](https://pypi.org/project/edge-tts/) | Example custom command TTS backend | Optional | Not installed by Jarvis Line; users can wire it through `tts command`. |
| [OpenAI TTS](https://platform.openai.com/docs/guides/text-to-speech) | Example API-backed custom TTS | Optional | Not installed or configured by default; use a wrapper command if desired. |
| macOS `say` | System TTS fallback on macOS | Optional system tool | Built into macOS. |
| PowerShell `System.Speech.Synthesis` | System TTS fallback on Windows | Optional system tool | Used by the `system` backend on Windows. |
| `spd-say`, `espeak-ng`, or `espeak` | System TTS fallback on Linux | Optional system tools | Install one if you want system TTS on Linux. |

Install Kokoro-related Python dependencies:

```bash
python3 -m pip install "jarvis-line[kokoro]"
```

Or from a repository checkout:

```bash
python3 -m pip install -e ".[kokoro]"
```

Jarvis Line does not redistribute Kokoro model files, voice files, Edge TTS, OpenAI credentials, or third-party API keys. Users are responsible for installing optional backends and following the upstream license/usage terms for the tools they choose.
