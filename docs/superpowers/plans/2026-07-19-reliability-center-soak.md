# Reliability Center And Runtime Soak Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-safe Reliability Center with explicit bounded recovery actions, then verify shared runtime invariants under deterministic quick and extended soak loads.

**Architecture:** Python owns a versioned diagnostics snapshot and recovery contract; Swift decodes and presents it only when requested. The soak runner uses the same queue-policy, file-lock, trace, and diagnostics boundaries inside an isolated temporary environment with fake speech, so normal runtime gains no daemon or polling process.

**Tech Stack:** Python 3.10+, stdlib `argparse`/`json`/`tempfile`/`threading`, pytest, Swift 5.9+, SwiftUI, Swift Testing, GitHub Actions.

## Global Constraints

- Diagnostics contract version is exactly `1`.
- Snapshot and soak output must omit spoken text, transcript text, session paths, tool arguments, answers, environment variables, custom commands, and API keys.
- Recovery actions are allowlisted to `restart-runtime`, `prune-expired`, and `test-tts`.
- `prune-expired` may remove only jobs rejected by the existing explicit-expiry or 90-second stale-job policy.
- No new daemon, local server, persistent helper, or hidden polling loop.
- The macOS view refreshes on appearance, manual refresh, and completed recovery only.
- Soak execution must use an isolated temporary runtime and fake speech; it must not touch the user's active home, queue, processes, config, or audio device.
- Existing Python, Swift, smoke, clean-install, security, and packaging checks remain required.

---

## File Map

- Create `src/jarvis_line/reliability.py`: pure snapshot, delivery correlation, recommendation, and queue-pruning domain logic.
- Modify `src/jarvis_line/audio_worker.py`: add a bounded non-blocking lock helper reusable by recovery.
- Modify `src/jarvis_line/cli.py`: expose diagnostics snapshot and recovery machine commands.
- Create `tests/test_reliability.py`: domain and privacy tests.
- Modify `tests/test_cli.py`: diagnostics command routing and recovery orchestration tests.
- Create `apps/macos/JarvisLine/Sources/ReliabilityContract.swift`: versioned Codable snapshot/action types.
- Modify `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`: Reliability Center model state and CLI calls.
- Modify `apps/macos/JarvisLine/Sources/RuntimeDiagnostics.swift`: status-first Reliability Center components.
- Modify `apps/macos/JarvisLine/Sources/SettingsState.swift`: user-facing Reliability destination copy.
- Modify `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`: replace broad runtime controls with bounded recovery UI.
- Create `apps/macos/JarvisLine/Tests/JarvisLineTests/ReliabilityContractTests.swift`: decoding and unsupported-version tests.
- Modify `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift`: model command/action tests.
- Modify `apps/macos/JarvisLine/Tests/JarvisLineTests/RuntimeDiagnosticsTests.swift`: health and delivery presentation tests.
- Modify `apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift`: destination copy tests.
- Create `src/jarvis_line/soak.py`: deterministic isolated scenario runner and report builder.
- Create `scripts/soak_runtime.py`: command-line entry point for quick/extended modes.
- Create `tests/test_soak.py`: deterministic invariant, isolation, and privacy tests.
- Modify `.github/workflows/ci.yml`: run quick soak once per operating system on Python 3.12.
- Create `.github/workflows/soak.yml`: scheduled/manual extended soak with report artifacts.
- Modify `README.md`, `docs/COMMANDS.md`, `docs/SUPPORT-MATRIX.md`, `CONTRIBUTING.md`, `PRIVACY.md`, and `CHANGELOG.md`: user and contributor documentation.

---

### Task 1: Versioned Diagnostics Snapshot Domain

**Files:**
- Create: `src/jarvis_line/reliability.py`
- Create: `tests/test_reliability.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: trace dictionaries produced by `diagnostics.read_events()`, persisted runtime `state`, persisted `queue`, effective config, `pid_alive(pid)`, and `process_rss_mb(pid)`.
- Produces: `SNAPSHOT_VERSION = 1`, `build_snapshot(...) -> dict[str, Any]`, `correlate_deliveries(events, limit=12) -> list[dict[str, Any]]`, `classify_queue(jobs, now_ms, stale_after_ms) -> dict[str, Any]`, and `prune_expired_jobs(jobs, now_ms, stale_after_ms) -> tuple[list[dict[str, Any]], int]`.

- [ ] **Step 1: Write failing snapshot and privacy tests**

```python
from jarvis_line import reliability


def test_snapshot_correlates_delivery_without_content():
    snapshot = reliability.build_snapshot(
        config={"tts": "system", "speech_enabled": True, "audio_worker_idle_exit_seconds": 60},
        state={"__watcher__": {"pid": 11}, "__audio_worker__": {"pid": 12}},
        queue={"jobs": []},
        trace_events=[
            {"ts_ms": 100, "event": "queued", "message_id": "m1", "session_id": "abc", "phase": "final", "line": "secret"},
            {"ts_ms": 140, "event": "completed", "message_id": "m1", "session_id": "abc", "phase": "final", "duration_ms": 30},
        ],
        now_ms=200,
        pid_alive=lambda pid: pid in {11, 12},
        process_rss_mb=lambda pid: 84.0,
        tts_status={"backend": "system", "ready": True, "detail": "ready"},
    )

    assert snapshot["version"] == 1
    assert snapshot["health"] == "healthy"
    assert snapshot["deliveries"][0]["state"] == "completed"
    assert "line" not in str(snapshot)
    assert "secret" not in str(snapshot)
```

Add named tests `test_snapshot_requires_action_when_watcher_is_stopped`,
`test_snapshot_accepts_expected_idle_worker`,
`test_classify_queue_counts_expired_stale_and_phases`,
`test_snapshot_recommendations_use_allowlisted_actions`,
`test_classify_queue_ignores_malformed_jobs`, and
`test_correlate_deliveries_keeps_only_the_requested_limit`. Each assertion uses
fixed timestamps and exact dictionaries so no wall-clock behavior enters the
domain tests.

- [ ] **Step 2: Run the new tests and verify failure**

Run: `python -m pytest tests/test_reliability.py -q`

Expected: FAIL because `jarvis_line.reliability` does not exist.

- [ ] **Step 3: Implement the pure snapshot domain**

```python
SNAPSHOT_VERSION = 1
HEALTH_VALUES = {"healthy", "degraded", "action_required"}
TERMINAL_EVENTS = {"completed", "failed", "skipped"}
SAFE_DELIVERY_KEYS = {
    "message_id", "session_id", "phase", "state", "backend", "reason",
    "received_ts_ms", "updated_ts_ms", "queue_delay_ms", "duration_ms",
}


def prune_expired_jobs(jobs, now_ms, stale_after_ms):
    active = []
    removed = 0
    for raw_job in jobs:
        job = raw_job if isinstance(raw_job, dict) else {}
        enqueued = int(job.get("enqueued_ts_ms") or 0)
        expires = int(job.get("expires_ts_ms") or 0)
        if (expires and expires <= now_ms) or enqueued < now_ms - stale_after_ms:
            removed += 1
        else:
            active.append(dict(job))
    return active, removed
```

Build deliveries by message ID, copy only explicitly safe keys, choose the latest
lifecycle state, calculate queue/runtime facts, and derive stable recommendations
such as `runtime-restart` and `expired-queue` without performing actions.

- [ ] **Step 4: Run snapshot and existing diagnostics tests**

Run: `python -m pytest tests/test_reliability.py tests/test_diagnostics.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit the snapshot domain**

```bash
git add src/jarvis_line/reliability.py tests/test_reliability.py
git commit -m "feat: add reliability snapshot contract"
```

---

### Task 2: Lock-Safe Recovery And CLI Machine Contract

**Files:**
- Modify: `src/jarvis_line/audio_worker.py`
- Modify: `src/jarvis_line/cli.py`
- Modify: `tests/test_audio_worker.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 `build_snapshot()` and `prune_expired_jobs()`.
- Produces: `try_file_lock(path) -> ContextManager[bool]`, `reliability_snapshot() -> dict[str, Any]`, `diagnostics_snapshot_command(args) -> int`, and `diagnostics_recover_command(args) -> int`.

- [ ] **Step 1: Write failing lock and CLI tests**

```python
def test_prune_expired_recovery_preserves_active_jobs(tmp_path, monkeypatch, capsys):
    now_ms = 1_000_000
    configure_runtime_paths(tmp_path, monkeypatch)
    cli.save_json(cli.QUEUE_PATH, {"jobs": [
        {"message_id": "expired", "enqueued_ts_ms": now_ms - 1, "expires_ts_ms": now_ms},
        {"message_id": "active", "enqueued_ts_ms": now_ms, "expires_ts_ms": now_ms + 10_000},
    ]})
    monkeypatch.setattr(cli.time, "time", lambda: now_ms / 1000)

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="prune-expired", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["changed"] is True
    assert [job["message_id"] for job in cli.load_json(cli.QUEUE_PATH, {})["jobs"]] == ["active"]
```

Add parser tests for `diagnostics snapshot --json`, all three allowlisted actions,
an unsupported action, busy lock behavior, fixed TTS test text, restart delegation,
and JSON output on both success and failure.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/test_audio_worker.py tests/test_cli.py -q`

Expected: FAIL because the diagnostics commands and bounded lock do not exist.

- [ ] **Step 3: Add a non-blocking queue lock helper**

```python
@contextmanager
def try_file_lock(path: Path):
    """Yield False immediately when another runtime writer owns the lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        lock_dir = path.with_name(path.name + ".d")
        try:
            lock_dir.mkdir()
        except FileExistsError:
            yield False
            return
        try:
            yield True
        finally:
            try:
                lock_dir.rmdir()
            except OSError:
                pass
        return

    with path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
```

Do not change existing blocking `file_lock()` semantics. Recovery uses only the
new helper, returns a busy result, and never waits behind audio playback.

- [ ] **Step 4: Add snapshot/recovery orchestration and parser routes**

```python
diagnostics_parser = sub.add_parser(
    "diagnostics", help="Inspect reliability and run bounded recovery actions."
)
diagnostics_sub = diagnostics_parser.add_subparsers(dest="diagnostics_command", required=True)
snapshot_parser = diagnostics_sub.add_parser("snapshot")
snapshot_parser.add_argument("--json", action="store_true", dest="json_output")
snapshot_parser.set_defaults(func=diagnostics_snapshot_command)
recover_parser = diagnostics_sub.add_parser("recover")
recover_parser.add_argument(
    "action", choices=("restart-runtime", "prune-expired", "test-tts")
)
recover_parser.add_argument("--json", action="store_true", dest="json_output")
recover_parser.set_defaults(func=diagnostics_recover_command)
```

`test-tts` must call `tts_test()` with exactly `Jarvis line test is ready.` and
quiet command output. `restart-runtime` delegates to `runtime_restart()`.
`prune-expired` locks and atomically writes only when at least one rejected job
exists. Each result contains a fresh snapshot.

- [ ] **Step 5: Run focused Python tests**

Run: `python -m pytest tests/test_reliability.py tests/test_audio_worker.py tests/test_cli.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit the CLI contract**

```bash
git add src/jarvis_line/audio_worker.py src/jarvis_line/cli.py tests/test_audio_worker.py tests/test_cli.py
git commit -m "feat: add bounded reliability recovery commands"
```

---

### Task 3: Swift Reliability Contract And Model

**Files:**
- Create: `apps/macos/JarvisLine/Sources/ReliabilityContract.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`
- Create: `apps/macos/JarvisLine/Tests/JarvisLineTests/ReliabilityContractTests.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift`

**Interfaces:**
- Consumes: Task 2 diagnostics JSON.
- Produces: `ReliabilitySnapshot.decode(_:)`, `ReliabilityRecoveryResult.decode(_:)`, `ReliabilityAction`, `JarvisLineModel.refreshReliability()`, and `JarvisLineModel.runReliabilityAction(_:)`.

- [ ] **Step 1: Write failing Swift decoding tests**

```swift
@Test func snapshotDecodesVersionOneAndRejectsOtherVersions() throws {
    let snapshot = try ReliabilitySnapshot.decode(#"{"version":1,"generated_at_ms":1,"health":"healthy","runtime":{},"queue":{},"tts":{},"deliveries":[],"recommendations":[]}"#)
    #expect(snapshot.health == .healthy)
    #expect(throws: ReliabilityContractError.self) {
        try ReliabilitySnapshot.decode(#"{"version":2,"generated_at_ms":1,"health":"healthy","runtime":{},"queue":{},"tts":{},"deliveries":[],"recommendations":[]}"#)
    }
}
```

Add named tests `snapshotDecodesOptionalRuntimeFields`,
`snapshotDoesNotExposeUnknownRecoveryAction`,
`recoveryResultDecodesAllControlledActions`, and
`snapshotRejectsMalformedJSON`. Unknown recommendation identifiers remain
displayable text but produce `nil` from their `executableAction` property.

- [ ] **Step 2: Run Swift tests and verify failure**

Run: `swift test --package-path apps/macos/JarvisLine --filter ReliabilityContractTests`

Expected: compile failure because the contract types do not exist.

- [ ] **Step 3: Implement strict Codable contract types**

```swift
enum ReliabilityHealth: String, Codable { case healthy, degraded, actionRequired = "action_required" }
enum ReliabilityAction: String, Codable, CaseIterable {
    case restartRuntime = "restart-runtime"
    case pruneExpired = "prune-expired"
    case testTTS = "test-tts"
}

struct ReliabilitySnapshot: Decodable, Equatable {
    static let supportedVersion = 1
    let version: Int
    let generatedAtMS: Int
    let health: ReliabilityHealth
    let runtime: ReliabilityRuntime
    let queue: ReliabilityQueue
    let tts: ReliabilityTTS
    let deliveries: [ReliabilityDelivery]
    let recommendations: [ReliabilityRecommendation]
}
```

Reject unsupported versions before publishing state. Unknown optional reason or
event strings remain displayable as safe metadata; unknown action values must
not become executable buttons.

- [ ] **Step 4: Add on-demand model refresh and action execution**

```swift
@Published private(set) var reliabilitySnapshot = ReliabilitySnapshot.empty
@Published private(set) var reliabilityResultText = "Not checked"

func refreshReliability() async {
    await run(label: "Refresh Reliability") {
        reliabilitySnapshot = try ReliabilitySnapshot.decode(
            try await cli.run(["diagnostics", "snapshot", "--json"])
        )
    }
}

func runReliabilityAction(_ action: ReliabilityAction) async {
    await run(label: action.label) {
        let result = try ReliabilityRecoveryResult.decode(
            try await cli.run(["diagnostics", "recover", action.rawValue, "--json"])
        )
        reliabilitySnapshot = result.snapshot
        reliabilityResultText = result.summary
    }
}
```

Do not start timers. Preserve the existing global `isBusy` serialization and
surface decode/CLI failures through `errorMessage`.

- [ ] **Step 5: Test model command routing and busy behavior**

Run: `swift test --package-path apps/macos/JarvisLine --filter Reliability`

Expected: all Reliability contract and model tests PASS.

- [ ] **Step 6: Commit the Swift contract/model**

```bash
git add apps/macos/JarvisLine/Sources/ReliabilityContract.swift apps/macos/JarvisLine/Sources/JarvisLineApp.swift apps/macos/JarvisLine/Tests/JarvisLineTests/ReliabilityContractTests.swift apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisLineModelTests.swift
git commit -m "feat: connect macOS app to reliability contract"
```

---

### Task 4: Status-First Reliability Center UI

**Files:**
- Modify: `apps/macos/JarvisLine/Sources/RuntimeDiagnostics.swift`
- Modify: `apps/macos/JarvisLine/Sources/SettingsState.swift`
- Modify: `apps/macos/JarvisLine/Sources/SettingsWindowView.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/RuntimeDiagnosticsTests.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift`

**Interfaces:**
- Consumes: Task 3 model state and actions.
- Produces: `ReliabilityCenterView`, health/metric/delivery/recovery presentation helpers, and a Diagnostics sidebar destination titled `Reliability`.

- [ ] **Step 1: Write failing presentation tests**

```swift
@Test func reliabilityPresentationExplainsSkippedDelivery() {
    let delivery = ReliabilityDelivery(
        messageID: "m1", sessionID: "abc", phase: "final",
        state: "skipped", backend: nil, reason: "quiet_hours",
        receivedAtMS: 1, updatedAtMS: 2, queueDelayMS: nil, durationMS: nil
    )
    #expect(ReliabilityPresentation.deliveryDetail(delivery) == "Skipped · Quiet hours")
}
```

Update destination tests to expect `Reliability` and `Runtime health and safe
recovery`. Add `healthPresentationUsesSemanticState` for all three health
values and `recoveryLabelsMatchControlledActions` for the three fixed labels;
these remain pure presentation tests and do not require view snapshots.

- [ ] **Step 2: Run focused Swift tests and verify failure**

Run: `swift test --package-path apps/macos/JarvisLine --filter RuntimeDiagnosticsTests`

Expected: FAIL because the Reliability presentation does not exist.

- [ ] **Step 3: Build the status-first view**

Replace the broad Runtime Controls and Recent Activity sections with:

```swift
ReliabilityCenterView(
    snapshot: model.reliabilitySnapshot,
    resultText: model.reliabilityResultText,
    isBusy: model.isBusy,
    onRefresh: { Task { await model.refreshReliability() } },
    onAction: { action in Task { await model.runReliabilityAction(action) } }
)
```

Use a compact health header, stable two-column metric rows, bounded recent
deliveries, recommendation-driven buttons, a secondary TTS test icon button,
and progressive disclosure for doctor details. Keep Storage & Cleanup as its
own section. Remove `Clear Queue` from the window; full queue clearing remains
CLI-only. Start/stop controls remain available from the menu-bar panel, while
restart appears here only when recommended and confirmed.

- [ ] **Step 4: Wire appearance refresh and restart confirmation**

When destination changes to `.diagnostics`, request cleanup status and call
`refreshReliability()`. Use SwiftUI confirmation for `restartRuntime`; pruning
and fixed TTS testing run directly. Do not add `.timer`, polling, or task loops.

- [ ] **Step 5: Run all Swift tests**

Run: `swift test --package-path apps/macos/JarvisLine`

Expected: all tests PASS.

- [ ] **Step 6: Commit the Reliability Center UI**

```bash
git add apps/macos/JarvisLine/Sources/RuntimeDiagnostics.swift apps/macos/JarvisLine/Sources/SettingsState.swift apps/macos/JarvisLine/Sources/SettingsWindowView.swift apps/macos/JarvisLine/Tests/JarvisLineTests/RuntimeDiagnosticsTests.swift apps/macos/JarvisLine/Tests/JarvisLineTests/SettingsStateTests.swift
git commit -m "feat: add macOS reliability center"
```

---

### Task 5: Deterministic Isolated Soak Harness

**Files:**
- Create: `src/jarvis_line/soak.py`
- Create: `scripts/soak_runtime.py`
- Create: `tests/test_soak.py`

**Interfaces:**
- Consumes: queue policy scheduling/dequeueing, audio-worker JSON locking, diagnostics trace writes, and Task 1 snapshot/pruning functions.
- Produces: `SoakConfig.for_mode(mode, seed)`, `run_soak(config) -> dict[str, Any]`, and script options `--mode`, `--seed`, `--json`, and `--output`.

- [ ] **Step 1: Write failing deterministic/isolation tests**

```python
def test_quick_soak_is_deterministic_private_and_passes(tmp_path):
    config = soak.SoakConfig.for_mode("quick", seed=7, root=tmp_path)
    first = soak.run_soak(config)
    second = soak.run_soak(config)

    assert first["ok"] is True
    assert first["metrics"] == second["metrics"]
    assert first["invariants"] == second["invariants"]
    assert "line" not in json.dumps(first)
    assert "text" not in json.dumps(first)
```

Also assert queue bounds, terminal uniqueness, final outcomes, no expired
playback, active-job preservation, trace rotation, no files outside `root`, and
no leftover child process IDs.

- [ ] **Step 2: Run soak tests and verify failure**

Run: `python -m pytest tests/test_soak.py -q`

Expected: FAIL because the soak module and script do not exist.

- [ ] **Step 3: Implement deterministic scenario generation**

```python
@dataclass(frozen=True)
class SoakConfig:
    mode: str
    seed: int
    sessions: int
    rounds: int
    max_queue_size: int
    root: Path

    @classmethod
    def for_mode(cls, mode, seed, root=None):
        values = {"quick": (24, 12), "extended": (128, 100)}
        sessions, rounds = values[mode]
        return cls(mode, seed, sessions, rounds, 8, root or Path(tempfile.mkdtemp()))
```

Generate commentary/final/attention jobs with a seeded RNG, schedule and drain
through production queue-policy functions, write correlated lifecycle events,
exercise lock-backed JSON mutations from bounded threads, request snapshots
during activity, simulate idle/RSS exits through explicit runtime state, and
record only aggregate metadata.

- [ ] **Step 4: Implement hard invariants and report schema**

Return version `1`, mode, seed, elapsed milliseconds, aggregate metrics,
per-invariant booleans, failures, and an `ok` aggregate. Ensure report keys are
allowlisted and scan serialized output for diagnostic forbidden fields before
returning success.

- [ ] **Step 5: Add the script entry point and output file support**

```python
parser.add_argument("--mode", choices=("quick", "extended"), default="quick")
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--json", action="store_true", dest="json_output")
parser.add_argument("--output", type=Path)
```

Exit `0` only when every invariant passes, `1` for a completed failing run, and
`2` for invalid arguments. Write output atomically when `--output` is supplied.

- [ ] **Step 6: Run quick and extended local checks**

Run: `python scripts/soak_runtime.py --mode quick --seed 1 --json`

Expected: JSON with `"ok": true`.

Run: `python scripts/soak_runtime.py --mode extended --seed 1 --json`

Expected: JSON with `"ok": true`, bounded queue depth, and no invariant failures.

- [ ] **Step 7: Commit the soak harness**

```bash
git add src/jarvis_line/soak.py scripts/soak_runtime.py tests/test_soak.py
git commit -m "test: add deterministic runtime soak harness"
```

---

### Task 6: CI, Documentation, Full Verification, And Delivery

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/soak.yml`
- Modify: `README.md`
- Modify: `docs/COMMANDS.md`
- Modify: `docs/SUPPORT-MATRIX.md`
- Modify: `CONTRIBUTING.md`
- Modify: `PRIVACY.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: cross-platform quick soak evidence, scheduled/manual extended reports, concise user documentation, and a PR-ready feature branch.

- [ ] **Step 1: Add quick soak to the existing CI matrix**

After pytest, run only on Python 3.12 to avoid multiplying equivalent work:

```yaml
- name: Quick runtime soak
  if: matrix.python-version == '3.12'
  run: python scripts/soak_runtime.py --mode quick --seed 1 --json
  env:
    PYTHONPATH: src
```

- [ ] **Step 2: Add scheduled/manual extended soak workflow**

Use `workflow_dispatch` plus a weekly schedule, a macOS/Ubuntu/Windows matrix on
Python 3.12, `timeout-minutes: 15`, pinned checkout/setup-python/upload-artifact
actions matching existing workflow pins, and:

```yaml
- name: Extended runtime soak
  run: python scripts/soak_runtime.py --mode extended --seed 1 --output soak-report.json
  env:
    PYTHONPATH: src
```

Upload one seven-day `soak-report-${{ matrix.os }}` artifact per operating
system even when the run fails.

- [ ] **Step 3: Update focused user and contributor documentation**

Document:

- `jarvis-line diagnostics snapshot --json`;
- each bounded recovery action and its output shape;
- no content retention and no automatic repair;
- quick and extended soak commands and what they prove;
- the remaining real-device and notarization Preview limits.

Keep README changes to one feature bullet and one Troubleshooting link. Put full
command examples in `docs/COMMANDS.md` and contributor workflow in
`CONTRIBUTING.md`.

- [ ] **Step 4: Run formatting/static checks**

Run: `python -m compileall -q src/jarvis_line scripts`

Expected: exit `0`.

Run: `git diff --check`

Expected: no output and exit `0`.

- [ ] **Step 5: Run the complete Python and smoke suites**

Run: `PYTHONPATH=src python tests/run_smoke.py`

Expected: smoke suite PASS.

Run: `python -m pytest -q`

Expected: all tests PASS.

- [ ] **Step 6: Run the complete Swift and artifact suites**

Run: `swift test --package-path apps/macos/JarvisLine`

Expected: all Swift tests PASS.

Run: `bash scripts/verify-macos-artifacts.sh`

Expected: app and DMG smoke verification PASS.

Run: `python -m build --wheel --outdir clean-dist`

Expected: one `jarvis_line-*.whl` in `clean-dist`.

Run: `python scripts/verify_clean_install.py clean-dist`

Expected: clean install and uninstall verification PASS.

- [ ] **Step 7: Run both soak modes one final time**

Run: `PYTHONPATH=src python scripts/soak_runtime.py --mode quick --seed 1 --json`

Run: `PYTHONPATH=src python scripts/soak_runtime.py --mode extended --seed 1 --json`

Expected: both report `"ok": true` with no invariant failures.

- [ ] **Step 8: Commit CI and documentation**

```bash
git add .github/workflows/ci.yml .github/workflows/soak.yml README.md docs/COMMANDS.md docs/SUPPORT-MATRIX.md CONTRIBUTING.md PRIVACY.md CHANGELOG.md
git commit -m "docs: publish reliability and soak workflows"
```

- [ ] **Step 9: Review the final branch**

Run: `git status --short`

Expected: clean working tree.

Run: `git diff --stat develop...HEAD`

Expected: only Reliability Center, soak, test, workflow, and documentation files.

Run: `git log --oneline develop..HEAD`

Expected: design plus focused implementation commits in task order.
