# Final Completion Chime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play one restrained cross-platform chime immediately before every eligible final Jarvis Line and expose a safe macOS on/off control.

**Architecture:** A focused Python module generates deterministic mono PCM WAV bytes without dependencies. The existing audio worker applies final-only policy and plays the cue inside its global audio lock before invoking TTS; the shared config contract and Swift settings draft expose one default-on boolean.

**Tech Stack:** Python 3.10 standard library, pytest, SwiftUI, Swift Testing.

## Global Constraints

- `final_chime_enabled` defaults to `true` for existing and new configurations.
- Only normalized `final` playback receives a chime.
- Chime failure must never suppress primary or fallback TTS.
- Playback remains serialized by the existing global audio lock.
- No dependency, persistent audio asset, process, thread, timer, or retained temporary file is added.
- The macOS app exposes only a boolean switch; no sound path or free-form volume field.

---

### Task 1: Deterministic Chime Waveform

**Files:**
- Create: `src/jarvis_line/completion_chime.py`
- Create: `tests/test_completion_chime.py`

**Interfaces:**
- Produces: `completion_chime.wav_bytes() -> bytes`, a cached valid mono 16-bit PCM WAV shorter than 500 ms.

- [ ] **Step 1: Write failing waveform contract tests**

  Parse the result with `wave.open(io.BytesIO(payload), "rb")` and assert one
  channel, 16-bit samples, the declared sample rate, non-empty bounded frames,
  and deterministic cached output.

- [ ] **Step 2: Verify the tests fail**

  Run: `.venv/bin/python -m pytest tests/test_completion_chime.py -q`

  Expected: collection fails because `jarvis_line.completion_chime` does not exist.

- [ ] **Step 3: Implement the minimal waveform generator**

  Generate an ascending two-tone waveform with smooth attack/release envelopes,
  clamp samples to signed 16-bit PCM, write them through `wave`, and cache the
  immutable result with `functools.lru_cache(maxsize=1)`.

- [ ] **Step 4: Verify waveform tests pass**

  Run: `.venv/bin/python -m pytest tests/test_completion_chime.py -q`

  Expected: all tests pass.

### Task 2: Final-Only Audio Worker Integration

**Files:**
- Modify: `src/jarvis_line/audio_worker.py`
- Modify: `tests/test_audio_worker.py`

**Interfaces:**
- Consumes: `completion_chime.wav_bytes() -> bytes`.
- Produces: `play_final_chime(cfg: dict[str, Any]) -> None` and phase-aware `speak_line(..., phase: str = "") -> bool`.

- [ ] **Step 1: Write failing ordering and policy tests**

  Stub chime playback and `speak_with_backend` to record calls. Assert final
  order is `["chime", "speech"]`, commentary and attention omit the chime,
  `final_chime_enabled=false` suppresses it, and a chime exception still records
  speech.

- [ ] **Step 2: Verify the tests fail**

  Run: `.venv/bin/python -m pytest tests/test_audio_worker.py -q`

  Expected: tests fail because phase-aware chime playback is absent.

- [ ] **Step 3: Add fail-open playback inside the audio lock**

  Write cached WAV bytes to `NamedTemporaryFile(suffix=".wav", delete=False)`,
  invoke the existing `kokoro_say.spawn_player`, and unlink the path in
  `finally`. In `speak_line`, call it once only when `is_final_phase(phase)` and
  the setting is enabled. Log completion or the exception class without text.

- [ ] **Step 4: Pass phase from the worker and preserve test doubles**

  Pass `phase=phase` from `run_worker`; update local test doubles to accept the
  optional keyword while retaining the existing cancellation callback for
  attention jobs.

- [ ] **Step 5: Verify worker tests pass**

  Run: `.venv/bin/python -m pytest tests/test_audio_worker.py tests/test_completion_chime.py -q`

  Expected: all tests pass.

### Task 3: Shared Configuration And macOS Control

**Files:**
- Modify: `src/jarvis_line/config_contract.py`
- Modify: `tests/test_config_contract.py`
- Modify: `apps/macos/JarvisLine/Sources/JarvisConfig.swift`
- Modify: `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisConfigContractTests.swift`

**Interfaces:**
- Produces: shared `final_chime_enabled: boolean`, default `true`.
- Produces: `JarvisConfigDraft.finalChimeEnabled: Bool` round-tripped as `final_chime_enabled`.

- [ ] **Step 1: Write failing Python and Swift config tests**

  Assert the Python default/schema/backend capabilities include the new boolean.
  Assert a Swift draft defaults it on and persists an off value.

- [ ] **Step 2: Verify targeted tests fail**

  Run: `.venv/bin/python -m pytest tests/test_config_contract.py -q`

  Run: `swift test --package-path apps/macos/JarvisLine --filter JarvisConfigContractTests`

  Expected: assertions fail because the field does not exist.

- [ ] **Step 3: Add the shared field and strict Swift toggle**

  Add the default, common backend capability, and field help in Python. Add the
  Swift property to defaults, decoding, initialization, saving, and fallback raw
  config. Render a `Final chime` switch under Speech > Events, disabled when
  speech is disabled or speak mode is off.

- [ ] **Step 4: Verify config tests pass**

  Run the two targeted commands from Step 2.

  Expected: all targeted tests pass.

### Task 4: Documentation And End-to-End Verification

**Files:**
- Modify: `docs/CONFIGURATION.md`
- Modify: `tests/run_smoke.py`

**Interfaces:**
- Documents: default-on final chime and the macOS switch.
- Verifies: the shared contract and playback policy remain install-safe.

- [ ] **Step 1: Add the bounded setting documentation and smoke assertion**

  Document `final_chime_enabled` in the speech settings table and assert its
  default in the smoke contract without expanding the README.

- [ ] **Step 2: Run complete verification**

  Run: `.venv/bin/python -m pytest -q`

  Run: `.venv/bin/python tests/run_smoke.py`

  Run: `.venv/bin/python -m jarvis_line.cli soak --quick --json`

  Run: `.venv/bin/python -m compileall -q src tests`

  Run: `swift test --package-path apps/macos/JarvisLine`

  Expected: Python tests, smoke, quick soak, syntax, and Swift tests all pass.

- [ ] **Step 3: Hear the generated cue once**

  Invoke `play_final_chime(default_config())` locally and confirm the temporary
  WAV is removed after synchronous playback.

- [ ] **Step 4: Review and commit implementation**

  Inspect `git diff --check`, `git diff --stat`, and the final status. Commit
  only the feature files on `feature/final-completion-chime`.
