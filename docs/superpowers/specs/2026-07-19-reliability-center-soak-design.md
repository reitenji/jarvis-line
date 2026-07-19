# Reliability Center And Runtime Soak Testing

## Goal

Make speech failures understandable and recoverable without adding a daemon,
persisting spoken content, or increasing the normal runtime resource footprint.
Use the same versioned diagnostics contract to verify multi-session behavior,
queue safety, process recovery, and resource limits under deterministic load.

## Current Behavior

The runtime already records bounded privacy-safe JSONL lifecycle events and the
macOS app shows the six most recent events. The CLI separately exposes
`doctor`, `status`, `queue`, `trace`, `restart`, `tts test`, and
`support-report`. These commands are useful, but they do not provide one
correlated delivery view or a machine-readable set of safe recovery actions.

The Python tests cover queue policy, watcher behavior, worker lifecycle,
diagnostics, and release installation independently. There is no sustained
scenario runner that combines concurrent sessions, expiry, deduplication,
worker exits, and restart recovery while checking shared invariants.

## Chosen Direction

Python remains the source of truth. It will expose a versioned diagnostics
snapshot and explicit recovery operations. The macOS app will consume that
contract on demand rather than duplicating runtime policy or running another
background service.

The soak harness will run the real queue, trace, and lifecycle boundaries in an
isolated temporary home with deterministic fake speech. It will never inspect
or modify the user's active configuration, queue, processes, or audio device.

## Considered Alternatives

### Read Runtime Files Directly From Swift

This is initially small, but it duplicates process-health, queue-expiry, and
failure-classification rules across Python and Swift. Contract drift would make
the manager disagree with the CLI.

### Versioned Python Diagnostics Contract

This is the selected approach. It adds short-lived CLI processes only when a
user opens or refreshes diagnostics. It keeps recovery policy testable and
allows future Windows or Linux interfaces to consume the same JSON.

### Local HTTP Or Socket Service

This could stream live updates, but it adds an always-on process, authentication
and socket lifecycle concerns, and a larger security and resource surface. The
current product does not need that cost.

## Diagnostics Snapshot Contract

`jarvis-line diagnostics snapshot --json` returns contract version `1`:

```json
{
  "version": 1,
  "generated_at_ms": 0,
  "health": "healthy",
  "runtime": {},
  "queue": {},
  "tts": {},
  "deliveries": [],
  "recommendations": []
}
```

`health` is one of `healthy`, `degraded`, or `action_required`. Runtime data
reports watcher and worker state, worker RSS when available, and whether an idle
worker exit is expected. Queue data reports total, expired, stale, phase counts,
and oldest age without exposing spoken lines. TTS data reports the selected
backend and readiness without emitting credentials or custom command contents.

Recent trace events are correlated by message identifier into bounded delivery
records. Each record contains only lifecycle state, phase, hashed session ID,
backend, timing, and a controlled reason code. It never contains spoken text,
transcript text, session paths, tool arguments, answers, environment variables,
custom commands, or API keys.

Recommendations use stable identifiers so the CLI and app can present the same
decision. A recommendation may point to an allowed recovery action, but the
snapshot never performs that action automatically.

## Recovery Contract

`jarvis-line diagnostics recover <action> --json` supports exactly these
bounded actions:

- `restart-runtime`: stop tracked watcher and worker processes, then launch one
  runtime through the existing restart path.
- `prune-expired`: remove only queue jobs that are expired by their explicit
  expiry or existing stale-job policy. Queue mutation uses the runtime lock and
  preserves every active job.
- `test-tts`: submit the existing fixed local test sentence through the selected
  backend. It does not accept arbitrary text through the app action.

Support-report generation remains the existing reviewed Markdown flow. Full
queue clearing, trace clearing, config rewriting, process killing outside the
tracked runtime, and automatic recovery are not Reliability Center actions.

Every action returns a versioned result with `ok`, `action`, `changed`, a safe
summary, and a fresh snapshot. Failures are fail-closed and leave unrelated
state untouched.

## macOS Reliability Center

The existing Diagnostics destination becomes a status-first Reliability Center:

1. A compact health header shows Healthy, Degraded, or Action Required.
2. Runtime and queue facts show watcher, worker, selected TTS, queued work,
   queue delay, and worker RSS when known.
3. A recent-deliveries list shows lifecycle state and skip/failure reason without
   spoken content.
4. A Recovery section shows only actions recommended by the snapshot. The TTS
   test remains available as an explicit secondary action.
5. Existing doctor details and reviewed support-report controls remain available
   through progressive disclosure.

The view refreshes when opened, when the user presses Refresh, and after an
action completes. It does not poll while hidden and does not launch a permanent
helper. Buttons disable while an action is running, show the result inline, and
require confirmation only for runtime restart. Expired-job pruning is safe and
does not require a destructive confirmation because active jobs cannot be
removed by contract.

## Soak Harness

The harness exposes deterministic quick and extended modes:

```text
python scripts/soak_runtime.py --mode quick --seed 1 --json
python scripts/soak_runtime.py --mode extended --seed 1 --json
```

Both modes operate under a temporary home and use a fake backend. The quick
mode is suitable for pull requests. Extended mode runs on a schedule and by
manual dispatch, producing a privacy-safe JSON report artifact.

Scenarios cover:

- concurrent commentary and final events from many stable sessions;
- final supersession and cross-session fairness;
- duplicate suppression and bounded queue pressure;
- attention expiry and cancellation;
- worker idle and memory-limit exits followed by clean restart;
- stale queue entries, locks, and runtime state;
- concurrent trace writers and trace rotation;
- repeated diagnostics snapshots during queue activity;
- recovery actions while no work, expired work, and active work are present.

The fake backend records lifecycle metadata rather than audio. Real TTS quality,
device playback, Windows speech APIs, Linux speech tools, and macOS signing stay
outside automated soak claims.

## Invariants And Budgets

A soak run fails when any of these invariants is violated:

- no more than one audio worker owns playback at a time;
- no terminal delivery is duplicated for the same message;
- a final is either completed or explicitly superseded/skipped with a reason;
- active queue length never exceeds the configured maximum;
- expired or stale jobs are never spoken;
- restart does not replay completed or expired work;
- recovery does not delete active work;
- trace and reports contain no forbidden content fields;
- every spawned process and temporary file is accounted for at exit.

The report records elapsed time, event counts, maximum queue depth, process RSS
samples when supported, and invariant results. Cross-platform CI uses generous
time and memory ceilings to avoid flaky absolute benchmarks; deterministic
queue and lifecycle invariants remain hard failures. Resource regressions are
compared against explicit configured budgets rather than the developer machine.

## Failure Handling

Malformed or unsupported contract versions produce a visible error and no
recovery controls. Snapshot collection tolerates missing or partially written
runtime files by reporting degraded state. A corrupt trace line is ignored as
it is today. Recovery acquires the existing lock non-destructively and reports
busy state instead of waiting indefinitely.

The soak harness always tears down isolated child processes in a `finally`
path. A failed scenario preserves only its redacted report when requested; the
temporary runtime directory is otherwise removed.

## Testing And Verification

- Python unit tests cover snapshot classification, privacy, lifecycle
  correlation, recommendations, action allowlisting, and lock-safe pruning.
- CLI tests cover JSON schemas, exit codes, parser routing, and failures.
- Swift tests cover contract decoding, view-state mapping, action enablement,
  unsupported versions, and error presentation.
- Quick soak runs in normal CI on supported Python versions and platforms with
  a bounded workload.
- Extended soak runs in a separate scheduled/manual workflow so pull requests
  remain fast.
- Existing Python, Swift, smoke, clean-install, security, and packaging checks
  remain required.

## Documentation And Release Boundary

The README receives only a short Reliability Center mention. CLI details,
privacy guarantees, recovery behavior, and soak commands belong in the command,
privacy, support, and contributing documentation. The changelog records the new
contract and test evidence.

This feature improves confidence toward 1.0 but does not promote Preview
platforms, claim real-device Windows/Linux playback coverage, or change the
macOS app's signing/notarization status.

## Acceptance Criteria

- CLI and macOS app agree through diagnostics contract version `1`.
- The app explains recent delivery outcomes without storing or displaying text.
- Only the three allowlisted recovery actions are exposed.
- Active queue work survives expired-job pruning.
- Quick and extended soak modes produce deterministic privacy-safe reports.
- The complete existing test and release verification suites still pass.
- Normal runtime behavior adds no daemon and no periodic diagnostics process.
