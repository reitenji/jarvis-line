# Storage Cleanup

## Goal

Keep Jarvis Line's generated runtime artifacts bounded without adding a
continuously running maintenance process or risking user-owned data. Provide
the same safe cleanup behavior through the watcher, CLI, and macOS app.

## Current Behavior

- Generated speech files are normally removed after playback when
  `delete_after_play` is enabled, but interrupted playback or a crash can leave
  files behind.
- Watcher and audio-worker logs rotate at a fixed size, and the structured trace
  is already capped, so current diagnostics are bounded but old rotated files
  can remain.
- Queue, cache, state, lock, and temporary files live in Jarvis Line's managed
  runtime directories. Some can survive an abnormal shutdown.
- Users can clear the speech queue and trace independently, but there is no
  single inventory, preview, or cleanup command.
- The app does not show reclaimable storage or the last maintenance result.

## Considered Approaches

### Clean On Every Speech Event

Scan after each generated or played line. This removes leftovers quickly, but
adds repeated filesystem work to the latency-sensitive path and creates more
opportunities for cleanup and playback to overlap.

### Operating-System Scheduler

Install a LaunchAgent, scheduled task, or cron job. This keeps maintenance
independent from the watcher, but introduces another installed component,
cross-platform lifecycle differences, and an additional process surface.

### Shared Interval-Based Cleanup Service

Use one cleanup service from the watcher, CLI, and macOS app. The watcher makes
a non-blocking due check at startup and then passes through an in-memory hourly
gate during its existing loop. A bounded state record ensures that actual work
runs at most once per configured interval. This is the selected approach
because it adds no daemon or timer, keeps behavior consistent, and stays outside
the speech hot path.

## Architecture

A Python cleanup module owns the complete allowlist, eligibility rules, scan,
deletion, and structured result. Callers do not delete files directly.

The module exposes three operations:

1. `inspect` returns cleanup candidates and estimated reclaimable bytes without
   changing files or scheduling state.
2. `run` removes eligible candidates and returns a per-category result.
3. `run_if_due` checks configuration and bounded maintenance state, acquires a
   non-blocking cleanup lock, and calls `run` only when the interval has elapsed.

The watcher calls `run_if_due` outside message extraction and playback. The CLI
calls `inspect` or `run` directly. The macOS app invokes the CLI's JSON contract
through its existing model boundary rather than implementing filesystem logic
in Swift.

Only one cleanup may run at a time. A second caller skips immediately and
reports that maintenance is already active. The maintenance state stores the
last attempt and last successful run in one atomically replaced, bounded JSON
record. Scheduling uses the last attempt so a persistent permission error does
not trigger a scan on every watcher iteration; the UI reports the last success
separately.

## Managed Categories

### Generated Audio

- Scope is limited to regular files directly inside Jarvis Line's fixed
  generated-audio directory under its managed data root. A custom TTS output
  path outside that root is never scanned.
- Automatic cleanup removes files older than 24 hours.
- Manual cleanup retains a ten-minute safety window and skips files recent
  enough to be in generation or playback.
- Model files, voice files, and parent TTS directories are never candidates.

### Diagnostics

- Current watcher and worker logs keep their existing size-based rotation.
- Only known rotated log files older than seven days are cleanup candidates.
- The current structured trace keeps its existing cap and trim behavior.
- User-created support reports and pasted issue diagnostics are never cleanup
  candidates.

### Runtime Temporary Artifacts

- Scope is limited to known Jarvis Line temporary names and lock artifacts in
  its managed runtime directories.
- Temporary files must be older than one hour.
- A lock artifact is eligible only when it is old, its recorded owner is no
  longer alive when ownership data exists, and the cleanup process can prove it
  is not currently held.
- Queue, latest-message cache, watcher state, cleanup state, and current lock
  files are not deleted.

## Safety Boundaries

- Every root is an explicit Jarvis Line managed path. Cleanup never scans a home
  directory, repository, or arbitrary configured parent.
- Directory traversal uses streaming enumeration and does not recursively walk
  beyond an explicitly managed directory.
- Entries are inspected with `lstat`; symbolic links are skipped and never
  followed.
- Only regular files and recognized stale lock directories can be removed.
- Candidate paths are checked again immediately before deletion to reduce
  time-of-check/time-of-use risk.
- Missing files are treated as a harmless concurrent cleanup result.
- A failure on one entry is recorded and does not stop other eligible entries.
- Automatic cleanup errors never stop watcher startup, message handling, queue
  processing, or speech playback.
- Configuration, hooks, Kokoro models, custom TTS assets, and user-created
  reports are explicitly outside the cleanup contract.

## Configuration

Add two bounded user-facing settings:

- `cleanup_enabled`: boolean, default `true`.
- `cleanup_interval_hours`: allowed values `24` and `168`, default `24`.

The app presents these as an automatic-cleanup toggle and a Daily or Weekly
picker. No free-form interval or path field is exposed. Age thresholds remain
safe product defaults rather than editable values.

Disabling automatic cleanup affects only `run_if_due`; inspection and manual
cleanup remain available.

## CLI Contract

```text
jarvis-line cleanup status
jarvis-line cleanup run
jarvis-line cleanup status --json
jarvis-line cleanup run --json
```

Human-readable output reports eligible or removed file count, byte total,
skipped active entries, per-entry errors, and the last successful cleanup time.
The JSON shape is stable and includes:

```json
{
  "mode": "status",
  "eligible_files": 4,
  "eligible_bytes": 50331648,
  "removed_files": 0,
  "removed_bytes": 0,
  "skipped_files": 1,
  "errors": [],
  "last_success_at": null
}
```

`status` is always read-only and does not update last-attempt or last-success
state. `run` exits successfully when cleanup completes with no entry errors. A
partial result is printed in full and uses a non-zero exit status without
rolling back successful deletions.

## macOS App

Add a **Storage & Cleanup** group to Diagnostics with:

- automatic cleanup toggle;
- Daily or Weekly frequency picker;
- last successful cleanup time;
- reclaimable file count and storage estimate;
- refresh action;
- **Clean Now** command;
- concise success, partial-success, and failure feedback.

Opening Diagnostics or pressing refresh uses `cleanup status --json`. Clean Now
uses `cleanup run --json`, then refreshes status. The command is disabled while
cleanup is active. The UI never displays or accepts filesystem paths.

Configuration changes continue through the existing staged settings flow. The
cleanup command itself does not restart the watcher because active runtime
state is excluded from deletion.

## Resource Use

- No new persistent process, scheduler, polling thread, or filesystem watcher
  is introduced.
- The watcher checks a monotonic in-memory deadline first. At most once per
  hour, a due check reads one small state record and returns immediately when
  maintenance is not due.
- Scans use streaming directory enumeration and retain only result counters and
  at most 50 redacted error details in memory.
- Cleanup stays outside extraction, queue insertion, synthesis, and playback
  critical paths.

## Failure Handling

- Invalid or inaccessible managed roots produce a redacted per-category error.
- Permission failures are reported without retry loops.
- The last-attempt timestamp prevents repeated automatic scans after a partial
  or failed run; a manual run remains possible.
- The last-success timestamp advances only when the scan completes without
  entry errors.
- CLI and app output never include file contents, secrets, or paths outside the
  managed Jarvis Line roots.

## Documentation

- Add cleanup settings and defaults to `docs/CONFIGURATION.md`.
- Add command syntax and example output to `docs/COMMANDS.md`.
- Mention automatic cleanup and the Diagnostics control in the app guidance.
- Keep the README concise and link to the detailed command/configuration docs.

## Verification

- Unit tests use temporary managed roots and controlled timestamps.
- Tests cover every age boundary, automatic-disabled behavior, Daily and Weekly
  scheduling, dry inspection, successful deletion, partial failure, and state
  timestamp rules.
- Security tests cover symlinks, unexpected names, directories in file slots,
  paths outside allowlisted roots, and files that change between inspection and
  deletion.
- Concurrency tests prove that simultaneous app, CLI, and watcher cleanup calls
  do not overlap.
- CLI tests cover human and JSON output plus exit status for success, partial
  failure, and already-running cleanup.
- macOS model tests cover parsing, loading, command state, and result feedback.
- Existing Python tests, shell smoke tests, Swift tests, debug build, and release
  build remain green.
- The packaged app is installed locally and checked for configuration
  persistence, manual cleanup, and uninterrupted speech after automatic
  maintenance.

## Scope Boundaries

- Cleanup does not remove or reinstall hooks, models, voices, configuration,
  launch agents, application bundles, or support reports.
- Cleanup does not clear live speech queue or latest-message state.
- Cleanup does not replace existing queue-clear or trace-clear commands.
- No operating-system cleanup service is installed.
- Release creation and promotion through `develop` and `main` occur only after
  implementation, review, and verification in the dedicated feature branch.
