from jarvis_line.queue_policy import dequeue_next, schedule_job


def make_job(message_id, session, phase, ts):
    return {
        "message_id": message_id,
        "session_key": session,
        "phase": phase,
        "jarvis_line": message_id,
        "enqueued_ts_ms": ts,
    }


def test_final_replaces_same_session_commentary():
    queued = [make_job("c1", "a", "commentary", 10)]

    result = schedule_job(queued, make_job("f1", "a", "final", 20), 8, 0)

    assert [job["message_id"] for job in result] == ["f1"]


def test_trimming_drops_commentary_before_final():
    queued = [
        make_job("f1", "a", "final", 10),
        make_job("c1", "b", "commentary", 20),
    ]

    result = schedule_job(queued, make_job("f2", "c", "final", 30), 2, 0)

    assert [job["message_id"] for job in result] == ["f1", "f2"]


def test_dequeue_prefers_final_and_rotates_sessions():
    queued = [
        make_job("c1", "a", "commentary", 10),
        make_job("f1", "a", "final", 20),
        make_job("f2", "b", "final", 30),
    ]

    job, remaining, session = dequeue_next(queued, "a")

    assert job["message_id"] == "f2"
    assert session == "b"
    assert [item["message_id"] for item in remaining] == ["c1", "f1"]


def test_dequeue_uses_oldest_priority_job_when_one_session_is_available():
    queued = [
        make_job("f1", "a", "final", 10),
        make_job("f2", "a", "final", 20),
    ]

    job, remaining, session = dequeue_next(queued, "a")

    assert job["message_id"] == "f1"
    assert [item["message_id"] for item in remaining] == ["f2"]
    assert session == "a"


def test_duplicate_message_id_is_coalesced():
    queued = [make_job("same", "a", "commentary", 10)]

    result = schedule_job(queued, make_job("same", "a", "commentary", 20), 8, 0)

    assert len(result) == 1
    assert result[0]["enqueued_ts_ms"] == 20


def test_stale_jobs_are_removed_before_scheduling():
    queued = [make_job("old", "a", "final", 10)]

    result = schedule_job(queued, make_job("new", "b", "commentary", 30), 8, 20)

    assert [job["message_id"] for job in result] == ["new"]
