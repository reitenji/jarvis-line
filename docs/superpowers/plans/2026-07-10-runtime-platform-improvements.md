# Runtime And Platform Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Jarvis Line reliable under concurrent sessions, resource-aware with Kokoro, diagnosable without raw-log inspection, agent-neutral at its input boundary, and continuously verified as both a Python CLI and macOS app.

**Architecture:** Keep the existing single audio worker and bounded file-backed queue, but extract deterministic queue policy, structured diagnostics, normalized speech events, and the configuration contract into focused modules. The watcher remains the Codex compatibility adapter; new agents call a small `emit` protocol directly. The macOS app continues to use the CLI as its runtime authority and gains a read-only diagnostics surface.

**Tech Stack:** Python 3.10+, pytest, standard-library JSON/file locking/subprocess APIs, Swift 6/SwiftUI/AppKit, Swift Package Manager, GitHub Actions.

## Global Constraints

- Preserve exactly one active audio playback process at a time.
- Prefer lower idle memory and fewer model reloads without dropping final messages.
- Add no required Python runtime dependency.
- Preserve Python 3.10/3.12 and macOS/Linux/Windows compatibility.
- Treat spoken text and absolute session paths as private; structured diagnostics are metadata-only by default.
- Keep the CLI core usable without the macOS app.
- Keep changes on `feature/runtime-platform-improvements`; delivery targets `develop` before `main`.

---

### Task 1: Drain The Queue Before A Memory Exit

**Files:**
- Modify: `src/jarvis_line/audio_worker.py:432`
- Test: `tests/test_audio_worker.py`

**Interfaces:**
- Consumes: `dequeue_audio_job()`, `rss_limit_exceeded()`, `speak_line()`.
- Produces: `run_worker()` behavior where an RSS breach schedules exit after the current burst rather than abandoning queued work.

- [ ] **Step 1: Write a failing worker-loop regression test**

```python
def test_worker_drains_pending_jobs_before_rss_exit(monkeypatch):
    jobs = [{"jarvis_line": "one"}, {"jarvis_line": "two"}, None]
    spoken = []
    monkeypatch.setattr(audio_worker, "dequeue_audio_job", lambda: jobs.pop(0))
    monkeypatch.setattr(audio_worker, "speak_line", spoken.append)
    monkeypatch.setattr(audio_worker, "rss_limit_exceeded", lambda: (True, 700.0, 512.0))
    monkeypatch.setattr(audio_worker, "warm_tts_if_configured", lambda: None)
    assert audio_worker.run_worker() == 0
    assert spoken == ["one", "two"]
```

- [ ] **Step 2: Run the focused test and confirm the second job is not spoken**

Run: `.venv/bin/python -m pytest tests/test_audio_worker.py::test_worker_drains_pending_jobs_before_rss_exit -q`

- [ ] **Step 3: Add an `exit_after_drain` state to `run_worker()`**

```python
exit_after_drain = False
job = dequeue_audio_job()
if not job and exit_after_drain:
    append_log("worker-rss-drained-exit")
    return 0
```

Set `exit_after_drain = True` when RSS exceeds the limit and continue the loop until the queue is empty.

- [ ] **Step 4: Verify focused and worker tests**

Run: `.venv/bin/python -m pytest tests/test_audio_worker.py -q`

---

### Task 2: Make Queue Scheduling Final-Safe And Session-Fair

**Files:**
- Create: `src/jarvis_line/queue_policy.py`
- Modify: `src/jarvis_line/watcher.py:587`
- Modify: `src/jarvis_line/audio_worker.py:127`
- Create: `tests/test_queue_policy.py`
- Modify: `tests/test_watcher.py`

**Interfaces:**
- Produces: `schedule_job(jobs, new_job, max_jobs, stale_before_ms) -> list[dict]`.
- Produces: `dequeue_next(jobs, last_session_key) -> tuple[dict | None, list[dict], str]`.
- Consumes: queue jobs containing `session_key`, `phase`, `message_id`, and `enqueued_ts_ms`.

- [ ] **Step 1: Write failing pure-policy tests**

```python
from jarvis_line.queue_policy import dequeue_next, schedule_job

def make_job(message_id, session, phase, ts):
    return {"message_id": message_id, "session_key": session, "phase": phase, "enqueued_ts_ms": ts}

def test_final_replaces_same_session_commentary():
    queued = [make_job("c1", "a", "commentary", 10)]
    result = schedule_job(queued, make_job("f1", "a", "final", 20), 8, 0)
    assert [job["message_id"] for job in result] == ["f1"]

def test_trimming_drops_commentary_before_final():
    queued = [make_job("f1", "a", "final", 10), make_job("c1", "b", "commentary", 20)]
    result = schedule_job(queued, make_job("f2", "c", "final", 30), 2, 0)
    assert [job["message_id"] for job in result] == ["f1", "f2"]

def test_dequeue_prefers_final_and_rotates_sessions():
    queued = [make_job("c1", "a", "commentary", 10), make_job("f1", "a", "final", 20), make_job("f2", "b", "final", 30)]
    job, remaining, session = dequeue_next(queued, "a")
    assert job["message_id"] == "f2"
    assert session == "b"
    assert len(remaining) == 2

def test_duplicate_message_id_is_coalesced():
    queued = [make_job("same", "a", "commentary", 10)]
    result = schedule_job(queued, make_job("same", "a", "commentary", 20), 8, 0)
    assert len(result) == 1
    assert result[0]["enqueued_ts_ms"] == 20
```

- [ ] **Step 2: Run policy tests and confirm import/behavior failures**

Run: `.venv/bin/python -m pytest tests/test_queue_policy.py -q`

- [ ] **Step 3: Implement deterministic scheduling**

```python
def is_final_phase(phase: str) -> bool:
    return phase in {"final", "final_answer", "final-response", "final_response"}

def schedule_job(jobs, new_job, max_jobs, stale_before_ms):
    active = [dict(job) for job in jobs if int(job.get("enqueued_ts_ms") or 0) >= stale_before_ms]
    active = [job for job in active if job.get("message_id") != new_job.get("message_id")]
    session = new_job.get("session_key")
    if is_final_phase(str(new_job.get("phase") or "")):
        active = [job for job in active if job.get("session_key") != session]
    else:
        active = [job for job in active if not (job.get("session_key") == session and not is_final_phase(str(job.get("phase") or "")))]
    active.append(dict(new_job))
    while max_jobs > 0 and len(active) > max_jobs:
        commentary_index = next((index for index, job in enumerate(active) if not is_final_phase(str(job.get("phase") or ""))), 0)
        active.pop(commentary_index)
    return active
```

- [ ] **Step 4: Integrate policy under the existing queue lock**

Store `last_session_key` in the queue document so dequeue can rotate sessions without another process or unbounded state.

- [ ] **Step 5: Verify policy, watcher, and worker tests**

Run: `.venv/bin/python -m pytest tests/test_queue_policy.py tests/test_watcher.py tests/test_audio_worker.py -q`

---

### Task 3: Add Privacy-Safe Structured Diagnostics

**Files:**
- Create: `src/jarvis_line/diagnostics.py`
- Modify: `src/jarvis_line/watcher.py`
- Modify: `src/jarvis_line/audio_worker.py`
- Modify: `src/jarvis_line/cli.py`
- Create: `tests/test_diagnostics.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `record_event(event, **metadata)` with a bounded JSONL file at `~/.codex/hooks/jarvis_line_trace.jsonl`.
- Produces: `read_events(limit=20) -> list[dict]`.
- Produces CLI: `jarvis-line trace [--limit N] [--json] [--clear]`.

- [ ] **Step 1: Write failing redaction, rotation, and CLI tests**

```python
def test_record_event_hashes_session_and_omits_spoken_text(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "TRACE_PATH", tmp_path / "trace.jsonl")
    diagnostics.record_event("queued", session_key="/private/session.jsonl", line="secret", message_id="abc")
    event = diagnostics.read_events(1)[0]
    assert event["session_id"] != "/private/session.jsonl"
    assert "line" not in event
    assert "text" not in event

def test_trace_is_bounded_and_reads_newest_events(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "TRACE_PATH", tmp_path / "trace.jsonl")
    monkeypatch.setattr(diagnostics, "TRACE_MAX_BYTES", 512)
    for index in range(40):
        diagnostics.record_event("queued", message_id=str(index))
    assert diagnostics.read_events(3)[-1]["message_id"] == "39"
    assert (tmp_path / "trace.jsonl").stat().st_size <= 1024

def test_trace_command_prints_event_lifecycle(monkeypatch, capsys):
    monkeypatch.setattr(cli.diagnostics, "read_events", lambda limit: [{"event": "completed", "message_id": "abc", "ts_ms": 1}])
    assert cli.trace_command(argparse.Namespace(limit=20, json=False, clear=False)) == 0
    assert "completed" in capsys.readouterr().out
```

- [ ] **Step 2: Run focused tests and confirm missing-module failures**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py tests/test_cli.py -q`

- [ ] **Step 3: Implement the bounded metadata trace**

```python
record_event("queued", session_key=session_key, message_id=job_id, phase=phase)
record_event("speaking", session_key=session_key, message_id=message_id, queue_delay_ms=delay)
record_event("completed", message_id=message_id, duration_ms=duration)
```

Hash session keys with SHA-256, truncate hashes to 12 characters, and reject metadata keys named `text`, `line`, `content`, or `session_path`.

- [ ] **Step 4: Replace default raw content/path logging with IDs**

Keep raw content only behind a new `debug_content_logging=false` configuration field.

- [ ] **Step 5: Verify diagnostics and regression tests**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py tests/test_cli.py tests/test_watcher.py tests/test_audio_worker.py -q`

---

### Task 4: Add The Agent-Neutral Emit Protocol

**Files:**
- Create: `src/jarvis_line/events.py`
- Modify: `src/jarvis_line/cli.py`
- Create: `tests/test_events.py`
- Modify: `tests/test_cli.py`
- Create: `docs/EVENT-PROTOCOL.md`
- Modify: `README.md`
- Modify: `docs/COMMANDS.md`

**Interfaces:**
- Produces: `SpeechEvent.from_mapping(value) -> SpeechEvent`.
- Produces: `emit_event(event) -> bool`.
- Produces CLI: `jarvis-line emit --source NAME --session ID --phase PHASE --line TEXT` and `jarvis-line emit --stdin`.

- [ ] **Step 1: Write failing validation and emission tests**

```python
def test_speech_event_normalizes_final_phase():
    event = SpeechEvent.from_mapping({"version": 1, "source": "claude", "session_id": "abc", "phase": "final_answer", "line": "Done."})
    assert event.phase == "final"
    assert event.session_key == "claude:abc"

def test_speech_event_rejects_empty_session_or_line():
    with pytest.raises(ValueError):
        SpeechEvent.from_mapping({"version": 1, "source": "custom", "session_id": "", "phase": "final", "line": ""})

def test_emit_event_queues_normalized_session_key(monkeypatch):
    queued = []
    monkeypatch.setattr(events, "queue_jarvis_line", lambda session, phase, line, text="": queued.append((session, phase, line)) or True)
    event = SpeechEvent.from_mapping({"version": 1, "source": "gemini", "session_id": "abc", "phase": "commentary", "line": "Working."})
    assert events.emit_event(event) is True
    assert queued == [("gemini:abc", "commentary", "Working.")]

def test_emit_stdin_accepts_versioned_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"version":1,"source":"custom","session_id":"abc","phase":"final","line":"Done."}'))
    monkeypatch.setattr(cli.events, "emit_event", lambda event: True)
    assert cli.emit_command(argparse.Namespace(stdin=True, source=None, session=None, phase=None, line=None, text=None)) == 0
    assert "queued" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run focused tests and confirm missing API failures**

Run: `.venv/bin/python -m pytest tests/test_events.py tests/test_cli.py -q`

- [ ] **Step 3: Implement versioned protocol validation**

```json
{"version":1,"source":"claude","session_id":"abc","phase":"commentary","line":"The change is ready."}
```

Limit source/session/phase to 128 characters and line input to 4,096 characters before applying normal spoken-length trimming.

- [ ] **Step 4: Route normalized events through the existing queue**

Use `source:session_id` as the session key, then call `remember_latest_message()` and `queue_jarvis_line()`.

- [ ] **Step 5: Document adapter examples and verify all event tests**

Run: `.venv/bin/python -m pytest tests/test_events.py tests/test_cli.py tests/test_watcher.py -q`

---

### Task 5: Establish One Canonical Config Contract

**Files:**
- Create: `src/jarvis_line/config_contract.py`
- Modify: `src/jarvis_line/cli.py:41`
- Modify: `src/jarvis_line/kokoro_say.py`
- Modify: `apps/macos/JarvisLine/Sources/JarvisConfig.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `default_config()`, `field_schema()`, `backend_capabilities()`, and `contract_document()`.
- Produces CLI: `jarvis-line config contract` returning a versioned object with `defaults`, `fields`, and `backends` dictionaries.
- Produces Swift: `JarvisConfigContract.fromJSON(_:)` with fallback values only when the CLI contract is unavailable.

- [ ] **Step 1: Write failing Python contract tests**

```python
def test_config_contract_contains_defaults_schema_and_backends(capsys):
    assert cli.config_contract_command(argparse.Namespace()) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["defaults"]["tts"] == "kokoro"
    assert "tts" in payload["fields"]
    assert "system" in payload["backends"]

def test_default_config_is_a_fresh_copy():
    first = config_contract.default_config()
    first["line_prefixes"].append("Changed:")
    assert config_contract.default_config()["line_prefixes"] == ["Jarvis line:"]
```

- [ ] **Step 2: Run tests and confirm the contract command is absent**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`

- [ ] **Step 3: Extract Python config constants into `config_contract.py`**

Preserve the current CLI names as imports during the migration so behavior remains unchanged.

- [ ] **Step 4: Make the macOS model load the CLI contract before settings**

```swift
let contractText = try await cli.run(["config", "contract"])
contract = try JarvisConfigContract.fromJSON(contractText)
configDraft = try configStore.load(defaults: contract.defaults)
```

- [ ] **Step 5: Add Swift contract parsing tests and verify both stacks**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`

Run: `swift test --package-path apps/macos/JarvisLine`

---

### Task 6: Add A Native Runtime Diagnostics Surface

**Files:**
- Create: `apps/macos/JarvisLine/Sources/RuntimeDiagnostics.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`
- Create: `apps/macos/JarvisLine/Tests/JarvisLineTests/RuntimeDiagnosticsTests.swift`
- Modify: `apps/macos/JarvisLine/Package.swift`

**Interfaces:**
- Consumes: `jarvis-line status` and `jarvis-line trace --json --limit 12`.
- Produces: read-only settings section showing last event, queue delay, worker memory, restart/exit reason, and recent lifecycle events.

- [ ] **Step 1: Add failing Swift decoding and display-model tests**

```swift
func testTraceEventsDecodeWithoutPrivateContent() throws {
    let data = #"[{"event":"completed","message_id":"abc","session_id":"123","ts_ms":1}]"#.data(using: .utf8)!
    let events = try JSONDecoder().decode([RuntimeTraceEvent].self, from: data)
    XCTAssertEqual(events.first?.event, "completed")
    XCTAssertNil(events.first?.spokenText)
}

func testDiagnosticsSummaryHighlightsMemoryExit() throws {
    let event = RuntimeTraceEvent(event: "worker_rss_exit", messageID: nil, sessionID: nil, phase: nil, timestampMS: 1, queueDelayMS: nil, durationMS: nil, rssMB: 700, limitMB: 512)
    XCTAssertEqual(RuntimeDiagnosticsSummary(events: [event]).headline, "Worker released memory")
}
```

- [ ] **Step 2: Run Swift tests and confirm the types are missing**

Run: `swift test --package-path apps/macos/JarvisLine`

- [ ] **Step 3: Implement diagnostics models and the compact settings section**

Keep the menu bar panel limited to health and fast actions; open the full diagnostics inside the settings window.

- [ ] **Step 4: Verify Swift tests and debug build**

Run: `swift test --package-path apps/macos/JarvisLine && swift build --package-path apps/macos/JarvisLine`

---

### Task 7: Verify macOS Packaging And Release Artifacts In CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/release-artifacts.yml`
- Create: `scripts/check-version-consistency.py`
- Create: `tests/test_release_metadata.py`
- Modify: `apps/macos/JarvisLine/scripts/package-app.sh`
- Modify: `apps/macos/JarvisLine/scripts/package-dmg.sh`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: CI macOS job running `swift test`, app packaging, `plutil`, DMG packaging, and SHA-256 generation.
- Produces: tag workflow attaching wheel, source distribution, DMG, and `SHA256SUMS` to an existing/new GitHub release.

- [ ] **Step 1: Write a failing version-consistency test**

Compare `pyproject.toml`, `src/jarvis_line/__init__.py`, and `apps/macos/JarvisLine/Resources/Info.plist` using standard-library parsers.

- [ ] **Step 2: Add Swift/macOS package verification to CI**

Run Swift tests before packaging, validate the bundle plist, mount the DMG read-only, and verify it contains exactly one `Jarvis Line.app`.

- [ ] **Step 3: Add reproducible checksums and tag artifact workflow**

Use `python -m build`, `shasum -a 256`, `actions/upload-artifact@v4`, and GitHub CLI release upload with repository `contents: write` permission.

- [ ] **Step 4: Run complete local verification**

Run: `.venv/bin/python -m pytest -q`

Run: `.venv/bin/python tests/run_smoke.py`

Run: `swift test --package-path apps/macos/JarvisLine`

Run: `apps/macos/JarvisLine/scripts/package-app.sh`

Run: `apps/macos/JarvisLine/scripts/package-dmg.sh`

- [ ] **Step 5: Review the complete diff and prepare the feature branch**

Confirm no generated `.build`, `dist`, venv, model, audio, or user configuration files are tracked.
