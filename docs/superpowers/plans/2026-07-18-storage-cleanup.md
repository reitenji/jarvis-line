# Storage Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded automatic and manual cleanup for Jarvis Line generated
audio, rotated diagnostics, and recognized stale runtime artifacts without
touching user-owned configuration, models, reports, or active runtime state.

**Architecture:** A new `jarvis_line.cleanup` module owns allowlisted paths,
streaming inspection, safe deletion, locking, scheduling state, and structured
reports. The CLI, watcher, and macOS app consume that one contract; the watcher
uses an in-memory hourly gate so cleanup never enters the speech hot path or
creates another daemon.

**Tech Stack:** Python 3.10+ standard library, argparse, pytest, Swift 5.9/SwiftUI, Swift Testing, JSON CLI bridge.

## Global Constraints

- No new dependency, daemon, timer thread, recursive home scan, or filesystem watcher.
- Automatic cleanup defaults to enabled and supports only 24-hour or 168-hour intervals.
- Automatic generated-audio retention is 24 hours; manual cleanup retains a ten-minute active-file safety window.
- Recognized runtime temporary artifacts require one hour of age; rotated logs require seven days.
- Never follow symlinks or delete configuration, hooks, queue/state/cache JSON,
  Kokoro models, custom TTS assets, app bundles, launch agents, or user-created
  support reports.
- Custom TTS output paths outside `~/.jarvis-line/tts/generated` are never scanned.
- Keep error details redacted and bounded to 50 entries.
- Partial cleanup must not stop the watcher, audio worker, message extraction, synthesis, or playback.
- Follow feature branch to `develop` PR to `main` PR promotion; do not push directly to `develop` or `main`.

---

### Task 1: Extend The Shared Configuration Contract

**Files:**
- Modify: `tests/test_config_contract.py`
- Modify: `src/jarvis_line/config_contract.py`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisConfigContractTests.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisConfig.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift`
- Modify: `apps/macos/JarvisLine/Sources/SettingsState.swift`

**Interfaces:**
- Produces config keys `cleanup_enabled: bool` and `cleanup_interval_hours: int`.
- Produces controlled option list `cleanup_interval_hours = [24, 168]`.
- Produces Swift properties `cleanupEnabled` and `cleanupIntervalHours`.
- Cleanup-only setting changes produce `SettingsApplyImpact.saveOnly`.

- [ ] **Step 1: Write failing Python contract tests**

Add these assertions to `test_contract_contains_defaults_fields_and_backends`:

```python
assert contract["defaults"]["cleanup_enabled"] is True
assert contract["defaults"]["cleanup_interval_hours"] == 24
assert contract["fields"]["cleanup_enabled"]["type"] == "boolean"
assert contract["fields"]["cleanup_interval_hours"]["values"] == [24, 168]
assert contract["ui_options"]["cleanup_interval_hours"] == [24, 168]
for backend in contract["backends"].values():
    assert "cleanup_enabled" in backend["supports"]
    assert "cleanup_interval_hours" in backend["supports"]
```

- [ ] **Step 2: Run the Python test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_config_contract.py::test_contract_contains_defaults_fields_and_backends`

Expected: FAIL because cleanup defaults and fields do not exist.

- [ ] **Step 3: Add the Python config fields**

Add both defaults to `DEFAULT_KOKORO_CONFIG`, both keys to
`COMMON_CONFIG_KEYS`, and these metadata entries:

```python
"cleanup_enabled": {
    "type": "boolean",
    "description": "Run bounded cleanup automatically when maintenance is due.",
},
"cleanup_interval_hours": {
    "type": "integer",
    "description": "Minimum interval between automatic cleanup attempts.",
    "values": [24, 168],
},
```

Add this controlled option:

```python
"cleanup_interval_hours": [24, 168],
```

- [ ] **Step 4: Verify the Python contract is GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_config_contract.py`

Expected: all contract tests pass.

- [ ] **Step 5: Write failing Swift config and apply-impact tests**

Add to `JarvisConfigContractTests.swift`:

```swift
@Test func cleanupDefaultsAreBoundedAndPersist() {
    var draft = JarvisConfigDraft([:])

    #expect(draft.cleanupEnabled)
    #expect(draft.cleanupIntervalHours == 24)
    draft.cleanupEnabled = false
    draft.cleanupIntervalHours = 168
    let saved = draft.applying(to: [:])
    #expect(saved["cleanup_enabled"] as? Bool == false)
    #expect(saved["cleanup_interval_hours"] as? Int == 168)
}
```

Add to `SettingsStateTests.swift`:

```swift
@Test func cleanupOnlyChangesDoNotRestartRuntime() {
    var draft = JarvisConfigDraft.defaults
    draft.cleanupIntervalHours = 168

    #expect(SettingsApplyImpact.between(.defaults, draft) == .saveOnly)
}
```

- [ ] **Step 6: Run Swift tests and verify RED**

Run: `swift test --package-path apps/macos/JarvisLine`

Expected: compile failure because the two cleanup properties do not exist. If
the local CLT compiler/SDK mismatch still prevents manifest compilation, record
that infrastructure failure and use CI plus the release packaging command as
the final Swift verification gates.

- [ ] **Step 7: Add bounded Swift config fields**

Add:

```swift
static let cleanupIntervalOptions = [24, 168]
var cleanupEnabled: Bool
var cleanupIntervalHours: Int
```

Wire both fields through `defaults`, dictionary initialization, the private
initializer, `applying(to:)`, `defaultRawConfig()`, and validation:

```swift
let cleanupIntervals = contract.intOptions(
    "cleanup_interval_hours",
    fallback: Self.cleanupIntervalOptions
)
if !cleanupIntervals.contains(cleanupIntervalHours) {
    issues.append("Choose Daily or Weekly automatic cleanup.")
}
```

Classify them as save-only in `SettingsApplyImpact.between`:

```swift
normalizedSaved.cleanupEnabled = draft.cleanupEnabled
normalizedSaved.cleanupIntervalHours = draft.cleanupIntervalHours
```

- [ ] **Step 8: Run focused Python and Swift tests**

Run: `.venv/bin/python -m pytest -q tests/test_config_contract.py`

Run when the local toolchain permits: `swift test --package-path apps/macos/JarvisLine --filter 'cleanup'`

Expected: focused tests pass.

- [ ] **Step 9: Commit the config contract**

```bash
git add src/jarvis_line/config_contract.py tests/test_config_contract.py
git add apps/macos/JarvisLine/Sources/JarvisConfig.swift
git add apps/macos/JarvisLine/Sources/SettingsState.swift
git add apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisConfigContractTests.swift
git add apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift
git commit -m "feat: add cleanup configuration contract"
```

### Task 2: Build The Allowlisted Cleanup Inventory And Deletion Engine

**Files:**
- Create: `tests/test_cleanup.py`
- Create: `src/jarvis_line/cleanup.py`

**Interfaces:**
- Produces `CleanupPaths.default() -> CleanupPaths`.
- Produces `inspect(paths: CleanupPaths | None = None, now: float | None = None) -> CleanupReport`.
- Produces `run(paths: CleanupPaths | None = None, now: float | None = None, automatic: bool = False) -> CleanupReport`.
- Produces `CleanupReport.to_dict() -> dict[str, object]` with stable top-level totals and per-category values.

- [ ] **Step 1: Write failing generated-audio and safety tests**

Create `tests/test_cleanup.py` with a temporary path factory and these behaviors:

```python
import os
from pathlib import Path

from jarvis_line import cleanup


def paths_for(root: Path) -> cleanup.CleanupPaths:
    hooks = root / "hooks"
    generated = root / "jarvis" / "tts" / "generated"
    hooks.mkdir(parents=True)
    generated.mkdir(parents=True)
    return cleanup.CleanupPaths(
        hooks_dir=hooks,
        generated_audio_dir=generated,
        state_path=hooks / ".jarvis_line_cleanup_state.json",
        lock_dir=hooks / ".jarvis_line_cleanup.lock.d",
        watcher_log=hooks / "jarvis_line_watcher.log",
        worker_log=hooks / "jarvis_line_audio_worker.log",
    )


def age(path: Path, seconds: int, now: float = 1_000_000) -> None:
    os.utime(path, (now - seconds, now - seconds))


def test_manual_run_removes_old_generated_audio_but_keeps_recent_and_unknown(tmp_path):
    paths = paths_for(tmp_path)
    old = paths.generated_audio_dir / "kokoro_1.wav"
    recent = paths.generated_audio_dir / "jarvis_line_2.wav"
    unknown = paths.generated_audio_dir / "voice-model.bin"
    for path in (old, recent, unknown):
        path.write_bytes(b"audio")
    age(old, 601)
    age(recent, 599)
    age(unknown, 86_400)

    report = cleanup.run(paths, now=1_000_000)

    assert not old.exists()
    assert recent.exists()
    assert unknown.exists()
    assert report.removed_files == 1
    assert report.removed_bytes == 5


def test_cleanup_never_follows_generated_audio_symlink(tmp_path):
    paths = paths_for(tmp_path)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"private")
    link = paths.generated_audio_dir / "kokoro_link.wav"
    link.symlink_to(outside)
    age(link, 86_400)

    report = cleanup.run(paths, now=1_000_000)

    assert outside.read_bytes() == b"private"
    assert link.is_symlink()
    assert report.skipped_files == 1
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_cleanup.py`

Expected: collection failure because `jarvis_line.cleanup` does not exist.

- [ ] **Step 3: Implement paths, reports, and generated-audio scanning**

Create `cleanup.py` with focused data classes and constants:

```python
AUTO_AUDIO_AGE_SECONDS = 24 * 60 * 60
MANUAL_AUDIO_AGE_SECONDS = 10 * 60
TEMP_AGE_SECONDS = 60 * 60
ROTATED_LOG_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_ERROR_DETAILS = 50
GENERATED_PREFIXES = ("kokoro_", "jarvis_line_")

@dataclass(frozen=True)
class CleanupPaths:
    hooks_dir: Path
    generated_audio_dir: Path
    state_path: Path
    lock_dir: Path
    watcher_log: Path
    worker_log: Path

    @classmethod
    def default(cls) -> "CleanupPaths":
        home = Path.home()
        hooks = home / ".codex" / "hooks"
        return cls(
            hooks_dir=hooks,
            generated_audio_dir=home / ".jarvis-line" / "tts" / "generated",
            state_path=hooks / ".jarvis_line_cleanup_state.json",
            lock_dir=hooks / ".jarvis_line_cleanup.lock.d",
            watcher_log=hooks / "jarvis_line_watcher.log",
            worker_log=hooks / "jarvis_line_audio_worker.log",
        )
```

Use `os.scandir`, `entry.stat(follow_symlinks=False)`, and `stat.S_ISREG`.
Only names beginning with `GENERATED_PREFIXES` are candidates. Store candidate
device/inode/size/mtime, then `lstat` immediately before `unlink`; skip when the
type or identity changed. `inspect` counts eligible files without deleting.
`run` uses the 10-minute threshold by default and 24 hours when `automatic=True`.

- [ ] **Step 4: Verify generated-audio tests are GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_cleanup.py`

Expected: generated-audio and symlink tests pass.

- [ ] **Step 5: Add failing diagnostics, temp, partial-error, and TOCTOU tests**

Add tests that create:

```python
rotated = paths.watcher_log.with_suffix(".log.1")
rotated.write_bytes(b"old log")
age(rotated, cleanup.ROTATED_LOG_AGE_SECONDS + 1)

temporary = paths.hooks_dir / ".jarvis_line_audio_queue.json.1.2.tmp"
temporary.write_bytes(b"partial")
age(temporary, cleanup.TEMP_AGE_SECONDS + 1)
```

Assert both are removed, current logs and queue/state JSON remain, an unexpected
`tmp123` file remains, symlinks remain, and a monkeypatched `Path.unlink` failure
appears in `report.errors` while another candidate still deletes. Add a test
that swaps a candidate between scan and delete and asserts identity mismatch is
counted as skipped.

- [ ] **Step 6: Implement exact diagnostics and runtime-temp allowlists**

Recognize only:

```python
ROTATED_LOG_NAMES = (
    "jarvis_line_watcher.log.1",
    "jarvis_line_audio_worker.log.1",
)
ATOMIC_TARGET_NAMES = (
    "jarvis_line_config.json",
    "jarvis_line_audio_queue.json",
    "jarvis_line_latest_messages.json",
    ".jarvis_line_state.json",
    ".jarvis_line_cleanup_state.json",
    "jarvis_line_trace.jsonl",
)
STALE_LOCK_DIR_NAMES = (
    ".jarvis_line.lock.d",
    ".jarvis_line_audio.lock.d",
    ".jarvis_line_trace.lock.d",
)
```

An atomic temporary file matches only `f".{target}."` plus `.tmp`. A stale lock
directory must be an exact known name, older than one hour, empty, and not the
currently held cleanup lock. Bound `errors` to 50 while retaining `error_count`.
Report errors with category and basename only.

- [ ] **Step 7: Run cleanup tests and the full Python suite**

Run: `.venv/bin/python -m pytest -q tests/test_cleanup.py`

Run: `.venv/bin/python -m pytest -q`

Expected: cleanup tests pass; full suite passes with the existing sandbox-only
watcher lock test rerun outside the sandbox if required.

- [ ] **Step 8: Commit the cleanup engine**

```bash
git add src/jarvis_line/cleanup.py tests/test_cleanup.py
git commit -m "feat: add safe storage cleanup engine"
```

### Task 3: Add Non-Blocking Locking, Scheduling State, And Recognized Temp Names

**Files:**
- Modify: `tests/test_cleanup.py`
- Modify: `src/jarvis_line/cleanup.py`
- Modify: `tests/test_audio_worker.py`
- Modify: `src/jarvis_line/audio_worker.py`
- Modify: `tests/test_diagnostics.py`
- Modify: `src/jarvis_line/diagnostics.py`

**Interfaces:**
- Produces `run_if_due(config, paths=None, now=None) -> CleanupReport | None`
  with typed `Mapping[str, object]` input and optional `CleanupPaths`.
- A `CleanupReport` can set `already_running=True` without deleting.
- State JSON stores integer `last_attempt_ts` and `last_success_ts` only.

- [ ] **Step 1: Write failing due-state and concurrency tests**

Add tests equivalent to:

```python
def test_run_if_due_respects_enabled_interval_and_records_success(tmp_path):
    paths = paths_for(tmp_path)
    audio = paths.generated_audio_dir / "kokoro_old.wav"
    audio.write_bytes(b"x")
    age(audio, cleanup.AUTO_AUDIO_AGE_SECONDS + 1, now=200_000)

    first = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 24},
        paths,
        now=200_000,
    )
    second = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 24},
        paths,
        now=200_100,
    )

    assert first is not None and first.removed_files == 1
    assert second is None
    assert json.loads(paths.state_path.read_text()) == {
        "last_attempt_ts": 200_000,
        "last_success_ts": 200_000,
    }


def test_run_returns_already_running_without_waiting(tmp_path):
    paths = paths_for(tmp_path)
    paths.lock_dir.mkdir()
    (paths.lock_dir / "owner.json").write_text(
        json.dumps({"pid": os.getpid(), "created_ts": 200_000})
    )

    report = cleanup.run(paths, now=200_001)

    assert report.already_running is True
    assert report.removed_files == 0
```

Also test disabled cleanup, 168-hour scheduling, invalid intervals falling back
to 24 hours, partial failures advancing only `last_attempt_ts`, stale dead-owner
cleanup-lock recovery, and atomic state replacement.

- [ ] **Step 2: Run scheduling tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_cleanup.py -k 'due or running or state'`

Expected: FAIL because scheduling and lock APIs are absent.

- [ ] **Step 3: Implement non-blocking lock and bounded state**

Acquire the cleanup lock with atomic `lock_dir.mkdir()`, write `owner.json` with
PID and timestamp, and return immediately when a live owner exists. Recover only
when the directory is older than one hour and its recorded PID is not alive, or
when the directory is older than one hour and no valid owner record exists.
Implement `_pid_alive` with `os.kill(pid, 0)`, treating `PermissionError` as
alive and `ProcessLookupError` as dead. Always remove the owner file and
directory in `finally`.

Implement `run_if_due` as:

```python
def run_if_due(config, paths=None, now=None):
    if not _bool(config.get("cleanup_enabled"), True):
        return None
    interval = _interval_hours(config.get("cleanup_interval_hours")) * 3600
    paths = paths or CleanupPaths.default()
    now = time.time() if now is None else now
    state = _read_state(paths.state_path)
    if now - int(state.get("last_attempt_ts") or 0) < interval:
        return None
    return _run_with_lock(paths, now=now, automatic=True, update_state=True)
```

Inside the acquired lock, re-read state and due status before writing
`last_attempt_ts`. Write state atomically with a recognized
`.jarvis_line_cleanup_state.json.*.tmp` name. Advance `last_success_ts` only
when `error_count == 0`.

- [ ] **Step 4: Verify scheduling tests are GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_cleanup.py`

Expected: all cleanup tests pass.

- [ ] **Step 5: Write failing tests for recognizable atomic temp names**

In `test_audio_worker.py`, spy on `tempfile.NamedTemporaryFile` and assert
`save_json_unlocked` passes `prefix=".jarvis_line_audio_queue.json."` and
`suffix=".tmp"` for the queue path. In `test_diagnostics.py`, force trace trim
and assert its temporary file uses `prefix=".jarvis_line_trace.jsonl."` and
`suffix=".tmp"`.

- [ ] **Step 6: Run the temp-name tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_audio_worker.py tests/test_diagnostics.py -k 'temporary or temp_name'`

Expected: FAIL because current `NamedTemporaryFile` calls use random default names.

- [ ] **Step 7: Prefix atomic temp files**

Change both calls to:

```python
tempfile.NamedTemporaryFile(
    mode,
    encoding=encoding,
    dir=path.parent,
    prefix=f".{path.name}.",
    suffix=".tmp",
    delete=False,
)
```

Use the binary equivalent without `encoding` for trace trimming.

- [ ] **Step 8: Run focused and full Python tests**

Run: `.venv/bin/python -m pytest -q tests/test_cleanup.py tests/test_audio_worker.py tests/test_diagnostics.py`

Run: `.venv/bin/python -m pytest -q`

Expected: all tests pass, subject only to the documented sandbox lock rerun.

- [ ] **Step 9: Commit scheduling and temp naming**

```bash
git add src/jarvis_line/cleanup.py src/jarvis_line/audio_worker.py
git add src/jarvis_line/diagnostics.py tests/test_cleanup.py
git add tests/test_audio_worker.py tests/test_diagnostics.py
git commit -m "feat: schedule bounded automatic cleanup"
```

### Task 4: Expose Cleanup Through The CLI And Watcher

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/jarvis_line/cli.py`
- Modify: `tests/test_watcher.py`
- Modify: `src/jarvis_line/watcher.py`
- Modify: `tests/run_smoke.py`

**Interfaces:**
- Produces CLI commands `cleanup status [--json]` and `cleanup run [--json]`.
- Produces watcher helper `maybe_run_cleanup(last_check_monotonic: float, now_monotonic: float | None = None) -> float`.

- [ ] **Step 1: Write failing CLI parser and output tests**

Add tests that monkeypatch `cleanup.inspect` and `cleanup.run` with a fixed
`CleanupReport`, then assert:

```python
args = cli.build_parser().parse_args(["cleanup", "status", "--json"])
assert args.func is cli.cleanup_command
assert args.cleanup_command == "status"
assert args.json_output is True
```

For JSON, assert `json.loads(stdout)` equals `report.to_dict()`. For text, assert
the output contains `Eligible: 4 files`, `Reclaimable: 48.0 MB`, and the last
success. Assert partial errors return `1`; already-running returns `0` with a
clear no-action message. Add config-set tests that reject non-boolean
`cleanup_enabled` and intervals outside `24` or `168` before saving.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_cli.py -k cleanup`

Expected: FAIL because the cleanup parser and handler do not exist.

- [ ] **Step 3: Implement the CLI contract**

Import `cleanup`, add one handler, and register the subcommands:

```python
cleanup_parser = sub.add_parser("cleanup", help="Inspect or remove safe runtime artifacts.")
cleanup_sub = cleanup_parser.add_subparsers(dest="cleanup_command", required=True)
for name in ("status", "run"):
    command = cleanup_sub.add_parser(name)
    command.add_argument("--json", action="store_true", dest="json_output")
    command.set_defaults(func=cleanup_command)
```

`cleanup_command` selects `cleanup.inspect()` or `cleanup.run()`, prints
`report.to_dict()` for JSON, prints byte totals with `format_bytes` for humans,
returns `1` only when `error_count > 0`, and treats `already_running` as a safe
no-op. Validate the two config keys before `save_json`.

- [ ] **Step 4: Verify CLI tests are GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_cli.py -k cleanup`

Expected: cleanup CLI tests pass.

- [ ] **Step 5: Write failing watcher gate tests**

Add:

```python
def test_maybe_run_cleanup_uses_hourly_memory_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"cleanup_enabled": True})
    monkeypatch.setattr(
        watcher.cleanup,
        "run_if_due",
        lambda cfg: calls.append(cfg) or None,
    )

    checked = watcher.maybe_run_cleanup(0.0, now_monotonic=100.0)
    checked = watcher.maybe_run_cleanup(checked, now_monotonic=200.0)
    checked = watcher.maybe_run_cleanup(checked, now_monotonic=3_701.0)

    assert len(calls) == 2
    assert checked == 3_701.0
```

Also assert cleanup exceptions are logged by class/count only and do not escape.

- [ ] **Step 6: Run watcher tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_watcher.py -k cleanup`

Expected: FAIL because the watcher gate does not exist.

- [ ] **Step 7: Implement and call the watcher gate**

Import `cleanup`, define `CLEANUP_CHECK_GATE_SECONDS = 60 * 60`, and implement
`maybe_run_cleanup`. Log only mode, removed count, reclaimed bytes, and error
count when a run occurs. Call it once before each watch loop and again from the
loop using the returned monotonic timestamp. Never call it from `process_line`,
queueing, synthesis, or playback.

- [ ] **Step 8: Extend smoke coverage and run focused tests**

Add parser coverage for both cleanup commands to `tests/run_smoke.py` without
touching real home files.

Run: `.venv/bin/python -m pytest -q tests/test_cli.py tests/test_watcher.py tests/test_cleanup.py`

Run: `PYTHONPATH=src .venv/bin/python tests/run_smoke.py`

Expected: all focused and smoke tests pass.

- [ ] **Step 9: Commit CLI and watcher integration**

```bash
git add src/jarvis_line/cli.py src/jarvis_line/watcher.py tests/test_cli.py tests/test_watcher.py tests/run_smoke.py
git commit -m "feat: expose cleanup in cli and watcher"
```

### Task 5: Add macOS Cleanup Status And Diagnostics Controls

**Files:**
- Create: `apps/macos/JarvisLine/Sources/StorageCleanup.swift`
- Create: `apps/macos/JarvisLine/Tests/JarvisLineTests/StorageCleanupTests.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`
- Modify: `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`

**Interfaces:**
- Produces `StorageCleanupStatus: Decodable, Equatable`.
- Produces model state `cleanupStatus`, `cleanupResultText`, and actions `refreshCleanupStatus()` and `cleanStorage()`.
- Diagnostics binds automatic cleanup settings through `JarvisConfigDraft` and
  invokes CLI JSON commands through `JarvisLineCommandRunning`.

- [ ] **Step 1: Write failing status decoder tests**

Create `StorageCleanupTests.swift`:

```swift
import Testing
@testable import JarvisLine

struct StorageCleanupTests {
    @Test func decodesCleanupJSONAndFormatsStorage() throws {
        let status = try StorageCleanupStatus.decode(#"""
        {
          "mode":"status",
          "eligible_files":4,
          "eligible_bytes":50331648,
          "removed_files":0,
          "removed_bytes":0,
          "skipped_files":1,
          "error_count":0,
          "errors":[],
          "already_running":false,
          "last_success_at":null,
          "categories":{}
        }
        """#)

        #expect(status.eligibleFiles == 4)
        #expect(status.reclaimableText == "48 MB")
        #expect(status.lastSuccessText == "Never")
    }
}
```

- [ ] **Step 2: Run Swift test and verify RED**

Run: `swift test --package-path apps/macos/JarvisLine --filter StorageCleanupTests`

Expected: compile failure because `StorageCleanupStatus` does not exist, or the
documented local compiler/SDK mismatch before test compilation.

- [ ] **Step 3: Implement the cleanup status value type**

Create a decodable struct with snake-case coding keys, `.empty`, a strict
`decode(_:)` helper, and native formatting:

```swift
var reclaimableText: String {
    ByteCountFormatter.string(fromByteCount: Int64(eligibleBytes), countStyle: .file)
}

var lastSuccessText: String {
    guard let timestamp = lastSuccessAt else { return "Never" }
    return Date(timeIntervalSince1970: TimeInterval(timestamp))
        .formatted(date: .abbreviated, time: .shortened)
}
```

- [ ] **Step 4: Write failing model command tests**

Add tests with a runner that returns cleanup JSON for matching arguments:

```swift
@Test func cleanupStatusAndRunUseDedicatedJSONCommands() async {
    let runner = CleanupModelRunner()
    let model = JarvisLineModel(cli: runner)

    await model.refreshCleanupStatus()
    await model.cleanStorage()

    #expect(await runner.calls == [
        ["cleanup", "status", "--json"],
        ["cleanup", "run", "--json"],
        ["cleanup", "status", "--json"],
    ])
    #expect(model.cleanupStatus.eligibleFiles == 0)
    #expect(model.cleanupResultText == "12 files removed, 48 MB recovered")
}
```

- [ ] **Step 5: Run model test and verify RED**

Run: `swift test --package-path apps/macos/JarvisLine --filter cleanupStatusAndRunUseDedicatedJSONCommands`

Expected: compile failure because model cleanup state/actions do not exist.

- [ ] **Step 6: Add model state and commands**

Add published state:

```swift
@Published private(set) var cleanupStatus = StorageCleanupStatus.empty
@Published private(set) var cleanupResultText = "Not checked"
```

`refreshCleanupStatus()` runs `cleanup status --json`, decodes it, and leaves
ordinary runtime status untouched on parse failure. `cleanStorage()` runs
`cleanup run --json`, accepts decodable stdout from a partial `CLIError`, updates
the result text, then refreshes status. Both use the existing `run` busy/error
boundary and never access files directly.

- [ ] **Step 7: Add the Diagnostics Storage & Cleanup group**

Add rows for:

```swift
Toggle("Automatic cleanup", isOn: $model.config.cleanupEnabled)

Picker("Frequency", selection: $model.config.cleanupIntervalHours) {
    Text("Daily").tag(24)
    Text("Weekly").tag(168)
}
.disabled(!model.config.cleanupEnabled)
```

Show last success and reclaimable storage with `SettingsValueRow`. Add icon
buttons for refresh and **Clean Now**, disable commands while `model.isBusy`,
and call `refreshCleanupStatus()` when the selected destination becomes
`.diagnostics`. Keep the section unframed and aligned with existing settings
rows; do not expose paths or free-form values.

- [ ] **Step 8: Run Swift tests and builds**

Run when the local toolchain permits:

```bash
swift test --package-path apps/macos/JarvisLine
swift build -c debug --package-path apps/macos/JarvisLine
swift build -c release --package-path apps/macos/JarvisLine
```

Expected: all Swift tests and both builds pass. If the compiler/SDK installation
remains mismatched, preserve the exact failure and require GitHub macOS CI to
pass before merge.

- [ ] **Step 9: Commit the macOS controls**

```bash
git add apps/macos/JarvisLine/Sources/StorageCleanup.swift
git add apps/macos/JarvisLine/Sources/JarvisConfig.swift
git add apps/macos/JarvisLine/Sources/SettingsState.swift
git add apps/macos/JarvisLine/Sources/JarvisLineApp.swift
git add apps/macos/JarvisLine/Sources/SettingsWindowView.swift
git add apps/macos/JarvisLine/Tests/JarvisLineTests/StorageCleanupTests.swift
git add apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisConfigContractTests.swift
git add apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift
git add apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift
git commit -m "feat: manage cleanup from macos diagnostics"
```

### Task 6: Document, Audit, Package, Install, And Deliver The Feature Branch

**Files:**
- Modify: `docs/COMMANDS.md`
- Modify: `docs/CONFIGURATION.md`
- Modify: `apps/macos/JarvisLine/README.md`
- Modify: `README.md` only if the existing concise feature list needs one link-sized mention

**Interfaces:**
- Documents exact cleanup commands, output shape, defaults, exclusions, and app controls.
- Produces a locally installed app and CLI from the verified feature branch without publishing a release yet.

- [ ] **Step 1: Add command and configuration documentation**

Document:

```bash
jarvis-line cleanup status
jarvis-line cleanup run
jarvis-line cleanup status --json
jarvis-line cleanup run --json
```

Include human output:

```text
Jarvis Line cleanup status
Eligible: 4 files
Reclaimable: 48.0 MB
Last successful cleanup: never
```

Add `cleanup_enabled = true` and `cleanup_interval_hours = 24` to the common
settings table and default JSON. State explicitly that models, config, hooks,
queue/state/cache, current logs/trace, custom output paths, and user support
reports are excluded. Mention the Diagnostics controls in the app README.

- [ ] **Step 2: Run documentation and static checks**

Run:

```bash
git diff --check
.venv/bin/python -m compileall -q src/jarvis_line
.venv/bin/python scripts/check_version_consistency.py
```

Expected: no whitespace, syntax, or version consistency errors.

- [ ] **Step 3: Run the complete Python and smoke matrix locally**

Run:

```bash
.venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python tests/run_smoke.py
```

If the sandbox blocks `~/.codex/hooks/.jarvis_line.lock`, rerun only the affected
test with real local permissions, then run the whole suite in CI.

- [ ] **Step 4: Perform focused security review**

Review the diff for path traversal, symlink following, TOCTOU identity checks,
unbounded scans/results, unsafe recursive deletion, lock recovery, output path
leaks, and cleanup failures escaping into watcher control flow. Run:

```bash
.venv/bin/python -m pytest -q tests/test_cleanup.py
git diff --check develop...HEAD
```

Expected: security tests pass and no unsafe deletion surface remains.

- [ ] **Step 5: Build and verify macOS artifacts**

Run when the toolchain permits:

```bash
swift test --package-path apps/macos/JarvisLine
bash scripts/verify-macos-artifacts.sh
```

Expected: Swift tests pass and the app/DMG artifacts verify. If local CLT remains
mismatched, do not claim local Swift verification; require the GitHub macOS job.

- [ ] **Step 6: Install and smoke-test the local build**

After successful packaging, replace `/Applications/Jarvis Line.app` with the
new package using the existing package/install flow, ensure only one app
instance runs, open Diagnostics, verify status preview and Clean Now, and run a
real `jarvis-line tts test`. Do not delete user models, config, or reports during
the test.

- [ ] **Step 7: Commit documentation and final fixes**

```bash
git add docs/COMMANDS.md docs/CONFIGURATION.md apps/macos/JarvisLine/README.md README.md
git commit -m "docs: explain storage cleanup"
```

Stage only files actually changed.

- [ ] **Step 8: Push the feature branch and open the develop PR**

```bash
git push -u origin feature/storage-cleanup
gh pr create --base develop --head feature/storage-cleanup \
  --title "feat: add bounded storage cleanup" \
  --body "Adds allowlisted cleanup, automatic scheduling, CLI controls, and macOS Diagnostics management."
gh pr checks --watch
```

Expected: all Linux, macOS, Windows, security, and artifact checks pass before
merge. Address failures on the feature branch, merge into `develop`, delete the
feature branch, then open a separate `develop` to `main` PR only when requested
for release promotion.
