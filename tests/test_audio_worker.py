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


def test_worker_idle_exit_seconds_uses_config():
    assert audio_worker.worker_idle_exit_seconds({"audio_worker_idle_exit_seconds": 12}) == 12
    assert audio_worker.worker_idle_exit_seconds({"audio_worker_idle_exit_seconds": 0}) == 0


def test_rss_limit_exceeded(monkeypatch):
    monkeypatch.setattr(audio_worker, "current_rss_mb", lambda: 900)

    exceeded, rss_mb, limit_mb = audio_worker.rss_limit_exceeded({"audio_worker_max_rss_mb": 768})

    assert exceeded is True
    assert rss_mb == 900
    assert limit_mb == 768
