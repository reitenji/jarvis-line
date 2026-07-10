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

- A graphical setup flow in the macOS manager app.
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

## Architecture

### Setup Model

Add small internal value objects for the wizard rather than passing partially
filled `argparse.Namespace` objects between prompts:

- `SetupEnvironment`: platform and backend readiness facts.
- `SetupPlan`: language, backend, speech mode, agent target, instruction scope,
  optional Kokoro install, hook action, runtime action, and voice-test action.

These objects contain no subprocesses or file writes. Pure helper functions
derive available choices, recommendations, proposed config, and review text.

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

### Verification

- Run the complete Python suite.
- Run clean-install smoke checks on Python 3.10 and 3.12 across Linux, macOS,
  and Windows CI.
- Run the macOS app build/tests to confirm the shared config contract remains
  compatible.
- Manually exercise one English Kokoro path and one non-English system-TTS path
  on macOS without editing the user's instruction files.

## Acceptance Criteria

- A new user can reach a healthy runtime through `jarvis-line setup` without
  editing JSON.
- The user sees only valid casual choices for the current platform.
- Language and TTS mismatches are prevented or clearly routed to the advanced
  custom-model path.
- No persistent change happens before the final confirmation.
- Cancelling or failing before apply preserves the prior installation.
- Agent Markdown remains entirely user-controlled.
- The completed flow states exactly what was changed and what the user must
  paste into which instruction scope.
