# Final Chime Volume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent, bounded, cross-platform volume control for the
final completion chime.

**Architecture:** Store `final_chime_volume` in the shared configuration and
scale the procedurally generated PCM waveform before playback. Expose the value
through validated CLI configuration and a constrained macOS percentage slider
without changing the queue, event protocol, or single-worker audio ownership.

**Tech Stack:** Python 3.10+, pytest, standard-library PCM/WAV generation,
SwiftUI, Swift Testing

## Global Constraints

- `final_chime_volume` is numeric and inclusive from `0.0` through `1.0`.
- The default is `1.0` to preserve the existing audible chime.
- Volume scaling must work on macOS, Windows, and Linux without new dependencies.
- The generated variants use a bounded in-memory cache and no persistent files.
- Chime failures remain fail-open and final speech must continue.
- The macOS control uses a 5% step and permits no free-form input.
- No version bump, release, push, or installed-runtime change is part of this plan.

---

### Task 1: Shared Configuration And CLI Validation

**Files:**
- Modify: `src/jarvis_line/config_contract.py`
- Modify: `src/jarvis_line/cli.py`
- Modify: `tests/test_config_contract.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/run_smoke.py`

**Interfaces:**
- Consumes: existing `DEFAULT_KOKORO_CONFIG`, `COMMON_CONFIG_KEYS`,
  `CONFIG_FIELD_HELP`, and `config_set(args)`.
- Produces: `final_chime_volume: float`, default `1.0`, supported by every
  backend and validated by `config_set`.

- [ ] **Step 1: Write failing contract and effective-config tests**

Add assertions that the default is `1.0`, the field type is `number`, every
backend supports it, and a config missing the key receives the default:

```python
assert contract["defaults"]["final_chime_volume"] == 1.0
assert contract["fields"]["final_chime_volume"]["type"] == "number"
for backend in contract["backends"].values():
    assert "final_chime_volume" in backend["supports"]
assert config["final_chime_volume"] == 1.0
```

Add the default assertion to `tests/run_smoke.py`.

- [ ] **Step 2: Write failing CLI boundary tests**

Parameterize invalid values:

```python
@pytest.mark.parametrize("value", ["-0.01", "1.01", "true", "quiet"])
def test_config_set_rejects_invalid_final_chime_volume(value, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_effective_config", lambda: {"tts": "system"})
    monkeypatch.setattr(cli, "save_json", lambda *_args: pytest.fail("must not save"))

    assert cli.config_set(
        argparse.Namespace(key="final_chime_volume", value=value)
    ) == 1
    assert "Invalid value for final_chime_volume" in capsys.readouterr().out
```

Add valid cases for `"0"`, `"0.6"`, and `"1"` that assert the parsed numeric
value is saved.

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```bash
python -m pytest tests/test_config_contract.py tests/test_cli.py -q
```

Expected: failures report the missing field/default and absent CLI validation.

- [ ] **Step 4: Implement the shared field and strict validation**

Add:

```python
"final_chime_volume": 1.0,
```

to `DEFAULT_KOKORO_CONFIG`, add the key to `COMMON_CONFIG_KEYS`, and add:

```python
"final_chime_volume": {
    "type": "number",
    "description": "Independent final completion chime volume from 0.0 to 1.0.",
},
```

to `CONFIG_FIELD_HELP`.

In `config_set`, validate without accepting booleans:

```python
if args.key == "final_chime_volume" and not (
    type(value) in (int, float) and 0.0 <= float(value) <= 1.0
):
    print("Invalid value for final_chime_volume: expected a number from 0.0 to 1.0.")
    return 1
```

Normalize accepted values to `float(value)` before saving.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python -m pytest tests/test_config_contract.py tests/test_cli.py tests/run_smoke.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/jarvis_line/config_contract.py src/jarvis_line/cli.py tests/test_config_contract.py tests/test_cli.py tests/run_smoke.py
git commit -m "feat: add final chime volume config"
```

### Task 2: Cross-Platform Waveform Scaling

**Files:**
- Modify: `src/jarvis_line/completion_chime.py`
- Modify: `src/jarvis_line/audio_worker.py`
- Modify: `tests/test_completion_chime.py`
- Modify: `tests/test_audio_worker.py`

**Interfaces:**
- Consumes: `completion_chime.wav_bytes()` and
  `audio_worker.play_final_chime(cfg)`.
- Produces: `completion_chime.wav_bytes(volume: float = 1.0) -> bytes`; the
  worker reads `cfg["final_chime_volume"]` and passes a safe value to it.

- [ ] **Step 1: Write failing waveform tests**

Decode samples from `wav_bytes(1.0)`, `wav_bytes(0.5)`, and `wav_bytes(0.0)`.
Assert the zero variant is silent and the half-level peak is approximately half:

```python
assert max(abs(sample) for sample in silent_samples) == 0
ratio = max(abs(sample) for sample in half_samples) / max(
    abs(sample) for sample in full_samples
)
assert 0.49 <= ratio <= 0.51
assert completion_chime.wav_bytes(-1.0) is completion_chime.wav_bytes(0.0)
assert completion_chime.wav_bytes(2.0) is completion_chime.wav_bytes(1.0)
```

- [ ] **Step 2: Write failing worker propagation tests**

Update the temporary-WAV test so `wav_bytes` captures its argument:

```python
volumes = []
monkeypatch.setattr(
    audio_worker.completion_chime,
    "wav_bytes",
    lambda volume: volumes.append(volume) or b"RIFF-test",
)
audio_worker.play_final_chime({"final_chime_volume": 0.6})
assert volumes == [0.6]
```

Add malformed-value cases that assert the worker uses `1.0` rather than raising.

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
python -m pytest tests/test_completion_chime.py tests/test_audio_worker.py -q
```

Expected: failures show `wav_bytes` has no volume parameter and the worker
still calls it without a level.

- [ ] **Step 4: Implement bounded cached generation**

Use a public normalizer and private bounded cache:

```python
def _normalized_volume(value: float) -> float:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(volume):
        return 1.0
    return round(max(0.0, min(volume, 1.0)), 3)


def wav_bytes(volume: float = 1.0) -> bytes:
    return _wav_bytes(_normalized_volume(volume))


@lru_cache(maxsize=32)
def _wav_bytes(volume: float) -> bytes:
    ...
    sample = max(-1.0, min(1.0, signal * _MASTER_AMPLITUDE * volume))
```

The wrapper ensures clamped values share cache entries.

- [ ] **Step 5: Pass the configured level from the worker**

Add a small defensive helper or equivalent local conversion that returns
`1.0` for malformed/non-finite values and clamps numeric values. Call:

```python
output.write(completion_chime.wav_bytes(final_chime_volume(cfg)))
```

Continue calling `ks.spawn_player(path, 1.0)` because volume is encoded into
the WAV and player controls are not consistent across platforms.

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest tests/test_completion_chime.py tests/test_audio_worker.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/jarvis_line/completion_chime.py src/jarvis_line/audio_worker.py tests/test_completion_chime.py tests/test_audio_worker.py
git commit -m "feat: scale final chime volume consistently"
```

### Task 3: macOS Configuration And Slider

**Files:**
- Modify: `apps/macos/JarvisLine/Sources/JarvisConfig.swift`
- Modify: `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisConfigContractTests.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift`

**Interfaces:**
- Consumes: shared `final_chime_volume` JSON key.
- Produces: `JarvisConfigDraft.finalChimeVolume: Double` and a constrained
  SwiftUI slider under Speech > Events.

- [ ] **Step 1: Write failing Swift config tests**

Extend the final-chime test:

```swift
#expect(draft.finalChimeVolume == 1.0)
draft.finalChimeVolume = 0.6
let saved = draft.applying(to: [:])
#expect(saved["final_chime_volume"] as? Double == 0.6)
```

Construct drafts with `-0.1` and `1.1` and assert:

```swift
#expect(draft.blockingIssues.contains("Final chime volume must be between 0% and 100%."))
```

- [ ] **Step 2: Run Swift tests and verify failure**

Run:

```bash
swift test --package-path apps/macos/JarvisLine
```

Expected: compilation fails because `finalChimeVolume` does not exist.

- [ ] **Step 3: Implement draft loading, validation, and saving**

Add `var finalChimeVolume: Double`, default it to `1.0`, load
`final_chime_volume`, include it in the private initializer, and save:

```swift
updated["final_chime_volume"] = min(max(finalChimeVolume, 0), 1)
```

Add the blocking issue when the value is outside `0...1`.

- [ ] **Step 4: Add the constrained slider**

Immediately after the final-chime toggle, add a settings row with:

```swift
Slider(value: $model.config.finalChimeVolume, in: 0...1, step: 0.05)
    .frame(width: 168)
    .accessibilityLabel("Final chime volume")
Text(model.config.finalChimeVolume.formatted(.percent.precision(.fractionLength(0))))
```

Disable the row controls when speech is disabled, speak mode is off, or the
final chime toggle is off. Do not add a text field.

- [ ] **Step 5: Run Swift tests**

Run:

```bash
swift test --package-path apps/macos/JarvisLine
```

Expected: all Swift tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/macos/JarvisLine/Sources/JarvisConfig.swift apps/macos/JarvisLine/Sources/SettingsWindowView.swift apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisConfigContractTests.swift apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift
git commit -m "feat: add final chime volume slider"
```

### Task 4: Documentation And Full Verification

**Files:**
- Modify: `docs/CONFIGURATION.md`
- Modify: `README.md` only if its current settings summary enumerates the chime
- Test: complete repository test and smoke surfaces

**Interfaces:**
- Consumes: completed configuration, runtime, and macOS app behavior.
- Produces: user-facing configuration guidance and final verification evidence.

- [ ] **Step 1: Document the setting**

Add `final_chime_volume` to the configuration table, examples, and final-chime
section. State that `1.0` preserves the original cue, `0.6` means 60%, and the
generated WAV scaling works consistently across supported platforms.

- [ ] **Step 2: Run formatting and diff checks**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 3: Run the full Python suite**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass, with only documented platform skips.

- [ ] **Step 4: Run smoke and quick soak**

Run:

```bash
python tests/run_smoke.py
python scripts/soak_runtime.py --mode quick
```

Expected: smoke reports `smoke_ok`; soak reports every invariant as passing.

- [ ] **Step 5: Run macOS tests and build**

Run:

```bash
swift test --package-path apps/macos/JarvisLine
swift build --package-path apps/macos/JarvisLine
```

Expected: tests and debug build succeed.

- [ ] **Step 6: Review the complete diff**

Confirm the diff contains only the config/CLI field, waveform scaling, worker
propagation, macOS model/slider, tests, and documentation. Confirm no version,
tag, release, generated app, or installer metadata changed.

- [ ] **Step 7: Commit**

```bash
git add docs/CONFIGURATION.md README.md
git commit -m "docs: explain final chime volume"
```
