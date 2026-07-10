from __future__ import annotations

from typing import Any


FINAL_PHASES = {"final", "final_answer", "final-response", "final_response"}


def is_final_phase(phase: str) -> bool:
    return str(phase or "").strip().lower() in FINAL_PHASES


def schedule_job(
    jobs: list[dict[str, Any]],
    new_job: dict[str, Any],
    max_jobs: int,
    stale_before_ms: int,
) -> list[dict[str, Any]]:
    active = [
        dict(job)
        for job in jobs
        if int(job.get("enqueued_ts_ms") or 0) >= stale_before_ms
    ]
    message_id = new_job.get("message_id")
    session_key = new_job.get("session_key")
    new_is_final = is_final_phase(str(new_job.get("phase") or ""))

    active = [job for job in active if job.get("message_id") != message_id]
    if new_is_final:
        active = [job for job in active if job.get("session_key") != session_key]
    else:
        active = [
            job
            for job in active
            if not (
                job.get("session_key") == session_key
                and not is_final_phase(str(job.get("phase") or ""))
            )
        ]

    active.append(dict(new_job))
    while max_jobs > 0 and len(active) > max_jobs:
        commentary_index = next(
            (
                index
                for index, job in enumerate(active)
                if not is_final_phase(str(job.get("phase") or ""))
            ),
            0,
        )
        active.pop(commentary_index)
    return active


def dequeue_next(
    jobs: list[dict[str, Any]],
    last_session_key: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    if not jobs:
        return None, [], last_session_key

    final_indices = [
        index
        for index, job in enumerate(jobs)
        if is_final_phase(str(job.get("phase") or ""))
    ]
    priority_indices = final_indices or list(range(len(jobs)))
    rotated_indices = [
        index
        for index in priority_indices
        if str(jobs[index].get("session_key") or "") != last_session_key
    ]
    candidate_indices = rotated_indices or priority_indices
    selected_index = min(
        candidate_indices,
        key=lambda index: (int(jobs[index].get("enqueued_ts_ms") or 0), index),
    )

    remaining = list(jobs)
    selected = remaining.pop(selected_index)
    selected_session = str(selected.get("session_key") or "")
    return selected, remaining, selected_session
