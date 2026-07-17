from __future__ import annotations

import hashlib
from typing import Any


FINAL_PHASES = {"final", "final_answer", "final-response", "final_response"}
ATTENTION_PHASES = {"attention"}
ATTENTION_CANCELLATION_KEY_CHARS = 24


def is_final_phase(phase: str) -> bool:
    return str(phase or "").strip().lower() in FINAL_PHASES


def is_attention_phase(phase: str) -> bool:
    return str(phase or "").strip().lower() in ATTENTION_PHASES


def attention_cancellation_key(
    session_key: object,
    attention_type: object,
    correlation_token: object,
) -> str | None:
    parts = [
        str(value or "").strip()
        for value in (session_key, attention_type, correlation_token)
    ]
    if not all(parts):
        return None
    payload = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:ATTENTION_CANCELLATION_KEY_CHARS]


def prune_attention_cancellations(
    cancellations: object,
    stale_before_ms: int,
    max_entries: int,
) -> dict[str, int]:
    if not isinstance(cancellations, dict):
        return {}
    active: list[tuple[str, int]] = []
    for key, raw_timestamp in cancellations.items():
        try:
            timestamp = int(raw_timestamp)
        except (TypeError, ValueError):
            continue
        if isinstance(key, str) and key and timestamp >= stale_before_ms:
            active.append((key, timestamp))
    active.sort(key=lambda item: item[1], reverse=True)
    return dict(active[:max_entries])


def phase_priority(phase: object) -> int:
    normalized = str(phase or "").strip().lower()
    if is_attention_phase(normalized):
        return 2
    if is_final_phase(normalized):
        return 1
    return 0


def _not_expired(job: dict[str, Any], now_ms: int | None) -> bool:
    if now_ms is None:
        return True
    expires_ts_ms = int(job.get("expires_ts_ms") or 0)
    return not expires_ts_ms or expires_ts_ms > now_ms


def _replaced_by_attention(
    job: dict[str, Any],
    session_key: object,
    attention_type: str,
) -> bool:
    if job.get("session_key") != session_key:
        return False
    phase = str(job.get("phase") or "")
    if phase_priority(phase) == 0:
        return True
    return is_attention_phase(phase) and str(job.get("attention_type") or "") == attention_type


def schedule_job(
    jobs: list[dict[str, Any]],
    new_job: dict[str, Any],
    max_jobs: int,
    stale_before_ms: int,
) -> list[dict[str, Any]]:
    now_ms = int(new_job.get("enqueued_ts_ms") or 0) or None
    active = [
        dict(job)
        for job in jobs
        if int(job.get("enqueued_ts_ms") or 0) >= stale_before_ms
        and _not_expired(job, now_ms)
    ]
    message_id = new_job.get("message_id")
    session_key = new_job.get("session_key")
    new_is_final = is_final_phase(str(new_job.get("phase") or ""))
    new_is_attention = is_attention_phase(str(new_job.get("phase") or ""))
    attention_type = str(new_job.get("attention_type") or "")

    active = [job for job in active if job.get("message_id") != message_id]
    if new_is_final:
        active = [job for job in active if job.get("session_key") != session_key]
    elif new_is_attention:
        active = [
            job
            for job in active
            if not _replaced_by_attention(job, session_key, attention_type)
        ]
    else:
        active = [
            job
            for job in active
            if not (
                job.get("session_key") == session_key
                and phase_priority(job.get("phase")) == 0
            )
        ]

    active.append(dict(new_job))
    while max_jobs > 0 and len(active) > max_jobs:
        lowest_priority = min(phase_priority(job.get("phase")) for job in active)
        removable = [
            index
            for index, job in enumerate(active)
            if phase_priority(job.get("phase")) == lowest_priority
        ]
        drop_index = min(
            removable,
            key=lambda index: (int(active[index].get("enqueued_ts_ms") or 0), index),
        )
        active.pop(drop_index)
    return active


def dequeue_next(
    jobs: list[dict[str, Any]],
    last_session_key: str,
    now_ms: int | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    active = [dict(job) for job in jobs if _not_expired(job, now_ms)]
    if not active:
        return None, [], last_session_key

    highest_priority = max(phase_priority(job.get("phase")) for job in active)
    priority_indices = [
        index
        for index, job in enumerate(active)
        if phase_priority(job.get("phase")) == highest_priority
    ]
    rotated_indices = [
        index
        for index in priority_indices
        if str(active[index].get("session_key") or "") != last_session_key
    ]
    candidate_indices = rotated_indices or priority_indices
    selected_index = min(
        candidate_indices,
        key=lambda index: (int(active[index].get("enqueued_ts_ms") or 0), index),
    )

    remaining = active
    selected = remaining.pop(selected_index)
    selected_session = str(selected.get("session_key") or "")
    return selected, remaining, selected_session
