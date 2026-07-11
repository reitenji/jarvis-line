<p align="center">
  <img src="apps/macos/JarvisLine/Resources/AppIcon.png" width="144" alt="Jarvis Line app icon">
</p>

<h1 align="center">Jarvis Line</h1>

<p align="center">
  <strong>Voice notifications for AI coding agents, powered by hook-driven TTS.</strong>
</p>

<p align="center">
  Speak short agent status lines from Codex, Claude, Gemini, and other coding-agent sessions.
</p>

Hear what your coding agent just finished without reading the whole session.

Jarvis Line watches agent session output, finds a short line like this:

```text
Jarvis line: The tests are passing and the branch is ready.
```

Then it sends that line to one audio worker and speaks it with your selected TTS engine.

It is built for long-running agent work: test loops, code reviews, refactors, debugging sessions, background tasks, and any workflow where you want a short spoken summary when the agent finishes.

> **Release status:** Jarvis Line `0.5.0` is beta. The macOS CLI/runtime is the
> primary validated surface. The macOS manager app, Windows, and Linux remain
> Preview while they collect broader real-device evidence. See the
> [support matrix](docs/SUPPORT-MATRIX.md) and [privacy guide](PRIVACY.md).

## TL;DR

Install Jarvis Line from the GitHub release tag, run the guided setup, then paste the generated instruction into the project or global instruction file your agent actually reads.

```bash
python3 -m pip install "git+https://github.com/reitenji/jarvis-line.git@v0.5.0"
jarvis-line setup
jarvis-line doctor
jarvis-line tts test --text "Jarvis line test is ready."
```

`jarvis-line setup` asks for language, compatible TTS, speech behavior, agent,
instruction scope, hook installation, runtime start, and an optional voice test.
It shows one review screen and requires an explicit Apply confirmation before
changing anything. The generic agent target is selected by default; the Codex
hook remains off unless you choose Codex and enable it. For a non-interactive
local default, use `jarvis-line setup --default`.

On macOS, the Preview manager app provides the same flow in **Settings > Run
Setup Assistant...**. Existing configured users are not interrupted; the app
offers the assistant once only when no Jarvis Line config exists.

Recommended defaults:

- English: use Kokoro or macOS system TTS. Jarvis Line's default Kokoro config is English-focused.
- Other languages on macOS: use `system` TTS, leave `system_voice` unset, choose a natural voice for that language in **System Settings > Accessibility > Read & Speak**, then install Jarvis Line instructions in the same language.
- Other languages with Kokoro: configure your own Kokoro model, voice, and `lang` that support that language.
- Avoid mismatched voices. For example, an English voice reading Turkish text can sound robotic or badly pronounced; choose a voice that was built for the language you want spoken.

## Highlights

- Speaks short `Jarvis line:` summaries from agent responses.
- Uses a single audio queue so multiple sessions do not talk over each other.
- Tracks the latest message with a cache instead of scanning huge session logs every time.
- Uses Kokoro as the recommended local voice engine.
- Falls back to system TTS if Kokoro is not installed or the user does not want Kokoro.
- Supports custom TTS commands and API wrappers.
- Accepts a versioned `emit` event from any agent or editor adapter.
- Keeps a bounded privacy-safe lifecycle trace for fast diagnosis.
- Prints agent instructions for `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` so you can paste them where they belong.
- Generates redacted Markdown support reports for issue descriptions.
- Includes a reviewed CLI setup wizard and a native macOS Setup Assistant.

## Who This Is For

Use Jarvis Line if you:

- run Codex, Claude, Gemini, or another coding agent for longer tasks
- leave agents working while you do something else
- want spoken progress and completion summaries instead of constantly checking the terminal
- want control over which TTS engine reads agent summaries
- want spoken text to be explicit, safe, and intentionally written by the agent

Jarvis Line is not a full transcript narrator. It is designed for short spoken agent summaries: progress/commentary lines at meaningful moments while work is happening, and a final status line when the task is done.

## How It Works

```text
agent response or hook event
  -> agent adapter / Codex session watcher
  -> normalized Jarvis Line event
  -> latest-message cache
  -> audio queue
  -> single audio worker
  -> selected TTS engine
```

The important part is the queue. Even if multiple sessions finish close together, Jarvis Line speaks one line at a time.

Codex can use the bundled session watcher and notify hook. Other agents can submit the same normalized event directly:

```bash
jarvis-line emit --source claude --session session-123 --phase commentary --line "The tests are running."
```

See [docs/EVENT-PROTOCOL.md](docs/EVENT-PROTOCOL.md) for JSON stdin and adapter rules.

## Quick Start

Install the package, then start the recommended guided flow:

```bash
jarvis-line setup
```

The wizard uses full language names, asks the CLI for compatible TTS choices,
and presents one final plan before it can write config, install a hook, start the
runtime, download explicitly accepted Kokoro assets, or play a voice test.

It never edits `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`. At completion, run the
printed `jarvis-line instructions print ...` command, review its output, and
paste it into the exact project or global destination shown by setup.

Custom command/API TTS remains an advanced path. Configure and review it first
with `jarvis-line tts use command --command ...`; guided setup can select that
existing command but never accepts or echoes a new command, environment secret,
or working directory through its app/automation bridge.

For the fastest non-interactive local setup:

```bash
jarvis-line setup --default
```

From this repository checkout, use:

```bash
PYTHONPATH=src python3 -m jarvis_line.cli setup
```

### Legacy `init` Flow

`init` remains available for scripts and explicit agent-target options:

```bash
jarvis-line init --codex --language "English"
```

What `jarvis-line init --language "English"` does:

1. Runs the default setup flow.
2. Checks whether Kokoro is ready.
3. Uses Kokoro if it is available.
4. Prints a warning if Kokoro is not ready.
5. Falls back to system TTS so Jarvis Line still works.
6. Writes config to `~/.codex/hooks/jarvis_line_config.json`.
7. Starts the watcher/audio worker runtime.
8. Prints the command you should run to generate agent instructions.

`init` does not edit `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or other Markdown instruction files by default. You choose whether the instruction belongs in a project file or a global/user-level file, then paste the generated block yourself.

`init` is agent-agnostic by default. It does not install a Codex hook unless you pass `--codex`.

Useful `init` options:

| Option | What It Does |
|---|---|
| `--language "English"` | Sets the spoken Jarvis line language used in generated instructions |
| `--codex` | Installs the Codex hook during init |
| `--target agents` | Chooses the instruction target; supported targets are `agents`, `codex`, `claude`, and `gemini` |
| `--path ./AGENTS.md` | Used only with `--write-instructions`; chooses the instruction file path |
| `--apply-tts` | Applies the recommended TTS preset for the selected language when one exists |
| `--no-instructions` | Skips instruction guidance |
| `--write-instructions` | Advanced option that writes the instruction block into the target file |
| `--test` | Plays a short test phrase during setup |

For most users, keep Markdown edits manual. Use `jarvis-line instructions print ...`, review the output, decide whether it belongs in a project instruction file or a global instruction file, then paste it yourself.

Kokoro is the preferred local default because it gives a consistent offline voice. If you do not want Kokoro, use the `system` backend. On macOS, `system` uses the default system voice, which can sound better than forcing older voices such as `Daniel`.

Manual setup is also available:

```bash
jarvis-line setup --default
jarvis-line install codex
jarvis-line instructions print agents --language "English"
jarvis-line doctor
```

Paste the printed instruction block into `AGENTS.md` after reviewing it.

## Agent Instructions

Jarvis Line only speaks lines that the agent explicitly emits. For it to work, the Jarvis Line instruction block must be present in the Markdown instruction file your agent actually reads.

Jarvis Line does not edit your Markdown instruction files by default. Choose the scope first:

| Scope | Use When | Example Location |
|---|---|---|
| Project | You want Jarvis Line only for one repository or workspace | `./AGENTS.md`, `./CLAUDE.md`, `./GEMINI.md` |
| Global/user | You want the same Jarvis Line instruction across many projects | Your agent's global instruction file |

Then print the instruction, review it, and paste it into the file you chose:

```bash
jarvis-line instructions print agents --language "English"
```

If the block is not pasted into the instruction file your agent uses, Jarvis Line may be installed but the agent will not know to emit `Jarvis line: ...` messages.

For Claude/Gemini examples, minimal output, full instruction text, and language-specific templates, see [docs/INSTRUCTIONS.md](docs/INSTRUCTIONS.md).

## TTS Engines

Jarvis Line supports Kokoro, platform system TTS, macOS `say`, and custom command/API wrappers.

```bash
jarvis-line tts capabilities
jarvis-line tts use kokoro
jarvis-line tts use system
jarvis-line tts use command --command 'my-tts --text {text_json}'
```

Official Kokoro model files are not bundled. Review the upstream source and
license, then download and verify the pinned assets explicitly:

```bash
jarvis-line kokoro download --accept-license
jarvis-line kokoro verify
jarvis-line kokoro install-deps
```

Kokoro is the recommended default for English. System TTS is the recommended fallback if Kokoro is not ready or if you prefer your OS voice.

For backend-specific setup, macOS Read & Speak guidance, custom command placeholders, and public dependency notes, see [docs/TTS.md](docs/TTS.md).

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

Change common settings:

```bash
jarvis-line config set speak_mode final_only
jarvis-line config set line_prefixes "Jarvis line:,Friday line:"
jarvis-line config set quiet_hours 22:00-08:00
jarvis-line config set max_spoken_chars 240
jarvis-line config set volume 0.7
jarvis-line config set message_template "Jarvis says: {line}"
jarvis-line config set fallback_tts system
jarvis-line config set audio_worker_idle_exit_seconds 60
jarvis-line config set audio_worker_max_rss_mb 512
jarvis-line config set speech_enabled false
```

For default config JSON, schema commands, profiles, prefixes, manual editing rules, and migration notes, see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Runtime Commands

Top-level commands shown by `jarvis-line --help`:

| Command | What It Does |
|---|---|
| `jarvis-line help` | Prints the top-level help text |
| `jarvis-line setup` | Configures Jarvis Line; `--default` uses the recommended low-friction setup |
| `jarvis-line init` | Runs agent-agnostic setup; add `--codex` to install the Codex hook |
| `jarvis-line doctor` | Runs health checks; `--fix` can restart the runtime when needed |
| `jarvis-line status` | Shows runtime, queue, config, and TTS status |
| `jarvis-line update` | Checks, installs, or configures update behavior |
| `jarvis-line start` | Starts the watcher and audio worker runtime |
| `jarvis-line stop` | Stops the watcher and audio worker runtime |
| `jarvis-line restart` | Restarts the watcher and audio worker runtime |
| `jarvis-line queue` | Inspects or clears queued spoken lines |
| `jarvis-line logs` | Prints redacted watcher and audio worker logs |
| `jarvis-line kokoro` | Downloads/verifies pinned official assets, checks readiness, installs dependencies, or configures model paths |
| `jarvis-line support-report` | Creates reviewed Markdown for GitHub issues |
| `jarvis-line install` | Installs hooks for supported agents; currently Codex hooks are supported |
| `jarvis-line uninstall` | Removes installed hooks |
| `jarvis-line migrate-config` | Migrates older Jarvis Line config files |
| `jarvis-line config` | Reads, edits, and inspects config, defaults, schema, profiles, and prefixes |
| `jarvis-line instructions` | Prints, installs, or checks agent instruction blocks |
| `jarvis-line tts` | Selects, tests, and inspects TTS engines |

For usage examples and expected output shapes for each command, see [docs/COMMANDS.md](docs/COMMANDS.md).

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

## Support Reports

When opening an issue, generate a redacted Markdown support report:

```bash
jarvis-line support-report --output ./jarvis-line-issue.md
```

Open the generated Markdown, review it, remove anything you do not want public, then paste the relevant sections into the GitHub issue.

The default report is intentionally small and redacted. It includes:

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
jarvis-line support-report --full --max-log-bytes 5000000 --output ./jarvis-line-issue-full.md
jarvis-line support-report --since 1h --output ./jarvis-line-issue-recent.md
```

`--full` includes redacted logs up to `--max-log-bytes` per log file. If a log is larger than the limit, Jarvis Line includes the newest bytes and records `truncated: true` in the summary.

Do not paste raw logs into issues. Use `support-report`, review the Markdown, then paste only the useful parts.

## Recipes

- [Custom command TTS](docs/recipes/tts-command.md)
- [Kokoro setup](docs/recipes/kokoro.md)
- [Edge TTS](docs/recipes/edge-tts.md)
- [OpenAI TTS](docs/recipes/openai-tts.md)

## Community

- Read project updates in [Announcements](https://github.com/reitenji/jarvis-line/discussions/categories/announcements).
- Ask installation, configuration, TTS, and agent-integration questions in [Q&A](https://github.com/reitenji/jarvis-line/discussions/categories/q-a).
- Propose early feature ideas in [Ideas](https://github.com/reitenji/jarvis-line/discussions/categories/ideas).
- Report reproducible defects through the [bug report form](https://github.com/reitenji/jarvis-line/issues/new?template=bug_report.yml).
- Review [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately according to [SECURITY.md](SECURITY.md), never in a public issue or discussion.

Jarvis Line's local data and network behavior is documented in
[PRIVACY.md](PRIVACY.md). Optional package/model attribution is listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

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

Verify shared version metadata and the native app:

```bash
python3 scripts/check_version_consistency.py
swift test --package-path apps/macos/JarvisLine
bash scripts/verify-macos-artifacts.sh
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete setup, verification, privacy, and pull request guide.

Jarvis Line uses a simple release branch flow:

```text
feature/* or fix/*
  -> develop
  -> main
  -> version tag and GitHub Release
```

Branch roles:

- `main`: release-ready code only. Public installs should prefer version tags such as `v0.5.0`.
- `develop`: integration branch for reviewed changes before release.
- `feature/*`: new features.
- `fix/*`: bug fixes.

Contribution flow:

1. Open pull requests against `develop`.
2. Include tests or a clear smoke-test note for behavior changes.
3. For bugs, paste a reviewed redacted support report when possible.
4. After review and CI, changes merge into `develop`.
5. Release preparation happens by opening a `develop -> main` pull request.
6. Releases are cut from `main` with a version tag and GitHub Release.

Recommended support report for bug reports:

```bash
jarvis-line support-report --output ./jarvis-line-issue.md
```

## Release Status

The current release is `0.5.0`. Changes listed under `Unreleased` are validated on feature/develop branches before the next version tag is created.

Release-ready project pieces:

- Python package scaffold
- CLI entry point
- CI workflow for macOS, Linux, and Windows
- smoke tests
- pytest-style unit tests
- redacted Markdown support report command
- user-facing config and TTS documentation
- Kokoro status/configure/dependency commands
- config defaults/schema inspection commands
- config profiles and prefix helper commands
- runtime start/stop/restart, queue, and log commands
- privacy-safe runtime trace and native diagnostics
- final-safe, session-fair queue scheduling
- agent-neutral versioned event protocol
- shared CLI/macOS configuration contract
- update check/apply/install/configure commands
- pinned and atomic Kokoro asset download/verification
- clean wheel install/uninstall checks on macOS, Linux, and Windows CI
- dependency auditing, Dependabot configuration, and release SBOM generation
- fallback TTS and command retry/env/cwd settings
- instruction replace/doctor/style commands
- issue template that requests a reviewed redacted support report
- system TTS fallback for users who do not want Kokoro
- Preview macOS menu bar manager app
- Swift tests, app/DMG smoke verification, and SHA-256 release checksums

Release caveat:

- Kokoro model files are not bundled; users can explicitly download verified
  pinned assets or configure trusted custom paths.
- Local DMGs are ad-hoc signed but not Apple-notarized until a Developer ID release process is configured.

## macOS Manager App

A Preview macOS menu bar manager lives in [apps/macos/JarvisLine](apps/macos/JarvisLine).
It keeps the CLI as the core engine and provides native controls for status,
start/stop/restart, repair, test voice, hook install, settings, config file
access, structured runtime diagnostics, and logs.

The menu bar panel is intentionally small: it shows current runtime health and
fast day-to-day actions. Common config changes open in a separate Settings
window, so casual users do not need to edit
`~/.codex/hooks/jarvis_line_config.json` by hand. It preserves unknown/custom
config keys while saving runtime, TTS, and update preferences. The Settings
window uses controlled pickers and presets where possible, shows the installed
CLI/app version in the header, and validates unsafe or incompatible choices
before saving. Picker values and defaults come from the CLI's versioned config
contract, which prevents Python and Swift settings from drifting. The macOS app
uses a custom dark theme derived from the Jarvis Line icon palette instead of
the default macOS utility look.

```bash
cd apps/macos/JarvisLine
swift run JarvisLine
```

To create a clickable app bundle:

```bash
cd apps/macos/JarvisLine
./scripts/package-app.sh
open "dist/Jarvis Line.app"
```

To create a local DMG:

```bash
cd apps/macos/JarvisLine
./scripts/package-dmg.sh
open "dist/JarvisLine-macOS.dmg"
```

The packaging script also writes `dist/JarvisLine-macOS.dmg.sha256`. CI mounts the DMG read-only, checks that it contains exactly one app, and verifies the checksum before retaining the artifact.

## Validation Status

The current release has been exercised locally on macOS with the Jarvis Line CLI, Codex hook flow, queue handling, Kokoro configuration checks, system TTS fallback, instruction generation, support reports, unit tests, and smoke tests.

Some combinations are implemented but still need more real-world validation:

- Windows system TTS playback on a real Windows machine
- Linux system TTS playback with `spd-say`, `espeak-ng`, or `espeak`
- non-English Kokoro setups with user-provided compatible models, voices, and language settings
- third-party/custom TTS command wrappers such as Edge TTS, OpenAI TTS, ElevenLabs, or local model scripts
- real Claude/Gemini hook adapters that call the new `jarvis-line emit` protocol

If you need setup help or are unsure whether the behavior is a defect, start in [Q&A Discussions](https://github.com/reitenji/jarvis-line/discussions/categories/q-a). For a reproducible defect, use the bug report form with a reviewed support report:

```bash
jarvis-line support-report --output ./jarvis-line-issue.md
```
