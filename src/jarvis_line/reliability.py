from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any


SNAPSHOT_VERSION = 1
DEFAULT_STALE_AFTER_MS = 90_000
DELIVERY_LIMIT = 12
RECENT_FAILURE_WINDOW_MS = 5 * 60 * 1000
ALLOWED_RECOVERY_ACTIONS = {
    "prune-expired",
    "restart-runtime",
    "test-tts",
}

_DELIVERY_EVENTS = {
    "received",
    "queued",
    "speaking",
    "completed",
    "failed",
    "skipped",
}
_PHASES = {"attention", "commentary", "final"}
_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_:-]{0,63}$")
_SESSION_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def correlation_id(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError, OverflowError):
        return default


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _safe_code(value: object, *, max_length: int = 64) -> str:
    text = str(value or "").strip().lower()[:max_length]
    if not text or not _CODE_PATTERN.fullmatch(text):
        return "unknown"
    return text


def _safe_phase(value: object) -> str:
    phase = str(value or "").strip().lower()
    return phase if phase in _PHASES else "unknown"


def _safe_session_id(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if _SESSION_PATTERN.fullmatch(text) else ""


def prune_expired_jobs(
    jobs: Iterable[object],
    *,
    now_ms: int,
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS,
) -> tuple[list[Any], int]:
    active: list[Any] = []
    removed = 0
    stale_before_ms = now_ms - max(0, int(stale_after_ms))
    for raw_job in jobs:
        if not isinstance(raw_job, dict):
            active.append(raw_job)
            continue
        enqueued_ts_ms = _integer(raw_job.get("enqueued_ts_ms"))
        expires_ts_ms = _integer(raw_job.get("expires_ts_ms"))
        expired = bool(expires_ts_ms and expires_ts_ms <= now_ms)
        stale = enqueued_ts_ms < stale_before_ms
        if expired or stale:
            removed += 1
            continue
        active.append(dict(raw_job))
    return active, removed


def classify_queue(
    jobs: Iterable[object],
    *,
    now_ms: int,
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS,
    max_size: int = 0,
) -> dict[str, Any]:
    total = 0
    active = 0
    expired = 0
    stale = 0
    oldest_age_ms = 0
    phase_counts: Counter[str] = Counter()
    stale_before_ms = now_ms - max(0, int(stale_after_ms))

    for raw_job in jobs:
        if not isinstance(raw_job, dict):
            continue
        total += 1
        phase_counts[_safe_phase(raw_job.get("phase"))] += 1
        enqueued_ts_ms = _integer(raw_job.get("enqueued_ts_ms"))
        expires_ts_ms = _integer(raw_job.get("expires_ts_ms"))
        if enqueued_ts_ms:
            oldest_age_ms = max(oldest_age_ms, max(0, now_ms - enqueued_ts_ms))
        if expires_ts_ms and expires_ts_ms <= now_ms:
            expired += 1
        elif enqueued_ts_ms < stale_before_ms:
            stale += 1
        else:
            active += 1

    return {
        "total": total,
        "active": active,
        "expired": expired,
        "stale": stale,
        "oldest_age_ms": oldest_age_ms,
        "phase_counts": dict(sorted(phase_counts.items())),
        "max_size": max(0, _integer(max_size)),
    }


def correlate_deliveries(
    events: Iterable[object],
    *,
    limit: int = DELIVERY_LIMIT,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    sortable_events = [event for event in events if isinstance(event, dict)]
    sortable_events.sort(key=lambda event: _integer(event.get("ts_ms")))

    for event in sortable_events:
        raw_message_id = str(event.get("message_id") or "")
        event_name = str(event.get("event") or "").strip().lower()
        if not raw_message_id or event_name not in _DELIVERY_EVENTS:
            continue
        timestamp_ms = max(0, _integer(event.get("ts_ms")))
        record = grouped.setdefault(
            raw_message_id,
            {
                "message_id": correlation_id(raw_message_id),
                "session_id": "",
                "phase": "unknown",
                "state": "received",
                "received_ts_ms": timestamp_ms,
                "updated_ts_ms": timestamp_ms,
            },
        )
        record["received_ts_ms"] = min(record["received_ts_ms"], timestamp_ms)
        record["updated_ts_ms"] = max(record["updated_ts_ms"], timestamp_ms)
        record["state"] = event_name

        if "session_id" in event:
            record["session_id"] = _safe_session_id(event.get("session_id"))
        if "phase" in event:
            record["phase"] = _safe_phase(event.get("phase"))
        if "backend" in event:
            record["backend"] = _safe_code(event.get("backend"), max_length=32)
        if "reason" in event:
            record["reason"] = _safe_code(event.get("reason"))
        for source_key, output_key in (
            ("queue_delay_ms", "queue_delay_ms"),
            ("duration_ms", "duration_ms"),
        ):
            value = _number(event.get(source_key))
            if value is not None:
                record[output_key] = max(0, value)

    ordered = sorted(
        grouped.values(),
        key=lambda record: (record["updated_ts_ms"], record["message_id"]),
        reverse=True,
    )
    bounded_limit = max(1, min(int(limit or DELIVERY_LIMIT), 100))
    return ordered[:bounded_limit]


def _process_state(
    state: Mapping[str, Any],
    key: str,
    *,
    pid_alive: Callable[[int], bool],
) -> tuple[int, bool]:
    raw = state.get(key)
    value = raw if isinstance(raw, dict) else {}
    pid = max(0, _integer(value.get("pid")))
    if not pid:
        return 0, False
    try:
        return pid, bool(pid_alive(pid))
    except Exception:
        return pid, False


def _recommendation(
    identifier: str,
    severity: str,
    title: str,
    detail: str,
    action: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": identifier,
        "severity": severity,
        "title": title,
        "detail": detail,
    }
    if action in ALLOWED_RECOVERY_ACTIONS:
        value["action"] = action
    return value


def build_snapshot(
    *,
    config: Mapping[str, Any],
    state: Mapping[str, Any],
    queue: Mapping[str, Any],
    trace_events: Iterable[object],
    now_ms: int,
    pid_alive: Callable[[int], bool],
    process_rss_mb: Callable[[int], float | None],
    tts_status: Mapping[str, Any],
) -> dict[str, Any]:
    safe_config = config if isinstance(config, Mapping) else {}
    safe_state = state if isinstance(state, Mapping) else {}
    safe_queue = queue if isinstance(queue, Mapping) else {}
    jobs = safe_queue.get("jobs")
    safe_jobs = jobs if isinstance(jobs, list) else []
    queue_summary = classify_queue(
        safe_jobs,
        now_ms=now_ms,
        stale_after_ms=DEFAULT_STALE_AFTER_MS,
        max_size=_integer(safe_config.get("max_queue_size")),
    )

    watcher_pid, watcher_alive = _process_state(
        safe_state,
        "__watcher__",
        pid_alive=pid_alive,
    )
    worker_pid, worker_alive = _process_state(
        safe_state,
        "__audio_worker__",
        pid_alive=pid_alive,
    )
    idle_exit_seconds = max(0, _integer(safe_config.get("audio_worker_idle_exit_seconds")))
    worker_idle = not worker_alive and queue_summary["active"] == 0 and idle_exit_seconds > 0
    speech_enabled = bool(safe_config.get("speech_enabled", True))

    worker_rss: float | None = None
    if worker_alive:
        try:
            measured_rss = process_rss_mb(worker_pid)
        except Exception:
            measured_rss = None
        if isinstance(measured_rss, (int, float)) and not isinstance(measured_rss, bool):
            worker_rss = round(max(0.0, float(measured_rss)), 1)

    runtime = {
        "speech_enabled": speech_enabled,
        "watcher": {
            "state": "running" if watcher_alive else "stopped",
            "pid": watcher_pid or None,
        },
        "worker": {
            "state": "running" if worker_alive else ("idle" if worker_idle else "stopped"),
            "pid": worker_pid or None,
            "rss_mb": worker_rss,
        },
    }

    deliveries = correlate_deliveries(trace_events, limit=DELIVERY_LIMIT)
    safe_tts = {
        "backend": _safe_code(tts_status.get("backend"), max_length=32),
        "ready": bool(tts_status.get("ready")),
        "reason": _safe_code(tts_status.get("reason")),
    }

    severity_rank = {"healthy": 0, "degraded": 1, "action_required": 2}
    health = "healthy"
    recommendations: list[dict[str, Any]] = []

    def add_recommendation(value: dict[str, Any]) -> None:
        nonlocal health
        if any(item["id"] == value["id"] for item in recommendations):
            return
        recommendations.append(value)
        if severity_rank[value["severity"]] > severity_rank[health]:
            health = value["severity"]

    if speech_enabled and not watcher_alive:
        add_recommendation(
            _recommendation(
                "runtime-restart",
                "action_required",
                "Restart voice runtime",
                "The watcher is not running.",
                "restart-runtime",
            )
        )
    elif speech_enabled and not worker_alive and queue_summary["active"] > 0:
        add_recommendation(
            _recommendation(
                "runtime-restart",
                "action_required",
                "Restart voice runtime",
                "Active speech is queued but the audio worker is not running.",
                "restart-runtime",
            )
        )

    rejected_jobs = queue_summary["expired"] + queue_summary["stale"]
    if rejected_jobs:
        noun = "entry" if rejected_jobs == 1 else "entries"
        add_recommendation(
            _recommendation(
                "expired-queue",
                "degraded",
                "Remove expired queue entries",
                f"{rejected_jobs} expired or stale {noun} is waiting."
                if rejected_jobs == 1
                else f"{rejected_jobs} expired or stale {noun} are waiting.",
                "prune-expired",
            )
        )

    if speech_enabled and not safe_tts["ready"]:
        add_recommendation(
            _recommendation(
                "tts-not-ready",
                "action_required",
                "Review the selected voice",
                "The selected TTS backend is not ready.",
                "test-tts",
            )
        )

    latest_delivery = deliveries[0] if deliveries else None
    if (
        latest_delivery
        and latest_delivery.get("state") == "failed"
        and now_ms - _integer(latest_delivery.get("updated_ts_ms")) <= RECENT_FAILURE_WINDOW_MS
    ):
        add_recommendation(
            _recommendation(
                "recent-speech-failure",
                "degraded",
                "Test the selected voice",
                "The most recent delivery failed.",
                "test-tts",
            )
        )

    rss_limit_mb = max(0, _integer(safe_config.get("audio_worker_max_rss_mb")))
    if worker_rss is not None and rss_limit_mb and worker_rss > rss_limit_mb:
        add_recommendation(
            _recommendation(
                "worker-memory-high",
                "degraded",
                "Worker memory is above its limit",
                "The worker will exit after draining active work.",
            )
        )

    return {
        "version": SNAPSHOT_VERSION,
        "generated_at_ms": max(0, int(now_ms)),
        "health": health,
        "runtime": runtime,
        "queue": queue_summary,
        "tts": safe_tts,
        "deliveries": deliveries,
        "recommendations": recommendations,
    }
