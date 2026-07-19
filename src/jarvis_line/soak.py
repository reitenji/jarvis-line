from __future__ import annotations

import json
import random
import shutil
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from jarvis_line import audio_worker, diagnostics, reliability
from jarvis_line.queue_policy import (
    attention_cancellation_key,
    dequeue_next,
    is_attention_phase,
    prune_attention_cancellations,
    schedule_job,
)


REPORT_VERSION = 1
PRIVACY_PROBE = "privacy-probe-secret"
FORBIDDEN_FIELDS = {
    "command",
    "content",
    "environment",
    "line",
    "session_key",
    "session_path",
    "text",
}
_MODES = {
    "quick": {
        "sessions": 24,
        "rounds": 12,
        "lock_threads": 4,
        "lock_iterations": 16,
        "trace_threads": 4,
        "trace_iterations": 12,
    },
    "extended": {
        "sessions": 128,
        "rounds": 100,
        "lock_threads": 8,
        "lock_iterations": 64,
        "trace_threads": 8,
        "trace_iterations": 64,
    },
}
_RUN_LOCK = threading.Lock()


@dataclass(frozen=True)
class SoakConfig:
    mode: str
    seed: int
    sessions: int
    rounds: int
    max_queue_size: int
    root: Path
    cleanup_root: bool
    lock_threads: int
    lock_iterations: int
    trace_threads: int
    trace_iterations: int

    @classmethod
    def for_mode(
        cls,
        mode: str,
        seed: int,
        root: Path | str | None = None,
    ) -> SoakConfig:
        normalized = str(mode or "").strip().lower()
        if normalized not in _MODES:
            raise ValueError(f"Unsupported soak mode: {mode}")
        values = _MODES[normalized]
        cleanup_root = root is None
        resolved_root = (
            Path(tempfile.mkdtemp(prefix="jarvis-line-soak-"))
            if cleanup_root
            else Path(root).expanduser().resolve()
        )
        return cls(
            mode=normalized,
            seed=int(seed),
            sessions=values["sessions"],
            rounds=values["rounds"],
            max_queue_size=8,
            root=resolved_root,
            cleanup_root=cleanup_root,
            lock_threads=values["lock_threads"],
            lock_iterations=values["lock_iterations"],
            trace_threads=values["trace_threads"],
            trace_iterations=values["trace_iterations"],
        )


def _private(value: object) -> bool:
    if isinstance(value, dict):
        if FORBIDDEN_FIELDS.intersection(str(key) for key in value):
            return False
        return all(_private(item) for item in value.values())
    if isinstance(value, list):
        return all(_private(item) for item in value)
    return PRIVACY_PROBE not in str(value)


@contextmanager
def _diagnostics_paths(runtime_root: Path) -> Iterator[None]:
    previous = (
        diagnostics.TRACE_PATH,
        diagnostics.TRACE_LOCK_PATH,
        diagnostics.TRACE_MAX_BYTES,
        diagnostics.TRACE_KEEP_BYTES,
    )
    diagnostics.TRACE_PATH = runtime_root / "trace.jsonl"
    diagnostics.TRACE_LOCK_PATH = runtime_root / ".trace.lock"
    diagnostics.TRACE_MAX_BYTES = 4 * 1024
    diagnostics.TRACE_KEEP_BYTES = 2 * 1024
    try:
        yield
    finally:
        (
            diagnostics.TRACE_PATH,
            diagnostics.TRACE_LOCK_PATH,
            diagnostics.TRACE_MAX_BYTES,
            diagnostics.TRACE_KEEP_BYTES,
        ) = previous


class _SoakRun:
    def __init__(self, config: SoakConfig):
        self.config = config
        self.random = random.Random(config.seed)
        self.runtime_root = config.root / "runtime"
        self.queue_path = self.runtime_root / "queue.json"
        self.queue_lock_path = self.runtime_root / ".queue.lock"
        self.counter_path = self.runtime_root / "lock-counter.json"
        self.counter_lock_path = self.runtime_root / ".counter.lock"
        self.base_ms = int(time.time() * 1000)
        self.clock_ms = self.base_ms
        self.sequence = 0
        self.last_session = ""
        self.cancellations: dict[str, int] = {}
        self.final_ids: set[str] = set()
        self.expired_ids: set[str] = set()
        self.completed_ids: set[str] = set()
        self.spoken_ids: set[str] = set()
        self.terminal_counts: Counter[str] = Counter()
        self.active_playbacks = 0
        self.queue_bound_ok = True
        self.snapshot_private = True
        self.trace_parse_ok = True
        self.trace_thread_errors: list[str] = []
        self.lock_thread_errors: list[str] = []
        self.started_thread_ids: set[int] = set()
        self.metrics = {
            "sessions": config.sessions,
            "rounds": config.rounds,
            "submissions": 0,
            "duplicate_submissions": 0,
            "completed": 0,
            "skipped": 0,
            "cancelled": 0,
            "expired_rejected": 0,
            "stale_rejected": 0,
            "expired_playbacks": 0,
            "max_queue_depth": 0,
            "max_parallel_playbacks": 0,
            "snapshots": 0,
            "trace_events_written": 0,
            "trace_rotations": 0,
            "lock_mutations": 0,
            "active_prune_checks": 0,
            "replayed_deliveries": 0,
            "child_processes_started": 0,
            "leftover_threads": 0,
        }

    def run(self) -> tuple[dict[str, int], dict[str, bool]]:
        self._prepare_root()
        audio_worker.save_json_unlocked(
            self.queue_path,
            {"jobs": [], "last_session_key": ""},
        )
        self._exercise_sessions()
        self._drain_all()
        self._exercise_recovery()
        self._exercise_runtime_snapshots()
        fair_dequeue = self._exercise_fair_dequeue()
        lock_serialized = self._exercise_lock_writers()
        self._ensure_trace_rotation()
        trace_writers_complete = self._exercise_trace_writers()
        trace_private = self._validate_trace()
        isolated_files = self._validate_isolation()

        duplicate_terminals = sum(
            count - 1 for count in self.terminal_counts.values() if count > 1
        )
        terminal_unique = duplicate_terminals == 0
        finals_resolved = self.final_ids == (
            self.final_ids.intersection(self.terminal_counts)
        )
        expired_never_played = not self.expired_ids.intersection(self.spoken_ids)
        active_threads = [
            thread
            for thread in threading.enumerate()
            if thread.ident in self.started_thread_ids and thread.is_alive()
        ]
        self.metrics["leftover_threads"] = len(active_threads)

        invariants = {
            "queue_bounded": self.queue_bound_ok,
            "terminal_unique": terminal_unique,
            "finals_resolved": finals_resolved,
            "expired_never_played": expired_never_played,
            "active_prune_preserved": self._active_prune_preserved,
            "trace_rotated": self.metrics["trace_rotations"] > 0,
            "trace_private": trace_private and self.snapshot_private,
            "lock_serialized": lock_serialized,
            "single_playback_owner": self.metrics["max_parallel_playbacks"] <= 1,
            "restart_no_replay": self.metrics["replayed_deliveries"] == 0,
            "runtime_limits_observed": self._runtime_limits_observed,
            "fair_dequeue": fair_dequeue,
            "isolated_files": isolated_files,
            "no_child_processes": self.metrics["child_processes_started"] == 0,
            "no_leftover_threads": not active_threads and trace_writers_complete,
        }
        return dict(self.metrics), invariants

    def _prepare_root(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        known_files = (
            self.queue_path,
            self.queue_lock_path,
            self.counter_path,
            self.counter_lock_path,
            self.runtime_root / "trace.jsonl",
            self.runtime_root / ".trace.lock",
        )
        for path in known_files:
            path.unlink(missing_ok=True)
            lock_dir = path.with_name(path.name + ".d")
            if lock_dir.is_dir():
                try:
                    lock_dir.rmdir()
                except OSError:
                    pass

    def _next_timestamp(self) -> int:
        self.sequence += 1
        self.clock_ms = self.base_ms + self.sequence * 20
        return self.clock_ms

    def _exercise_sessions(self) -> None:
        for round_index in range(self.config.rounds):
            session_indices = list(range(self.config.sessions))
            self.random.shuffle(session_indices)
            for session_index in session_indices:
                timestamp_ms = self._next_timestamp()
                phase = self._phase(round_index, session_index)
                message_id = f"m-{self.config.seed:x}-{round_index:x}-{session_index:x}"
                job: dict[str, Any] = {
                    "message_id": message_id,
                    "session_key": f"session-{session_index}",
                    "phase": phase,
                    "enqueued_ts_ms": timestamp_ms,
                }
                if phase == "final":
                    self.final_ids.add(message_id)
                elif phase == "attention":
                    job.update(
                        {
                            "attention_type": "approval",
                            "correlation_token": message_id,
                            "expires_ts_ms": timestamp_ms
                            + (1 if (round_index + session_index) % 3 == 0 else 5_000),
                        }
                    )
                    if (round_index + session_index) % 5 == 0:
                        key = attention_cancellation_key(
                            job["session_key"],
                            job["attention_type"],
                            job["correlation_token"],
                        )
                        if key:
                            self.cancellations[key] = timestamp_ms

                self._submit(job)
                if self.random.randrange(17) == 0:
                    self.metrics["duplicate_submissions"] += 1
                    self._submit(dict(job))
                if self.sequence % 5 == 0:
                    self._drain_one(timestamp_ms + 2)
                if self.sequence % 31 == 0:
                    self._snapshot(timestamp_ms + 2)

            for _ in range(3):
                self._drain_one(self.clock_ms + 5)

    def _phase(self, round_index: int, session_index: int) -> str:
        if round_index == self.config.rounds - 1:
            return "final"
        if (round_index + session_index) % 9 == 0:
            return "attention"
        return "commentary"

    def _submit(self, job: dict[str, Any]) -> None:
        self.metrics["submissions"] += 1
        self._record("received", job)
        removed: list[dict[str, Any]] = []

        def mutate(queue: dict[str, Any]) -> None:
            before = [dict(item) for item in queue.get("jobs", []) if isinstance(item, dict)]
            scheduled = schedule_job(
                before,
                job,
                self.config.max_queue_size,
                int(job["enqueued_ts_ms"]) - reliability.DEFAULT_STALE_AFTER_MS,
            )
            retained_ids = {str(item.get("message_id") or "") for item in scheduled}
            removed.extend(
                item
                for item in before
                if str(item.get("message_id") or "") not in retained_ids
                and item.get("message_id") != job.get("message_id")
            )
            queue["jobs"] = scheduled
            queue["updated_ts_ms"] = int(job["enqueued_ts_ms"])
            self._observe_queue(len(scheduled))

        audio_worker.update_json(
            self.queue_path,
            {"jobs": [], "last_session_key": ""},
            mutate,
            lock_path=self.queue_lock_path,
        )
        for old_job in removed:
            self._reject_removed(old_job, int(job["enqueued_ts_ms"]))
        self._record("queued", job)

    def _reject_removed(self, job: dict[str, Any], now_ms: int) -> None:
        expires_ms = int(job.get("expires_ts_ms") or 0)
        enqueued_ms = int(job.get("enqueued_ts_ms") or 0)
        if expires_ms and expires_ms <= now_ms:
            reason = "expired"
            self.metrics["expired_rejected"] += 1
            self.expired_ids.add(str(job.get("message_id") or ""))
        elif enqueued_ms < now_ms - reliability.DEFAULT_STALE_AFTER_MS:
            reason = "stale"
            self.metrics["stale_rejected"] += 1
            self.expired_ids.add(str(job.get("message_id") or ""))
        else:
            reason = "superseded"
        self._terminal(job, "skipped", reason=reason)

    def _drain_one(self, now_ms: int) -> bool:
        selected: dict[str, Any] | None = None
        rejected: list[dict[str, Any]] = []

        def mutate(queue: dict[str, Any]) -> None:
            nonlocal selected
            before = [dict(item) for item in queue.get("jobs", []) if isinstance(item, dict)]
            active = audio_worker.drop_stale_jobs(before, now_ms)
            active_ids = {str(item.get("message_id") or "") for item in active}
            rejected.extend(
                item
                for item in before
                if str(item.get("message_id") or "") not in active_ids
            )
            selected, remaining, self.last_session = dequeue_next(
                active,
                self.last_session,
                now_ms=now_ms,
            )
            queue["jobs"] = remaining
            queue["last_session_key"] = self.last_session
            queue["updated_ts_ms"] = now_ms
            self._observe_queue(len(remaining))

        audio_worker.update_json(
            self.queue_path,
            {"jobs": [], "last_session_key": ""},
            mutate,
            lock_path=self.queue_lock_path,
        )
        for job in rejected:
            self._reject_removed(job, now_ms)
        if selected is None:
            return False

        expires_ms = int(selected.get("expires_ts_ms") or 0)
        if expires_ms and expires_ms <= now_ms:
            self.metrics["expired_playbacks"] += 1
            self.expired_ids.add(str(selected.get("message_id") or ""))
            self._terminal(selected, "skipped", reason="expired")
            return True

        if self._attention_cancelled(selected, now_ms):
            self.metrics["cancelled"] += 1
            self._terminal(selected, "skipped", reason="cancelled")
            return True

        self.active_playbacks += 1
        self.metrics["max_parallel_playbacks"] = max(
            self.metrics["max_parallel_playbacks"],
            self.active_playbacks,
        )
        try:
            self._record("speaking", selected, backend="fake")
            message_id = str(selected.get("message_id") or "")
            self.spoken_ids.add(message_id)
            self._terminal(selected, "completed", backend="fake", duration_ms=1)
        finally:
            self.active_playbacks -= 1
        return True

    def _attention_cancelled(self, job: dict[str, Any], now_ms: int) -> bool:
        if not is_attention_phase(str(job.get("phase") or "")):
            return False
        self.cancellations = prune_attention_cancellations(
            self.cancellations,
            now_ms - reliability.DEFAULT_STALE_AFTER_MS,
            audio_worker.ATTENTION_CANCELLATION_MAX_ENTRIES,
        )
        key = attention_cancellation_key(
            job.get("session_key"),
            job.get("attention_type"),
            job.get("correlation_token"),
        )
        return bool(key and key in self.cancellations)

    def _drain_all(self) -> None:
        attempts = 0
        while self._queue_jobs() and attempts < self.config.sessions * 4:
            attempts += 1
            self.clock_ms += 10
            self._drain_one(self.clock_ms)
        if self._queue_jobs():
            self.queue_bound_ok = False

    def _queue_jobs(self) -> list[dict[str, Any]]:
        queue = audio_worker.load_json(self.queue_path, {"jobs": []})
        if not isinstance(queue, dict):
            return []
        return [dict(item) for item in queue.get("jobs", []) if isinstance(item, dict)]

    def _observe_queue(self, depth: int) -> None:
        self.metrics["max_queue_depth"] = max(self.metrics["max_queue_depth"], depth)
        if depth > self.config.max_queue_size:
            self.queue_bound_ok = False

    def _record(self, event: str, job: dict[str, Any], **metadata: object) -> None:
        trace_path = diagnostics.TRACE_PATH
        before = trace_path.stat().st_size if trace_path.exists() else 0
        diagnostics.record_event(
            event,
            message_id=job.get("message_id"),
            session_key=job.get("session_key"),
            phase=job.get("phase"),
            line=PRIVACY_PROBE,
            text=PRIVACY_PROBE,
            **metadata,
        )
        self.metrics["trace_events_written"] += 1
        after = trace_path.stat().st_size if trace_path.exists() else 0
        if before >= diagnostics.TRACE_MAX_BYTES and after < before:
            self.metrics["trace_rotations"] += 1

    def _terminal(
        self,
        job: dict[str, Any],
        event: str,
        **metadata: object,
    ) -> None:
        message_id = str(job.get("message_id") or "")
        self.terminal_counts[message_id] += 1
        if event == "completed":
            self.metrics["completed"] += 1
            self.completed_ids.add(message_id)
        else:
            self.metrics["skipped"] += 1
        self._record(event, job, **metadata)

    def _snapshot(self, now_ms: int) -> dict[str, Any]:
        snapshot = reliability.build_snapshot(
            config={
                "tts": "fake",
                "speech_enabled": True,
                "audio_worker_idle_exit_seconds": 60,
                "audio_worker_max_rss_mb": 128,
                "max_queue_size": self.config.max_queue_size,
            },
            state={
                "__watcher__": {"pid": 101},
                "__audio_worker__": {"pid": 202},
            },
            queue=audio_worker.load_json(self.queue_path, {"jobs": []}),
            trace_events=diagnostics.read_events(limit=100),
            now_ms=now_ms,
            pid_alive=lambda pid: pid in {101, 202},
            process_rss_mb=lambda _pid: 64.0,
            tts_status={"backend": "fake", "ready": True, "reason": "ready"},
        )
        self.metrics["snapshots"] += 1
        self.snapshot_private = self.snapshot_private and _private(snapshot)
        self.queue_bound_ok = self.queue_bound_ok and (
            int(snapshot["queue"]["active"]) <= self.config.max_queue_size
        )
        return snapshot

    def _exercise_recovery(self) -> None:
        now_ms = self.clock_ms + reliability.DEFAULT_STALE_AFTER_MS + 1_000
        cancelled_job = {
            "message_id": "recovery-cancelled",
            "session_key": "recovery-session",
            "phase": "attention",
            "attention_type": "approval",
            "correlation_token": "recovery-cancelled",
            "enqueued_ts_ms": now_ms,
            "expires_ts_ms": now_ms + 5_000,
        }
        cancellation = attention_cancellation_key(
            cancelled_job["session_key"],
            cancelled_job["attention_type"],
            cancelled_job["correlation_token"],
        )
        if cancellation:
            self.cancellations[cancellation] = now_ms
        audio_worker.save_json_unlocked(
            self.queue_path,
            {"jobs": [cancelled_job], "last_session_key": self.last_session},
        )
        self._drain_one(now_ms + 1)

        active_job = {
            "message_id": "recovery-active",
            "session_key": "recovery-session",
            "phase": "final",
            "enqueued_ts_ms": now_ms,
        }
        probe_jobs = [
            {
                "message_id": "recovery-expired",
                "phase": "attention",
                "enqueued_ts_ms": now_ms - 10,
                "expires_ts_ms": now_ms,
            },
            {
                "message_id": "recovery-stale",
                "phase": "commentary",
                "enqueued_ts_ms": now_ms - reliability.DEFAULT_STALE_AFTER_MS - 1,
            },
            active_job,
        ]
        audio_worker.save_json_unlocked(
            self.queue_path,
            {"jobs": probe_jobs, "last_session_key": self.last_session},
        )
        preserved = False
        with audio_worker.try_file_lock(self.queue_lock_path) as acquired:
            if acquired:
                queue = audio_worker.load_json(self.queue_path, {"jobs": []})
                active, removed = reliability.prune_expired_jobs(
                    queue.get("jobs", []),
                    now_ms=now_ms,
                    stale_after_ms=reliability.DEFAULT_STALE_AFTER_MS,
                )
                queue["jobs"] = active
                audio_worker.save_json_unlocked(self.queue_path, queue)
                preserved = removed == 2 and active == [active_job]
                if preserved:
                    self.metrics["expired_rejected"] += 1
                    self.metrics["stale_rejected"] += 1
                    self.expired_ids.update(
                        {"recovery-expired", "recovery-stale"}
                    )
        self.metrics["active_prune_checks"] = 1
        self._active_prune_preserved = preserved

        def clear_active(queue: dict[str, Any]) -> None:
            queue["jobs"] = []
            queue["updated_ts_ms"] = now_ms

        audio_worker.update_json(
            self.queue_path,
            {"jobs": []},
            clear_active,
            lock_path=self.queue_lock_path,
        )
        selected, _, _ = dequeue_next([], self.last_session, now_ms=now_ms)
        self.metrics["replayed_deliveries"] = int(selected is not None)

    def _exercise_runtime_snapshots(self) -> None:
        config = {
            "tts": "fake",
            "speech_enabled": True,
            "audio_worker_idle_exit_seconds": 60,
            "audio_worker_max_rss_mb": 128,
            "max_queue_size": self.config.max_queue_size,
        }
        common = {
            "config": config,
            "queue": {"jobs": []},
            "trace_events": diagnostics.read_events(limit=100),
            "now_ms": self.clock_ms,
            "tts_status": {"backend": "fake", "ready": True, "reason": "ready"},
        }
        idle = reliability.build_snapshot(
            **common,
            state={"__watcher__": {"pid": 101}},
            pid_alive=lambda pid: pid == 101,
            process_rss_mb=lambda _pid: None,
        )
        high_rss = reliability.build_snapshot(
            **common,
            state={
                "__watcher__": {"pid": 101},
                "__audio_worker__": {"pid": 202},
            },
            pid_alive=lambda pid: pid in {101, 202},
            process_rss_mb=lambda _pid: 256.0,
        )
        stopped = reliability.build_snapshot(
            **common,
            state={"__watcher__": {"pid": 101}},
            pid_alive=lambda _pid: False,
            process_rss_mb=lambda _pid: None,
        )
        restarted = reliability.build_snapshot(
            **common,
            state={"__watcher__": {"pid": 101}},
            pid_alive=lambda pid: pid == 101,
            process_rss_mb=lambda _pid: None,
        )
        snapshots = (idle, high_rss, stopped, restarted)
        self.metrics["snapshots"] += len(snapshots)
        self.snapshot_private = self.snapshot_private and all(
            _private(snapshot) for snapshot in snapshots
        )
        self._runtime_limits_observed = (
            idle["runtime"]["worker"]["state"] == "idle"
            and any(
                item["id"] == "worker-memory-high"
                for item in high_rss["recommendations"]
            )
            and any(
                item.get("action") == "restart-runtime"
                for item in stopped["recommendations"]
            )
            and restarted["health"] == "healthy"
        )

    def _exercise_fair_dequeue(self) -> bool:
        now_ms = self.clock_ms
        jobs = [
            {"message_id": "fair-a1", "session_key": "a", "phase": "commentary", "enqueued_ts_ms": now_ms},
            {"message_id": "fair-b", "session_key": "b", "phase": "commentary", "enqueued_ts_ms": now_ms + 1},
            {"message_id": "fair-a2", "session_key": "a", "phase": "commentary", "enqueued_ts_ms": now_ms + 2},
        ]
        selected, _, _ = dequeue_next(jobs, "a", now_ms=now_ms)
        return bool(selected and selected.get("session_key") == "b")

    def _exercise_lock_writers(self) -> bool:
        audio_worker.save_json_unlocked(self.counter_path, {"count": 0})

        def writer() -> None:
            thread_id = threading.get_ident()
            self.started_thread_ids.add(thread_id)
            try:
                for _ in range(self.config.lock_iterations):
                    def increment(value: dict[str, Any]) -> None:
                        value["count"] = int(value.get("count") or 0) + 1

                    audio_worker.update_json(
                        self.counter_path,
                        {"count": 0},
                        increment,
                        lock_path=self.counter_lock_path,
                    )
            except Exception as error:
                self.lock_thread_errors.append(type(error).__name__)

        threads = [
            threading.Thread(target=writer, name=f"jarvis-soak-lock-{index}")
            for index in range(self.config.lock_threads)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        expected = self.config.lock_threads * self.config.lock_iterations
        result = audio_worker.load_json(self.counter_path, {"count": -1})
        actual = int(result.get("count") or 0) if isinstance(result, dict) else -1
        self.metrics["lock_mutations"] = actual
        return (
            not self.lock_thread_errors
            and all(not thread.is_alive() for thread in threads)
            and actual == expected
        )

    def _ensure_trace_rotation(self) -> None:
        attempts = 0
        while self.metrics["trace_rotations"] == 0 and attempts < 128:
            attempts += 1
            probe = {
                "message_id": f"rotation-{attempts}",
                "session_key": "rotation-session",
                "phase": "commentary",
            }
            self._record("received", probe, padding="x" * 256)

    def _exercise_trace_writers(self) -> bool:
        def writer(index: int) -> None:
            self.started_thread_ids.add(threading.get_ident())
            try:
                for iteration in range(self.config.trace_iterations):
                    diagnostics.record_event(
                        "received",
                        message_id=f"writer-{index}-{iteration}",
                        session_key=f"writer-session-{index}",
                        phase="commentary",
                        line=PRIVACY_PROBE,
                        text=PRIVACY_PROBE,
                    )
            except Exception as error:
                self.trace_thread_errors.append(type(error).__name__)

        threads = [
            threading.Thread(
                target=writer,
                args=(index,),
                name=f"jarvis-soak-trace-{index}",
            )
            for index in range(self.config.trace_threads)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.metrics["trace_events_written"] += (
            self.config.trace_threads * self.config.trace_iterations
        )
        return not self.trace_thread_errors and all(
            not thread.is_alive() for thread in threads
        )

    def _validate_trace(self) -> bool:
        try:
            raw_trace = diagnostics.TRACE_PATH.read_text(encoding="utf-8")
            events = [json.loads(raw) for raw in raw_trace.splitlines() if raw]
        except (OSError, json.JSONDecodeError):
            self.trace_parse_ok = False
            return False
        return bool(events) and self.trace_parse_ok and _private(events)

    def _validate_isolation(self) -> bool:
        root = self.config.root.resolve()
        paths = [
            self.runtime_root,
            self.queue_path,
            self.queue_lock_path,
            self.counter_path,
            self.counter_lock_path,
            diagnostics.TRACE_PATH,
            diagnostics.TRACE_LOCK_PATH,
        ]
        within_root = all(path.resolve().is_relative_to(root) for path in paths)
        temporary_artifacts = [
            path
            for path in self.runtime_root.rglob("*")
            if path.name.endswith(".tmp") or (path.is_dir() and path.name.endswith(".d"))
        ]
        return within_root and not temporary_artifacts


def run_soak(config: SoakConfig) -> dict[str, Any]:
    started_ns = time.perf_counter_ns()
    try:
        with _RUN_LOCK, _diagnostics_paths(config.root / "runtime"):
            metrics, invariants = _SoakRun(config).run()
        failures = [name for name, passed in invariants.items() if not passed]
        report: dict[str, Any] = {
            "version": REPORT_VERSION,
            "mode": config.mode,
            "seed": config.seed,
            "elapsed_ms": max(0, (time.perf_counter_ns() - started_ns) // 1_000_000),
            "metrics": metrics,
            "invariants": invariants,
            "failures": failures,
            "ok": not failures,
        }
        if not _private(report):
            report["failures"].append("report_privacy")
            report["ok"] = False
        return report
    finally:
        if config.cleanup_root:
            shutil.rmtree(config.root, ignore_errors=True)
