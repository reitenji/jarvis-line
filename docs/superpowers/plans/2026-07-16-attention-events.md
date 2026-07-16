# Attention Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional, content-aware spoken alerts for Codex permission requests and structured user-input requests without increasing the resident process count or exposing sensitive request data.

**Architecture:** A pure `attention` module classifies bounded untrusted metadata and renders fixed local language templates. Normalized attention events enter the existing file-backed single-worker queue with explicit priority, expiry, and correlation metadata; the official Codex `PermissionRequest` hook and the existing session watcher are thin adapters. The shared Python config contract remains authoritative for CLI setup and the macOS app.

**Tech Stack:** Python 3.10+, pytest, JSONL Codex session adapter, Codex command hooks, Swift 6/SwiftUI, Swift Testing.

## Global Constraints

- No LLM, network request, model load, or additional resident process may be introduced by attention formatting.
- Never persist or log raw commands, arguments, `tool_input`, question options, answers, paths, URLs, secrets, or raw call ids.
- Preserve the existing one-worker playback guarantee and stable `source + session_id` isolation.
- Existing installations resolve `attention_enabled` as `false`; guided Codex setup recommends it but applies it only after user confirmation.
- `final_only` suppresses commentary but does not suppress enabled attention; `off`, disabled speech, quiet hours, and quiet days suppress attention.
- Attention jobs expire after 30 seconds and never interrupt audio already playing.
- Built-in templates cover English, Turkish, French, Italian, Japanese, and Chinese; unknown languages fall back to English.
- Codex hooks use `[features].hooks = true`; Jarvis Line must not write deprecated `[features].codex_hooks`.
- Automatic Plan-mode detection is a fail-soft compatibility adapter over the structured `request_user_input` transcript shape.

## File Map

- Create `src/jarvis_line/attention.py`: pure classification, sanitization, language templates, Plan-mode payload parsing, and one-way correlation tokens.
- Create `src/jarvis_line/codex_hook.py`: bounded, stdout-silent one-shot `PermissionRequest` adapter.
- Create `tests/test_attention.py`: formatter, language, redaction, parser, and token tests.
- Create `tests/test_codex_hook.py`: malformed, disabled, normalized-event, and stdout tests.
- Modify `src/jarvis_line/events.py` and `tests/test_events.py`: protocol validation and normalized attention dispatch.
- Modify `src/jarvis_line/queue_policy.py`, `src/jarvis_line/watcher.py`, `src/jarvis_line/audio_worker.py`, `tests/test_queue_policy.py`, `tests/test_watcher.py`, and `tests/test_audio_worker.py`: priority, expiry, cancellation, and session adapter behavior.
- Modify `src/jarvis_line/config_contract.py`, `src/jarvis_line/setup_flow.py`, `src/jarvis_line/cli.py`, and their tests: default-off config, setup choice, hook installation, feature enablement, status, doctor, and CLI syntax.
- Modify `apps/macos/JarvisLine/Sources/JarvisConfig.swift`, `SetupContract.swift`, `SetupAssistant.swift`, `JarvisLineApp.swift`, and Swift tests: validated toggle and setup serialization.
- Modify `README.md`, `docs/COMMANDS.md`, `docs/CONFIGURATION.md`, `docs/EVENT-PROTOCOL.md`, `docs/SUPPORT-MATRIX.md`, and `CHANGELOG.md`: user-facing behavior, privacy, compatibility, and examples.

---

### Task 1: Pure Attention Formatter

**Files:**
- Create: `src/jarvis_line/attention.py`
- Create: `tests/test_attention.py`

**Interfaces:**
- Produces: `AttentionMessage(category: str, line: str)`.
- Produces: `format_permission_request(tool_name: object, tool_input: object, language: object) -> AttentionMessage`.
- Produces: `format_input_required(header: object, question: object, language: object) -> AttentionMessage`.
- Produces: `parse_input_request_payload(payload: object) -> InputRequest | None`.
- Produces: `correlation_token(call_id: object) -> str | None`.

- [ ] **Step 1: Write failing formatter and privacy tests**

```python
def test_permission_formatter_classifies_without_speaking_secret():
    result = format_permission_request(
        "Bash",
        {"command": "curl https://api.example.com/items?token=secret"},
        "English",
    )
    assert result.category == "network"
    assert result.line == "Permission is needed to connect to api.example.com."
    assert "secret" not in result.line


def test_input_formatter_never_speaks_options_or_secret_assignments():
    result = format_input_required(
        "Deploy",
        "Choose the target for TOKEN=secret: production or staging?",
        "English",
    )
    assert result.line.startswith("Your input is needed")
    assert "secret" not in result.line
    assert len(result.line) <= 240
```

- [ ] **Step 2: Run tests and verify the new module is missing**

Run: `.venv/bin/python -m pytest tests/test_attention.py -q`

Expected: FAIL during import because `jarvis_line.attention` does not exist.

- [ ] **Step 3: Implement fixed templates and conservative classifiers**

```python
@dataclass(frozen=True)
class AttentionMessage:
    category: str
    line: str


def format_permission_request(tool_name: object, tool_input: object, language: object) -> AttentionMessage:
    intent = classify_permission(tool_name, tool_input)
    template = template_catalog(language)
    return AttentionMessage(intent.category, template.permission(intent))


def format_input_required(header: object, question: object, language: object) -> AttentionMessage:
    safe = sanitize_question(header, question)
    template = template_catalog(language)
    return AttentionMessage("input_required", template.input_required(safe))
```

Use `shlex.split` only for classification, `urllib.parse.urlsplit` only for hostname extraction, strict allowlists for MCP labels, and bounded redaction before interpolation. Add parameterized assertions for all six languages, malformed shell quoting, control characters, credentials in URLs, bearer/token assignments, and generic fallbacks.

- [ ] **Step 4: Run formatter tests**

Run: `.venv/bin/python -m pytest tests/test_attention.py -q`

Expected: PASS with no network, subprocess, TTS, or filesystem mocks needed.

- [ ] **Step 5: Commit the formatter**

```bash
git add src/jarvis_line/attention.py tests/test_attention.py
git commit -m "feat: add safe attention formatter"
```

### Task 2: Versioned Attention Event Contract

**Files:**
- Modify: `src/jarvis_line/events.py`
- Modify: `src/jarvis_line/cli.py`
- Modify: `tests/test_events.py`

**Interfaces:**
- Consumes: `attention.ATTENTION_TYPES`.
- Produces: `SpeechEvent.attention_type: str | None`.
- Produces CLI: `jarvis-line emit --phase attention --attention-type input_required --line TEXT`.

- [ ] **Step 1: Write failing event and parser tests**

```python
def test_attention_event_requires_supported_type():
    event = SpeechEvent.from_mapping({
        "version": 1,
        "source": "claude",
        "session_id": "abc",
        "phase": "attention",
        "attention_type": "input_required",
        "line": "Your input is needed.",
    })
    assert event.attention_type == "input_required"


@pytest.mark.parametrize("attention_type", [None, "unknown"])
def test_attention_event_rejects_missing_or_unknown_type(attention_type):
    with pytest.raises(ValueError):
        SpeechEvent.from_mapping({
            "source": "custom", "session_id": "abc", "phase": "attention",
            "attention_type": attention_type, "line": "Attention.",
        })
```

- [ ] **Step 2: Run event tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_events.py -q`

Expected: FAIL because `attention` is not an accepted phase and the CLI lacks `--attention-type`.

- [ ] **Step 3: Extend normalization and dispatch without changing version 1**

Add `attention` to `PHASE_ALIASES`, validate `attention_type` only for attention events, include it in diagnostics, and pass it to `watcher.queue_jarvis_line`. Do not call `remember_latest_message` for attention events so attention text cannot become the cached final response.

- [ ] **Step 4: Run event tests**

Run: `.venv/bin/python -m pytest tests/test_events.py -q`

Expected: PASS for legacy commentary/final and new attention payloads.

- [ ] **Step 5: Commit the protocol extension**

```bash
git add src/jarvis_line/events.py src/jarvis_line/cli.py tests/test_events.py
git commit -m "feat: extend event protocol with attention"
```

### Task 3: Priority Queue, Expiry, And Cancellation

**Files:**
- Modify: `src/jarvis_line/queue_policy.py`
- Modify: `src/jarvis_line/watcher.py`
- Modify: `src/jarvis_line/audio_worker.py`
- Modify: `tests/test_queue_policy.py`
- Modify: `tests/test_watcher.py`
- Modify: `tests/test_audio_worker.py`

**Interfaces:**
- Produces: `phase_priority(phase: object) -> int` with attention `2`, final `1`, commentary `0`.
- Produces: `dequeue_next(jobs, last_session_key, now_ms=...)` that ignores expired jobs.
- Produces: `queue_jarvis_line(..., attention_type=None, correlation_token=None) -> bool`.
- Produces: `cancel_attention_job(session_key, attention_type, correlation_token) -> bool`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_attention_precedes_final_and_rotates_sessions():
    queued = [
        make_job("f1", "a", "final", 10),
        {**make_job("a1", "b", "attention", 20), "attention_type": "input_required"},
    ]
    job, _, session = dequeue_next(queued, "a", now_ms=25)
    assert job["message_id"] == "a1"
    assert session == "b"


def test_expired_attention_is_never_dequeued():
    job = {**make_job("a1", "a", "attention", 10), "expires_ts_ms": 20}
    selected, remaining, _ = dequeue_next([job], "", now_ms=21)
    assert selected is None
    assert remaining == []
```

Also cover same-session attention replacement, commentary preserving attention, final removing attention, overflow dropping commentary first, and correlation-token cancellation that cannot affect another session.

- [ ] **Step 2: Run queue and worker tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_queue_policy.py tests/test_watcher.py tests/test_audio_worker.py -q`

Expected: FAIL on priority, signature, and expiry assertions.

- [ ] **Step 3: Implement priority and bounded metadata**

Store only `attention_type`, an optional short one-way `correlation_token`, and `expires_ts_ms = enqueued_ts_ms + 30000` on attention jobs. Update message identity to include attention type. Ensure `speak_mode_allows("attention")` returns true for `final_only` and `commentary_and_final`, but false for `off`.

- [ ] **Step 4: Enforce expiry immediately before synthesis**

Pass current milliseconds to `dequeue_next`; retain the audio worker's general stale-job limit and additionally discard any job whose explicit `expires_ts_ms` is reached. Record only `expired` plus content-free metadata.

- [ ] **Step 5: Run queue and worker tests**

Run: `.venv/bin/python -m pytest tests/test_queue_policy.py tests/test_watcher.py tests/test_audio_worker.py -q`

Expected: PASS, including legacy fairness and RSS-limit tests.

- [ ] **Step 6: Commit the queue behavior**

```bash
git add src/jarvis_line/queue_policy.py src/jarvis_line/watcher.py src/jarvis_line/audio_worker.py tests/test_queue_policy.py tests/test_watcher.py tests/test_audio_worker.py
git commit -m "feat: prioritize expiring attention jobs"
```

### Task 4: Codex Permission Hook And Plan-Mode Adapter

**Files:**
- Create: `src/jarvis_line/codex_hook.py`
- Create: `tests/test_codex_hook.py`
- Modify: `src/jarvis_line/watcher.py`
- Modify: `src/jarvis_line/cli.py`
- Modify: `tests/test_watcher.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/run_smoke.py`

**Interfaces:**
- Consumes: `attention.format_permission_request`, `attention.parse_input_request_payload`, and `events.emit_event`.
- Produces: `codex_hook.permission_request_main(stdin=None) -> int`, always stdout-silent and fail-soft.
- Produces: idempotent `SessionStart` plus `PermissionRequest` hook installation.
- Produces: structured Plan-mode input queueing and matched-result cancellation in `watcher.process_line`.

- [ ] **Step 1: Write failing one-shot hook tests**

```python
def test_permission_hook_emits_normalized_event_without_stdout(monkeypatch, capsys):
    accepted = []
    monkeypatch.setattr(codex_hook, "load_config", lambda: {
        "attention_enabled": True, "line_language": "English",
    })
    monkeypatch.setattr(codex_hook.events, "emit_event", lambda event: accepted.append(event) or True)
    payload = {
        "hook_event_name": "PermissionRequest", "session_id": "s1",
        "tool_name": "Bash", "tool_input": {"command": "git push origin develop"},
    }
    assert codex_hook.permission_request_main(io.StringIO(json.dumps(payload))) == 0
    assert accepted[0].attention_type == "permission_request"
    assert capsys.readouterr().out == ""
```

Add malformed JSON, oversized stdin, wrong event name, missing session, disabled attention, and formatter-exception cases; all must exit `0` with no stdout.

- [ ] **Step 2: Write failing Plan-mode session tests**

Use minimal fixtures matching the observed shape:

```python
call = {"type": "response_item", "payload": {
    "type": "function_call", "name": "request_user_input", "call_id": "call-1",
    "arguments": json.dumps({"questions": [{
        "header": "Release", "id": "release", "question": "Which release channel?",
        "options": [{"label": "Beta", "description": "Use beta."}],
    }]})
}}
result = {"type": "response_item", "payload": {
    "type": "function_call_output", "call_id": "call-1", "output": "Beta",
}}
```

Assert one `input_required` job is queued without options/output/call id and is removed when the matching result is processed. Assert a different session's job remains.

- [ ] **Step 3: Run adapter tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_codex_hook.py tests/test_watcher.py tests/test_cli.py -q`

Expected: FAIL because the hook module, PermissionRequest install entry, and session parser do not exist.

- [ ] **Step 4: Implement the one-shot hook and session adapter**

The hook reads at most 64 KiB, validates exact event/session fields, formats locally, emits one normalized event, catches all ordinary exceptions, and never prints. The watcher parses only exact `request_user_input` function calls, hashes call ids before persistence, and cancels matching queued alerts on either supported output event type.

- [ ] **Step 5: Make Codex hook installation idempotent and current**

Install this command under `PermissionRequest`:

```text
<package-python> -m jarvis_line.codex_hook
```

Keep the existing SessionStart command, preserve unrelated entries, back up `hooks.json` once, invoke `codex features enable hooks` through an argv list, and never create `codex_hooks`. Uninstall removes only Jarvis Line commands from both event lists.

- [ ] **Step 6: Run adapter and smoke tests**

Run: `.venv/bin/python -m pytest tests/test_codex_hook.py tests/test_watcher.py tests/test_cli.py -q && .venv/bin/python tests/run_smoke.py`

Expected: PASS; temporary Codex home contains both hooks and no raw request content in queue/log fixtures.

- [ ] **Step 7: Commit Codex integration**

```bash
git add src/jarvis_line/codex_hook.py src/jarvis_line/watcher.py src/jarvis_line/cli.py tests/test_codex_hook.py tests/test_watcher.py tests/test_cli.py tests/run_smoke.py
git commit -m "feat: add codex attention adapters"
```

### Task 5: Shared Configuration And Guided Setup

**Files:**
- Modify: `src/jarvis_line/config_contract.py`
- Modify: `src/jarvis_line/setup_flow.py`
- Modify: `src/jarvis_line/cli.py`
- Modify: `tests/test_config_contract.py`
- Modify: `tests/test_setup_flow.py`
- Modify: `tests/test_cli_setup.py`

**Interfaces:**
- Produces config field: `attention_enabled: bool`, default `false`.
- Produces setup-plan field: `attention_enabled: bool`.
- Produces setup inspection current value and review text for attention alerts.

- [ ] **Step 1: Write failing contract and setup tests**

```python
def test_attention_defaults_off_and_is_shared():
    contract = config_contract.contract_document()
    assert contract["defaults"]["attention_enabled"] is False
    assert contract["fields"]["attention_enabled"]["type"] == "boolean"


def test_codex_setup_can_enable_attention():
    plan = SetupPlan.from_mapping({**valid_plan(), "attention_enabled": True})
    assert build_config(plan, {})["attention_enabled"] is True
    assert "Attention alerts: enabled" in "\n".join(review_lines(plan, environment()))
```

Assert strict boolean validation, inspection privacy, existing-plan default `false`, interactive Codex recommendation, and setup apply persistence.

- [ ] **Step 2: Run setup tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_config_contract.py tests/test_setup_flow.py tests/test_cli_setup.py -q`

Expected: FAIL on missing field and rejected setup-plan key.

- [ ] **Step 3: Extend the shared contract and setup flow**

Add the boolean to every backend's common fields, defaults, setup serialization, inspection, review, and config construction. Prompt once after speech mode; default yes only when target is Codex and speech is enabled, otherwise preserve the current value/default false.

- [ ] **Step 4: Run setup tests**

Run: `.venv/bin/python -m pytest tests/test_config_contract.py tests/test_setup_flow.py tests/test_cli_setup.py -q`

Expected: PASS without exposing commands or adapter payloads in setup JSON.

- [ ] **Step 5: Commit shared configuration**

```bash
git add src/jarvis_line/config_contract.py src/jarvis_line/setup_flow.py src/jarvis_line/cli.py tests/test_config_contract.py tests/test_setup_flow.py tests/test_cli_setup.py
git commit -m "feat: configure optional attention alerts"
```

### Task 6: macOS Manager Toggle

**Files:**
- Modify: `apps/macos/JarvisLine/Sources/JarvisConfig.swift`
- Modify: `apps/macos/JarvisLine/Sources/SetupContract.swift`
- Modify: `apps/macos/JarvisLine/Sources/SetupAssistant.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/JarvisConfigContractTests.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/SetupContractTests.swift`
- Modify: `apps/macos/JarvisLine/Tests/JarvisLineTests/SetupAssistantModelTests.swift`

**Interfaces:**
- Consumes: Python contract field `attention_enabled` and setup JSON key `attention_enabled`.
- Produces: one validated `Attention alerts` toggle in Runtime settings and setup speech behavior.

- [ ] **Step 1: Write failing Swift decoding and persistence tests**

```swift
@Test func attentionDefaultsOffAndPersists() throws {
    var draft = JarvisConfigDraft(data: [:])
    #expect(!draft.attentionEnabled)
    draft.attentionEnabled = true
    #expect(draft.applying(to: [:])["attention_enabled"] as? Bool == true)
}
```

Add setup-plan encode/decode coverage and verify disabling speech also presents attention as unavailable without deleting the saved preference.

- [ ] **Step 2: Run Swift tests and verify compile failure**

Run: `swift test --package-path apps/macos/JarvisLine`

Expected: FAIL because the Swift models lack `attentionEnabled`.

- [ ] **Step 3: Add the single-toggle UI**

Place `Toggle("Attention alerts", isOn: $model.config.attentionEnabled)` beside speech behavior, disable it visually while speech is off, and add one concise caption that Codex permissions and Plan-mode questions are automatic while other agents require protocol events. Do not expose templates, event types, or formatter rules.

- [ ] **Step 4: Run Swift tests and build**

Run: `swift test --package-path apps/macos/JarvisLine && swift build -c release --package-path apps/macos/JarvisLine`

Expected: PASS and a successful release build.

- [ ] **Step 5: Commit macOS configuration**

```bash
git add apps/macos/JarvisLine/Sources apps/macos/JarvisLine/Tests
git commit -m "feat: expose attention alerts in macos app"
```

### Task 7: Documentation, Benchmarks, And Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/COMMANDS.md`
- Modify: `docs/CONFIGURATION.md`
- Modify: `docs/EVENT-PROTOCOL.md`
- Modify: `docs/SUPPORT-MATRIX.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_release_metadata.py`
- Create: `scripts/benchmark_attention_hook.py`

**Interfaces:**
- Produces: documented setup, event examples, Plan-mode distinction, privacy boundary, and a hermetic 30-run hook benchmark.

- [ ] **Step 1: Write failing documentation assertions**

```python
def test_attention_documentation_is_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    protocol = (ROOT / "docs/EVENT-PROTOCOL.md").read_text(encoding="utf-8")
    assert "Attention alerts" in readme
    assert "request_user_input" in readme
    assert "--attention-type input_required" in protocol
```

- [ ] **Step 2: Run release metadata tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_release_metadata.py -q`

Expected: FAIL until the user-facing references are added.

- [ ] **Step 3: Document the complete behavior without inflating the README**

Keep a short README feature/setup section and move detailed CLI/event/config examples into the existing focused documents. State that Codex permissions use the official hook, Plan-mode questions use a fail-soft session compatibility adapter, Claude/Gemini require explicit protocol events, raw request data is not persisted, and attention is default-off for existing configurations.

- [ ] **Step 4: Add the hermetic benchmark**

Run the one-shot hook 30 times with a temporary home, disabled TTS process launch, and a synthetic safe payload. Print median and p95 milliseconds plus pass/fail against 150 ms; never print payload content.

- [ ] **Step 5: Run focused and full verification**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tests/run_smoke.py
.venv/bin/python scripts/benchmark_attention_hook.py
swift test --package-path apps/macos/JarvisLine
python3 -m build
git diff --check
```

Expected: all tests/builds pass; benchmark p95 is below 150 ms on the primary Mac; no whitespace errors.

- [ ] **Step 6: Perform privacy and regression inspection**

Search generated temporary queue, trace, watcher log, and support output for synthetic command arguments, secrets, raw call id, option descriptions, and answer output. Verify none occur. Then run synthetic Kokoro and system-TTS attention events through the installed local runtime and confirm one-at-a-time playback, expiry, and unchanged commentary/final speech.

- [ ] **Step 7: Commit docs and verification assets**

```bash
git add README.md CHANGELOG.md docs scripts/benchmark_attention_hook.py tests/test_release_metadata.py
git commit -m "docs: explain and verify attention alerts"
```

## Plan Self-Review

- Spec coverage: formatter, protocol, priority, expiry, cancellation, permission hook, Plan-mode input, config, setup, macOS UI, docs, privacy, benchmark, and full verification each map to an explicit task.
- Placeholder scan: no deferred implementation markers or unspecified error-handling steps remain.
- Type consistency: `attention_type`, `correlation_token`, `attention_enabled`, and the formatter/parser function names are identical across producer and consumer tasks.
- Scope boundary: Claude/Gemini automatic permission detection, LLM phrasing, playback interruption, and arbitrary formatter configuration remain excluded.
