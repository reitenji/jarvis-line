# Guided Setup Design

**Status:** Approved direction, awaiting written-spec review  
**Target command:** `jarvis-line setup`  
**Branch:** `feature/guided-setup`

## Problem

Jarvis Line already has an interactive `setup` command, but it exposes a few
raw prompts and writes each answer directly into the live config. It does not
filter choices by platform, explain language and TTS compatibility, coordinate
agent integration, or show a final review before applying changes. A cancelled
or failed run can therefore leave a partially changed configuration.

The project also has good low-level commands for config, TTS, Kokoro assets,
Codex hook installation, instructions, runtime control, and doctor checks. The
guided setup should compose those capabilities instead of introducing another
configuration model.

## Goals

- Turn the existing `jarvis-line setup` command into a safe first-run wizard.
- Add a native macOS Setup Assistant that drives the same setup engine without
  duplicating configuration or compatibility rules in Swift.
- Present controlled, platform-aware choices before advanced free-form input.
- Keep the spoken instruction language and selected TTS compatible by default.
- Recommend Kokoro for English and platform system TTS for other languages.
- Make verified Kokoro installation available only after explicit license and
  download confirmation.
- Preview the complete result and ask for confirmation before changing config.
- Commit the final config in one atomic write and preserve the previous config
  when setup is cancelled or a prerequisite fails.
- Install the Codex hook only when the user explicitly selects Codex and agrees.
- Never edit `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` automatically.
- Print the exact instruction command and destination guidance for the chosen
  agent and project/global scope.
- Start the runtime, run health checks, and play audio only when selected.
- Keep detection cheap: setup must not load the Kokoro model unless the user
  explicitly requests a voice test.

## Non-Goals

- Graphical setup applications for Windows or Linux in this feature.
- Automatic edits to agent instruction Markdown.
- Native Claude or Gemini hook adapters.
- Automatic selection of a natural OS voice for every language.
- Automatic installation of arbitrary custom commands, API credentials, or
  third-party TTS packages.
- Background telemetry or uploading setup results.

## User Flow

`jarvis-line setup` runs these steps in order:

1. **Detect environment**
   - Operating system.
   - Kokoro runtime and verified asset readiness.
   - Platform system TTS readiness.
   - macOS `say` availability when relevant.
   - Existing config values, used as safe defaults.

2. **Choose spoken language**
   - Show common full language names from the config contract.
   - Include `Other language...` for a validated full-name entry.
   - Do not accept short codes such as `en` or `tr`.

3. **Choose TTS backend**
   - English: recommend ready Kokoro; otherwise recommend system TTS.
   - Other languages: recommend system TTS and remind the user to select a
     matching OS voice.
   - Show only backends available on the current platform in the casual list.
   - Keep custom command TTS behind an `Advanced custom TTS...` choice.
   - If English Kokoro is selected but unavailable, offer a verified install.
     Display the upstream source, Apache-2.0 model license, approximate download
     size, and require explicit acceptance before network or package work.
   - Do not auto-configure non-English Kokoro. Print the custom-model command
     path instead because model, voices, language, and phonemizer must match.

4. **Choose speech behavior**
   - Final responses only.
   - Meaningful commentary and final responses.
   - Speech off.
   - Preserve the current setting as the default when it remains valid.

5. **Choose agent and scope**
   - Agent: Codex, Claude, Gemini, or generic `AGENTS.md` integration.
   - Scope: current project or global/user instructions.
   - For Codex, ask whether to install or refresh the bundled hook.
   - For every target, explain that the generated instruction must be reviewed
     and pasted into the instruction file that the agent actually reads.

6. **Choose activation checks**
   - Start or restart the runtime after applying setup, default yes.
   - Play a short voice test, default no because it can load a large model and
     produce sound unexpectedly.

7. **Review and apply**
   - Print a concise summary with language, TTS, speech mode, agent, scope,
     hook action, runtime action, and voice-test action.
   - Ask `Apply this setup? [Y/n]`.
   - On no, EOF, or Ctrl-C, exit without modifying config, hooks, or runtime.

8. **Finish**
   - Complete any explicitly approved Kokoro prerequisite work first.
   - Validate the proposed config. Warnings block the write unless they are
     explicitly identified as advanced custom-TTS warnings.
   - Atomically replace the config once.
   - Install the approved Codex hook.
   - Start or restart the runtime if selected.
   - Run a local doctor check without exposing private data.
   - Run the voice test only if selected.
   - Print the exact `jarvis-line instructions print ... --language "..."`
     command plus project/global destination guidance.

## macOS Graphical Setup Assistant

The existing macOS manager app adds a separate native Setup Assistant window.
It follows the same sequence as the CLI wizard:

```text
Welcome -> Language -> Voice -> Speech -> Agent & Scope -> Review -> Verify
```

### Launch Behavior

- Open the assistant automatically once when the app finds no Jarvis Line
  config. Existing users with a config must not receive surprise onboarding.
- Record that the first-run offer was shown in app preferences. Dismissing it
  does not mutate config and does not reopen it on every launch.
- When setup is incomplete, keep a visible `Complete Setup` action in the menu
  bar panel.
- Add `Run Setup Assistant...` to the full Settings window so any user can
  revisit the flow later.
- Opening or closing the assistant must not change Dock visibility or create a
  second app process.

### Interaction Design

- Use the current Jarvis Line dark theme, app mark, typography hierarchy, and
  restrained cyan/gold semantic accents.
- Use native pickers, radio-style selection rows, toggles, progress indicators,
  and Back/Continue buttons. Do not expose raw JSON or unrestricted config
  fields in the casual flow.
- Keep a stable window size with a fixed header, one scrollable content region,
  and a persistent action footer. Text must remain readable at the longest
  supported language labels.
- Show unavailable TTS choices as disabled only when the explanation helps the
  user; otherwise omit them. Never let a disabled backend become the selected
  plan value.
- Show the Kokoro source, license, approximate size, and install confirmation
  before invoking any network work.
- Project scope uses an `NSOpenPanel` folder picker only to produce accurate
  destination guidance. The app still does not write instruction Markdown.
- The final screen offers `Copy Instructions`, `Test Voice`, and `Done`. Copying
  instructions reads reviewed output from the CLI and places it on the local
  clipboard.

### Progress And Errors

- During apply, replace navigation controls with one progress indicator and the
  current safe step label, such as `Verifying Kokoro assets` or
  `Starting Jarvis Line`.
- A failed step remains visible with a concise recovery action and captured,
  redacted CLI detail. The window does not close automatically on failure.
- Retry uses the same reviewed plan. Back returns to editing only when no apply
  process is active.
- Completion requires a valid config and healthy runtime when runtime start was
  selected. A failed optional voice test is reported separately and does not
  corrupt the completed setup.

## Architecture

### Setup Model

Add small internal value objects for the wizard rather than passing partially
filled `argparse.Namespace` objects between prompts:

- `SetupEnvironment`: platform and backend readiness facts.
- `SetupPlan`: language, backend, speech mode, agent target, instruction scope,
  optional Kokoro install, hook action, runtime action, and voice-test action.

These objects contain no subprocesses or file writes. Pure helper functions
derive available choices, recommendations, proposed config, and review text.

### Versioned Machine Interface

The macOS app must not reconstruct Python setup rules. Extend `setup` with two
machine-oriented subcommands while preserving the current no-subcommand flow:

- `jarvis-line setup inspect --json` returns a bounded versioned document with
  environment facts, current values, available choices, recommendations, and
  whether first-run setup is needed.
- `jarvis-line setup apply --stdin --json` reads a versioned `SetupPlan` JSON
  document from at most 64 KiB of stdin, validates it with the same Python
  helpers as the interactive wizard, applies it, and returns a structured
  `SetupResult`.

The bridge accepts no arbitrary instruction-file path and no secret-bearing
custom command environment. Unknown versions, fields, choices, or option-like
values fail before any persistent change. Human-readable interactive output and
machine-readable JSON must never be mixed on stdout.

### SwiftUI Setup Coordinator

Add a focused `SetupAssistantModel` and `SetupAssistantWindowController`
instead of expanding `JarvisLineModel` into another large state machine.

- The model decodes setup inspection, owns the editable plan, validates step
  navigation locally against server-provided choices, and submits the final
  plan through `JarvisLineCLI`.
- The window controller follows the existing single-window ownership pattern
  and reactivates the existing assistant if the user opens it twice.
- `JarvisLineModel` exposes only the minimal actions needed to refresh status
  after successful setup and to report whether first-run onboarding is needed.
- The CLI remains authoritative for config generation, backend compatibility,
  hook installation, runtime activation, doctor checks, and instruction text.

### Prompt Layer

Use reusable prompt helpers for numbered choices, yes/no questions, and a
validated full language name. Invalid input reprints the available choices.
Prompt functions accept injectable input/output callables so tests do not patch
global terminal state.

The wizard catches EOF and Ctrl-C at its boundary and returns a cancellation
status without a traceback.

### Apply Layer

Applying a setup plan is separate from collecting it:

1. Snapshot the current config in memory.
2. Complete approved external prerequisites such as verified Kokoro assets and
   dependencies. Failure stops setup before config or hook changes.
3. Build and validate the complete config using `config_for_preset()` and the
   existing configuration contract.
4. Write the config with a temporary file in the same directory followed by
   `os.replace()`. The helper must work on macOS, Linux, and Windows.
5. Perform the optional Codex hook action.
6. Activate and verify the runtime.

If a step after the config write fails, report the failed step and retain the
valid config instead of attempting a broad rollback of runtime state. The
previous config is backed up once before replacement so the user can restore it
manually, but setup must not overwrite an existing backup on repeated runs.

### Existing Command Compatibility

- `jarvis-line setup` becomes the guided flow.
- `jarvis-line setup --default` remains non-interactive and keeps its current
  low-friction Kokoro-or-system behavior.
- `jarvis-line setup --test` forces the final voice test while retaining the
  interactive flow.
- `jarvis-line setup inspect --json` and `setup apply --stdin --json` form the
  versioned bridge used by the macOS app and advanced automation.
- Existing `init`, `tts`, `kokoro`, `config`, `instructions`, and `doctor`
  commands remain available for scripting and advanced users.
- Existing config values are preserved unless the reviewed plan intentionally
  changes or removes backend-specific fields.

## Safety And Privacy

- No Markdown instruction file is written by the wizard.
- No API key or command environment is requested in the casual flow.
- Custom TTS remains an explicit advanced path and secrets are never echoed in
  the review summary.
- Network access occurs only for an explicitly accepted Kokoro installation.
- Model files use the existing pinned size and SHA-256 verification.
- No setup answer, health result, or audio text leaves the machine.
- The test phrase contains no user-provided content.
- Clipboard use happens only after the user presses `Copy Instructions`.

## Resource Limits

- Environment detection may check paths, executables, and lightweight Python
  imports but must not initialize the ONNX model.
- The audio worker starts only after the user accepts the final plan.
- Kokoro dependency or model installation runs only when explicitly selected.
- A voice test is opt-in unless `--test` is supplied.
- Existing worker idle and RSS limits remain unchanged.

## Output Shape

The final review should resemble:

```text
Jarvis Line setup review
Language: Turkish
TTS: System voice (recommended for Turkish)
Speech: Commentary and final responses
Agent: Codex
Instructions: Current project AGENTS.md (manual paste)
Codex hook: Install or refresh
Runtime: Restart
Voice test: No

Apply this setup? [Y/n]
```

Successful completion ends with health status and one clear instruction step:

```text
Setup complete.
Next: run `jarvis-line instructions print agents --language "Turkish"` and
paste the reviewed output into this project's AGENTS.md.
```

## Testing

### Unit Tests

- Platform/readiness facts produce the correct casual backend choices.
- English recommends Kokoro only when ready; non-English recommends system TTS.
- Unsupported platform backends are not offered.
- Invalid numbered choices re-prompt without mutating state.
- Short language codes are rejected; full custom language names are accepted.
- Proposed config preserves unrelated settings and removes ignored backend keys.
- Config warnings prevent apply.
- Review text does not reveal custom command environment values or secrets.

### Transaction Tests

- Cancellation at every prompt leaves config, hooks, and runtime unchanged.
- Setup writes the config exactly once after confirmation.
- Atomic replacement leaves the previous valid file intact on write failure.
- Failed Kokoro download or dependency installation leaves active config and
  hook files unchanged.
- Hook installation occurs only for an approved Codex plan.
- Instruction files are never created or edited.

### CLI Tests

- `setup --default` remains non-interactive and backward compatible.
- `setup` completes with mocked prompts on macOS, Linux, and Windows facts.
- Runtime start and doctor checks run only after successful apply.
- Voice test is skipped by default and runs when selected or forced by `--test`.
- Help and command documentation describe the guided flow and its network/audio
  confirmation behavior.

### Machine Contract Tests

- Inspection JSON is versioned, bounded, deterministic, and contains no spoken
  text, command environment, or absolute session paths.
- Apply rejects oversized input, malformed JSON, unknown versions and fields,
  unsupported choices, and custom instruction paths before mutation.
- Interactive and JSON plans produce the same proposed config and side effects.
- JSON mode writes diagnostics only to the result object or stderr and keeps
  stdout parseable.

### macOS App Tests

- Setup inspection and result documents decode into typed Swift models.
- Step navigation cannot advance with a disabled or incompatible selection.
- First-run auto-open occurs only when config is absent and has not already
  been offered.
- Reopening the assistant activates one existing window and one app process.
- Cancel and Back do not save config or install hooks.
- Apply submits exactly the reviewed plan and refreshes the main model once.
- Instruction output is copied only after an explicit user action.
- Failure and retry preserve the reviewed plan and do not dismiss the window.

### Verification

- Run the complete Python suite.
- Run clean-install smoke checks on Python 3.10 and 3.12 across Linux, macOS,
  and Windows CI.
- Run the macOS app build/tests to confirm the shared config contract remains
  compatible.
- Launch the packaged app and visually inspect every assistant step at the
  normal and minimum supported window sizes, including long language labels,
  disabled backends, progress, failure, and completion states.
- Manually exercise one English Kokoro path and one non-English system-TTS path
  on macOS without editing the user's instruction files.

## Acceptance Criteria

- A new user can reach a healthy runtime through `jarvis-line setup` without
  editing JSON.
- A new macOS user can complete the same setup through the native app without
  opening Terminal or receiving a different configuration result.
- The user sees only valid casual choices for the current platform.
- Language and TTS mismatches are prevented or clearly routed to the advanced
  custom-model path.
- No Jarvis Line config, hook, instruction, or runtime change happens before
  final confirmation. The macOS app may persist only its own one-time
  first-run-offer dismissal preference.
- Cancelling or failing before apply preserves the prior installation.
- Agent Markdown remains entirely user-controlled.
- The Setup Assistant opens automatically only for a true first run, remains
  manually accessible later, and never creates a duplicate app instance.
- The completed flow states exactly what was changed and what the user must
  paste into which instruction scope.
