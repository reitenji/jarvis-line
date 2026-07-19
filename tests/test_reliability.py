from jarvis_line import reliability


FORBIDDEN_KEYS = {
    "command",
    "content",
    "environment",
    "line",
    "session_key",
    "session_path",
    "text",
}


def assert_private(value):
    if isinstance(value, dict):
        assert FORBIDDEN_KEYS.isdisjoint(value)
        for item in value.values():
            assert_private(item)
    elif isinstance(value, list):
        for item in value:
            assert_private(item)


def build_snapshot(**overrides):
    values = {
        "config": {
            "tts": "system",
            "speech_enabled": True,
            "audio_worker_idle_exit_seconds": 60,
            "audio_worker_max_rss_mb": 512,
            "max_queue_size": 8,
        },
        "state": {
            "__watcher__": {"pid": 11},
            "__audio_worker__": {"pid": 12},
        },
        "queue": {"jobs": []},
        "trace_events": [],
        "now_ms": 200_000,
        "pid_alive": lambda pid: pid in {11, 12},
        "process_rss_mb": lambda pid: 84.0,
        "tts_status": {"backend": "system", "ready": True, "reason": "ready"},
    }
    values.update(overrides)
    return reliability.build_snapshot(**values)


def test_snapshot_correlates_delivery_without_content():
    snapshot = build_snapshot(
        trace_events=[
            {
                "ts_ms": 100,
                "event": "queued",
                "message_id": "message-secret",
                "session_id": "abcdef012345",
                "session_path": "/private/session.jsonl",
                "phase": "final",
                "line": "secret spoken content",
            },
            {
                "ts_ms": 140,
                "event": "completed",
                "message_id": "message-secret",
                "session_id": "abcdef012345",
                "phase": "final",
                "duration_ms": 30,
            },
        ]
    )

    assert snapshot["version"] == 1
    assert snapshot["health"] == "healthy"
    assert snapshot["deliveries"][0] == {
        "message_id": reliability.correlation_id("message-secret"),
        "session_id": "abcdef012345",
        "phase": "final",
        "state": "completed",
        "received_ts_ms": 100,
        "updated_ts_ms": 140,
        "duration_ms": 30,
    }
    assert "secret spoken content" not in str(snapshot)
    assert "/private/session.jsonl" not in str(snapshot)
    assert "message-secret" not in str(snapshot)
    assert_private(snapshot)


def test_snapshot_requires_action_when_watcher_is_stopped():
    snapshot = build_snapshot(pid_alive=lambda pid: pid == 12)

    assert snapshot["health"] == "action_required"
    assert snapshot["runtime"]["watcher"]["state"] == "stopped"
    assert snapshot["recommendations"] == [
        {
            "id": "runtime-restart",
            "severity": "action_required",
            "title": "Restart voice runtime",
            "detail": "The watcher is not running.",
            "action": "restart-runtime",
        }
    ]


def test_snapshot_accepts_expected_idle_worker():
    snapshot = build_snapshot(pid_alive=lambda pid: pid == 11)

    assert snapshot["health"] == "healthy"
    assert snapshot["runtime"]["worker"]["state"] == "idle"
    assert snapshot["recommendations"] == []


def test_snapshot_requires_worker_restart_when_active_queue_is_waiting():
    snapshot = build_snapshot(
        pid_alive=lambda pid: pid == 11,
        queue={
            "jobs": [
                {
                    "message_id": "active",
                    "phase": "final",
                    "enqueued_ts_ms": 199_000,
                }
            ]
        },
    )

    assert snapshot["health"] == "action_required"
    assert snapshot["runtime"]["worker"]["state"] == "stopped"
    assert snapshot["recommendations"][0]["action"] == "restart-runtime"


def test_classify_queue_counts_expired_stale_and_phases():
    summary = reliability.classify_queue(
        [
            {
                "phase": "attention",
                "enqueued_ts_ms": 199_000,
                "expires_ts_ms": 200_000,
            },
            {"phase": "commentary", "enqueued_ts_ms": 100_000},
            {"phase": "final", "enqueued_ts_ms": 199_500},
        ],
        now_ms=200_000,
        stale_after_ms=90_000,
    )

    assert summary == {
        "total": 3,
        "active": 1,
        "expired": 1,
        "stale": 1,
        "oldest_age_ms": 100_000,
        "phase_counts": {"attention": 1, "commentary": 1, "final": 1},
        "max_size": 0,
    }


def test_snapshot_recommends_pruning_rejected_queue_jobs():
    snapshot = build_snapshot(
        queue={
            "jobs": [
                {
                    "message_id": "expired",
                    "phase": "attention",
                    "enqueued_ts_ms": 199_000,
                    "expires_ts_ms": 200_000,
                }
            ]
        }
    )

    assert snapshot["health"] == "degraded"
    assert snapshot["recommendations"] == [
        {
            "id": "expired-queue",
            "severity": "degraded",
            "title": "Remove expired queue entries",
            "detail": "1 expired or stale entry is waiting.",
            "action": "prune-expired",
        }
    ]


def test_snapshot_recommendations_use_allowlisted_actions():
    snapshot = build_snapshot(
        pid_alive=lambda _pid: False,
        queue={"jobs": [{"phase": "final", "enqueued_ts_ms": 1}]},
        tts_status={"backend": "command", "ready": False, "reason": "not_ready"},
    )

    actions = {
        item["action"]
        for item in snapshot["recommendations"]
        if item.get("action") is not None
    }
    assert actions <= reliability.ALLOWED_RECOVERY_ACTIONS
    assert snapshot["tts"] == {
        "backend": "command",
        "ready": False,
        "reason": "not_ready",
    }


def test_classify_queue_ignores_malformed_jobs():
    summary = reliability.classify_queue(
        [None, "bad", {"phase": "final", "enqueued_ts_ms": 10}],
        now_ms=20,
        stale_after_ms=90_000,
    )

    assert summary["total"] == 1
    assert summary["active"] == 1
    assert summary["phase_counts"] == {"final": 1}


def test_prune_expired_jobs_preserves_active_jobs():
    jobs = [
        {"message_id": "expired", "enqueued_ts_ms": 199_000, "expires_ts_ms": 200_000},
        {"message_id": "stale", "enqueued_ts_ms": 100_000},
        {"message_id": "active", "enqueued_ts_ms": 199_500},
    ]

    active, removed = reliability.prune_expired_jobs(
        jobs,
        now_ms=200_000,
        stale_after_ms=90_000,
    )

    assert [job["message_id"] for job in active] == ["active"]
    assert removed == 2


def test_prune_expired_jobs_preserves_unknown_queue_entries():
    active_job = {"message_id": "active", "enqueued_ts_ms": 199_500}

    active, removed = reliability.prune_expired_jobs(
        [
            "unexpected-entry",
            {"message_id": "expired", "enqueued_ts_ms": 199_000, "expires_ts_ms": 200_000},
            active_job,
        ],
        now_ms=200_000,
        stale_after_ms=90_000,
    )

    assert active == ["unexpected-entry", active_job]
    assert removed == 1


def test_correlate_deliveries_keeps_only_the_requested_limit():
    events = []
    for index in range(5):
        events.extend(
            [
                {
                    "ts_ms": index * 10,
                    "event": "queued",
                    "message_id": f"message-{index}",
                    "phase": "commentary",
                },
                {
                    "ts_ms": index * 10 + 1,
                    "event": "completed",
                    "message_id": f"message-{index}",
                    "phase": "commentary",
                },
            ]
        )

    deliveries = reliability.correlate_deliveries(events, limit=2)

    assert len(deliveries) == 2
    assert [item["message_id"] for item in deliveries] == [
        reliability.correlation_id("message-4"),
        reliability.correlation_id("message-3"),
    ]


def test_recent_failure_degrades_health_and_recommends_tts_test():
    snapshot = build_snapshot(
        trace_events=[
            {
                "ts_ms": 199_900,
                "event": "failed",
                "message_id": "failed-message",
                "phase": "final",
                "reason": "backend_error",
            }
        ]
    )

    assert snapshot["health"] == "degraded"
    assert snapshot["recommendations"] == [
        {
            "id": "recent-speech-failure",
            "severity": "degraded",
            "title": "Test the selected voice",
            "detail": "The most recent delivery failed.",
            "action": "test-tts",
        }
    ]


def test_snapshot_sanitizes_uncontrolled_metadata_values():
    snapshot = build_snapshot(
        trace_events=[
            {
                "ts_ms": 199_900,
                "event": "failed",
                "message_id": "message",
                "session_id": "not/a/hash",
                "phase": "final with secret",
                "backend": "command --api-key secret",
                "reason": "secret reason with spaces",
            }
        ],
        tts_status={
            "backend": "command --api-key secret",
            "ready": False,
            "reason": "/private/model/path",
        },
    )

    assert snapshot["deliveries"][0]["session_id"] == ""
    assert snapshot["deliveries"][0]["phase"] == "unknown"
    assert snapshot["deliveries"][0]["backend"] == "unknown"
    assert snapshot["deliveries"][0]["reason"] == "unknown"
    assert snapshot["tts"] == {
        "backend": "unknown",
        "ready": False,
        "reason": "unknown",
    }
    assert "secret" not in str(snapshot)
