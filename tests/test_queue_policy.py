from jarvis_line.queue_policy import (
    attention_cancellation_key,
    dequeue_next,
    prune_attention_cancellations,
    schedule_job,
)


def make_job(message_id, session, phase, ts, **extra):
    return {
        "message_id": message_id,
        "session_key": session,
        "phase": phase,
        "jarvis_line": message_id,
        "enqueued_ts_ms": ts,
        **extra,
    }


def test_attention_cancellation_key_is_private_and_deterministic():
    first = attention_cancellation_key("private-session", "input_required", "secret-token")

    assert first == attention_cancellation_key(
        "private-session", "input_required", "secret-token"
    )
    assert len(first) == 24
    assert "private-session" not in first
    assert "secret-token" not in first


def test_attention_cancellations_are_stale_pruned_and_bounded():
    cancellations = {
        "stale": 10,
        "old": 100,
        "middle": 200,
        "new": 300,
    }

    assert prune_attention_cancellations(cancellations, 100, 2) == {
        "new": 300,
        "middle": 200,
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


def test_attention_precedes_final_and_rotates_sessions():
    queued = [
        make_job("f1", "a", "final", 10),
        make_job(
            "a1",
            "b",
            "attention",
            20,
            attention_type="input_required",
            expires_ts_ms=100,
        ),
    ]

    job, remaining, session = dequeue_next(queued, "a", now_ms=25)

    assert job["message_id"] == "a1"
    assert session == "b"
    assert [item["message_id"] for item in remaining] == ["f1"]


def test_expired_attention_is_never_dequeued():
    queued = [
        make_job(
            "a1",
            "a",
            "attention",
            10,
            attention_type="input_required",
            expires_ts_ms=20,
        )
    ]

    job, remaining, session = dequeue_next(queued, "", now_ms=20)

    assert job is None
    assert remaining == []
    assert session == ""


def test_new_attention_replaces_same_type_and_removes_same_session_commentary():
    queued = [
        make_job("c1", "a", "commentary", 10),
        make_job("f1", "a", "final", 11),
        make_job("p1", "a", "attention", 12, attention_type="permission_request"),
        make_job("i1", "a", "attention", 13, attention_type="input_required"),
    ]
    new_job = make_job(
        "p2", "a", "attention", 20, attention_type="permission_request"
    )

    result = schedule_job(queued, new_job, 8, 0)

    assert [job["message_id"] for job in result] == ["f1", "i1", "p2"]


def test_commentary_does_not_remove_attention():
    queued = [
        make_job("a1", "a", "attention", 10, attention_type="input_required"),
        make_job("c1", "a", "commentary", 11),
    ]

    result = schedule_job(queued, make_job("c2", "a", "commentary", 20), 8, 0)

    assert [job["message_id"] for job in result] == ["a1", "c2"]


def test_final_removes_all_same_session_attention():
    queued = [
        make_job("a1", "a", "attention", 10, attention_type="input_required"),
        make_job("a2", "b", "attention", 11, attention_type="input_required"),
    ]

    result = schedule_job(queued, make_job("f1", "a", "final", 20), 8, 0)

    assert [job["message_id"] for job in result] == ["a2", "f1"]


def test_overflow_drops_lowest_priority_oldest_job_first():
    queued = [
        make_job("f1", "a", "final", 10),
        make_job("c1", "b", "commentary", 20),
        make_job("a1", "c", "attention", 30, attention_type="input_required"),
    ]

    result = schedule_job(
        queued,
        make_job("a2", "d", "attention", 40, attention_type="permission_request"),
        3,
        0,
    )

    assert [job["message_id"] for job in result] == ["f1", "a1", "a2"]
