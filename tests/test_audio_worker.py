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
