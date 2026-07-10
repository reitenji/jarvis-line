from pathlib import Path

from jarvis_line import audio_worker


def test_format_command_parts_replaces_placeholders():
    output_path = Path("out.wav")
    parts = audio_worker.format_command_parts(
        ["tts", "--text", "{text_json}", "--out", "{output}"],
        "hello",
        output_path,
    )

    assert parts == ["tts", "--text", '"hello"', "--out", str(output_path)]


def test_dequeue_drops_stale_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_worker, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(audio_worker, "LOCK_PATH", tmp_path / "lock")
    now_ms = int(audio_worker.time.time() * 1000)
    audio_worker.save_json_unlocked(
        tmp_path / "queue.json",
        {
            "jobs": [
                {"jarvis_line": "old", "enqueued_ts_ms": now_ms - 999_999},
                {"jarvis_line": "new", "enqueued_ts_ms": now_ms},
            ]
        },
    )

    assert audio_worker.dequeue_audio_job()["jarvis_line"] == "new"
    assert audio_worker.dequeue_audio_job() is None


def test_dequeue_prefers_final_from_another_session(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_worker, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(audio_worker, "LOCK_PATH", tmp_path / "lock")
    now_ms = int(audio_worker.time.time() * 1000)
    audio_worker.save_json_unlocked(
        tmp_path / "queue.json",
        {
            "last_session_key": "a",
            "jobs": [
                {"message_id": "c1", "session_key": "a", "phase": "commentary", "jarvis_line": "commentary", "enqueued_ts_ms": now_ms},
                {"message_id": "f1", "session_key": "a", "phase": "final", "jarvis_line": "final a", "enqueued_ts_ms": now_ms + 1},
                {"message_id": "f2", "session_key": "b", "phase": "final", "jarvis_line": "final b", "enqueued_ts_ms": now_ms + 2},
            ],
        },
    )

    assert audio_worker.dequeue_audio_job()["message_id"] == "f2"
    queue = audio_worker.load_json(tmp_path / "queue.json", {})
    assert queue["last_session_key"] == "b"


def test_worker_idle_exit_seconds_uses_config():
    assert audio_worker.worker_idle_exit_seconds({"audio_worker_idle_exit_seconds": 12}) == 12
    assert audio_worker.worker_idle_exit_seconds({"audio_worker_idle_exit_seconds": 0}) == 0


def test_rss_limit_exceeded(monkeypatch):
    monkeypatch.setattr(audio_worker, "current_rss_mb", lambda: 900)

    exceeded, rss_mb, limit_mb = audio_worker.rss_limit_exceeded({"audio_worker_max_rss_mb": 768})

    assert exceeded is True
    assert rss_mb == 900
    assert limit_mb == 768


def test_worker_drains_pending_jobs_before_rss_exit(monkeypatch):
    jobs = [
        {"jarvis_line": "one", "phase": "commentary", "session_key": "a"},
        {"jarvis_line": "two", "phase": "final", "session_key": "b"},
        None,
    ]
    spoken = []
    logs = []

    monkeypatch.setattr(audio_worker, "dequeue_audio_job", lambda: jobs.pop(0))
    monkeypatch.setattr(audio_worker, "speak_line", spoken.append)
    monkeypatch.setattr(audio_worker, "rss_limit_exceeded", lambda: (True, 700.0, 512.0))
    monkeypatch.setattr(audio_worker, "warm_tts_if_configured", lambda: None)
    monkeypatch.setattr(audio_worker, "update_worker_heartbeat", lambda: None)
    monkeypatch.setattr(audio_worker, "append_log", logs.append)

    assert audio_worker.run_worker() == 0
    assert spoken == ["one", "two"]
    assert any("worker-rss-drained-exit" in line for line in logs)
