import threading
import time
from pathlib import Path

from jarvis_line import audio_worker
from jarvis_line.queue_policy import attention_cancellation_key


def test_format_command_parts_replaces_placeholders():
    output_path = Path("out.wav")
    parts = audio_worker.format_command_parts(
        ["tts", "--text", "{text_json}", "--out", "{output}"],
        "hello",
        output_path,
    )

    assert parts == ["tts", "--text", '"hello"', "--out", str(output_path)]


def test_save_json_unlocked_uses_recognizable_temporary_name(tmp_path, monkeypatch):
    path = tmp_path / "jarvis_line_audio_queue.json"
    real_named_temporary_file = audio_worker.tempfile.NamedTemporaryFile
    calls = []

    def record_temporary_file(*args, **kwargs):
        calls.append(kwargs)
        return real_named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(
        audio_worker.tempfile,
        "NamedTemporaryFile",
        record_temporary_file,
    )

    audio_worker.save_json_unlocked(path, {"jobs": []})

    assert calls == [
        {
            "encoding": "utf-8",
            "dir": path.parent,
            "prefix": ".jarvis_line_audio_queue.json.",
            "suffix": ".tmp",
            "delete": False,
        }
    ]


def test_try_file_lock_acquires_and_releases_fallback_lock(tmp_path, monkeypatch):
    lock_path = tmp_path / "runtime.lock"
    monkeypatch.setattr(audio_worker, "fcntl", None)
    monkeypatch.setattr(audio_worker, "msvcrt", None)

    with audio_worker.try_file_lock(lock_path) as acquired:
        assert acquired is True
        assert lock_path.with_name("runtime.lock.d").is_dir()

    assert not lock_path.with_name("runtime.lock.d").exists()


def test_try_file_lock_returns_immediately_when_fallback_lock_is_owned(tmp_path, monkeypatch):
    lock_path = tmp_path / "runtime.lock"
    lock_path.with_name("runtime.lock.d").mkdir()
    monkeypatch.setattr(audio_worker, "fcntl", None)
    monkeypatch.setattr(audio_worker, "msvcrt", None)

    with audio_worker.try_file_lock(lock_path) as acquired:
        assert acquired is False

    assert lock_path.with_name("runtime.lock.d").is_dir()


def test_try_file_lock_uses_windows_kernel_lock_without_directory(
    tmp_path, monkeypatch
):
    class FakeMSVCRT:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self):
            self.calls = []

        def locking(self, descriptor, mode, size):
            self.calls.append((descriptor, mode, size))

    lock_path = tmp_path / "runtime.lock"
    windows_lock = FakeMSVCRT()
    monkeypatch.setattr(audio_worker, "fcntl", None)
    monkeypatch.setattr(audio_worker, "msvcrt", windows_lock)

    with audio_worker.try_file_lock(lock_path) as acquired:
        assert acquired is True

    assert [call[1:] for call in windows_lock.calls] == [(1, 1), (2, 1)]
    assert lock_path.is_file()
    assert not lock_path.with_name("runtime.lock.d").exists()


def test_try_file_lock_reports_busy_windows_kernel_lock(tmp_path, monkeypatch):
    class BusyMSVCRT:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(_descriptor, mode, _size):
            if mode == BusyMSVCRT.LK_NBLCK:
                raise OSError("busy")

    lock_path = tmp_path / "runtime.lock"
    monkeypatch.setattr(audio_worker, "fcntl", None)
    monkeypatch.setattr(audio_worker, "msvcrt", BusyMSVCRT())

    with audio_worker.try_file_lock(lock_path) as acquired:
        assert acquired is False

    assert not lock_path.with_name("runtime.lock.d").exists()


def test_windows_file_lock_serializes_threads_before_kernel_polling(
    tmp_path, monkeypatch
):
    class ContendedMSVCRT:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self):
            self.guard = threading.Lock()
            self.held = False
            self.active_calls = 0
            self.max_active_calls = 0

        def locking(self, _descriptor, mode, _size):
            if mode == self.LK_UNLCK:
                with self.guard:
                    self.held = False
                return

            with self.guard:
                self.active_calls += 1
                self.max_active_calls = max(
                    self.max_active_calls,
                    self.active_calls,
                )
            time.sleep(0.01)
            with self.guard:
                busy = self.held
                if not busy:
                    self.held = True
                self.active_calls -= 1
            if busy:
                raise OSError("busy")

    lock_path = tmp_path / "runtime.lock"
    windows_lock = ContendedMSVCRT()
    monkeypatch.setattr(audio_worker, "fcntl", None)
    monkeypatch.setattr(audio_worker, "msvcrt", windows_lock)
    start = threading.Barrier(5)
    threads = []

    def worker():
        start.wait()
        with audio_worker.file_lock(lock_path):
            time.sleep(0.005)

    for _ in range(4):
        thread = threading.Thread(target=worker)
        threads.append(thread)
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert windows_lock.max_active_calls == 1


def test_try_file_lock_reports_same_process_contention_before_kernel(
    tmp_path, monkeypatch
):
    lock_path = tmp_path / "runtime.lock"
    kernel_attempts = []
    monkeypatch.setattr(audio_worker, "fcntl", None)
    monkeypatch.setattr(audio_worker, "msvcrt", object())
    monkeypatch.setattr(
        audio_worker,
        "_try_windows_file_lock",
        lambda _file: kernel_attempts.append(True) or True,
    )
    monkeypatch.setattr(audio_worker, "_release_windows_file_lock", lambda _file: None)

    with audio_worker.file_lock(lock_path):
        kernel_attempts.clear()
        with audio_worker.try_file_lock(lock_path) as acquired:
            assert acquired is False

    assert kernel_attempts == []


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


def test_dequeue_drops_expired_attention_before_playback(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_worker, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(audio_worker, "LOCK_PATH", tmp_path / "lock")
    now_ms = int(audio_worker.time.time() * 1000)
    audio_worker.save_json_unlocked(
        tmp_path / "queue.json",
        {
            "jobs": [
                {
                    "message_id": "expired",
                    "session_key": "a",
                    "phase": "attention",
                    "attention_type": "input_required",
                    "jarvis_line": "old input",
                    "enqueued_ts_ms": now_ms - 100,
                    "expires_ts_ms": now_ms,
                },
                {
                    "message_id": "final",
                    "session_key": "b",
                    "phase": "final",
                    "jarvis_line": "current final",
                    "enqueued_ts_ms": now_ms,
                },
            ]
        },
    )

    assert audio_worker.dequeue_audio_job()["message_id"] == "final"
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


def test_worker_skips_attention_cancelled_after_dequeue(monkeypatch):
    jobs = [
        {
            "message_id": "attention-1",
            "jarvis_line": "Your input is needed.",
            "phase": "attention",
            "attention_type": "input_required",
            "correlation_token": "token-1",
            "session_key": "codex:s1",
        },
        None,
    ]
    spoken = []
    events = []

    monkeypatch.setattr(
        audio_worker,
        "dequeue_audio_job",
        lambda: jobs.pop(0) if jobs else None,
    )
    monkeypatch.setattr(audio_worker, "attention_job_is_cancelled", lambda _job: True)
    monkeypatch.setattr(audio_worker, "speak_line", spoken.append)
    monkeypatch.setattr(audio_worker, "rss_limit_exceeded", lambda: (True, 700.0, 512.0))
    monkeypatch.setattr(audio_worker, "worker_idle_exit_seconds", lambda: 0.01)
    monkeypatch.setattr(audio_worker, "warm_tts_if_configured", lambda: None)
    monkeypatch.setattr(audio_worker, "update_worker_heartbeat", lambda: None)
    monkeypatch.setattr(audio_worker, "append_log", lambda _line: None)
    monkeypatch.setattr(
        audio_worker.diagnostics,
        "record_event",
        lambda event, **metadata: events.append((event, metadata)),
    )

    assert audio_worker.run_worker() == 0
    assert spoken == []
    assert "cancelled" in [event for event, _metadata in events]


def test_attention_job_is_cancelled_reads_private_tombstone(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(audio_worker, "QUEUE_PATH", queue_path)
    monkeypatch.setattr(audio_worker, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(audio_worker.time, "time", lambda: 100.0)
    key = attention_cancellation_key("codex:s1", "input_required", "token-1")
    audio_worker.save_json_unlocked(
        queue_path,
        {"jobs": [], "attention_cancellations": {key: 100_000}},
    )

    assert audio_worker.attention_job_is_cancelled(
        {
            "phase": "attention",
            "session_key": "codex:s1",
            "attention_type": "input_required",
            "correlation_token": "token-1",
        }
    ) is True


def test_speak_line_rechecks_cancellation_after_kokoro_setup(tmp_path, monkeypatch):
    config = {
        "tts": "kokoro",
        "voice": "test-voice",
        "playback_mode": "stream",
        "volume": 0.7,
        "lang": "en-gb",
        "speed": 1.0,
    }
    checks = []
    prepared = []
    played = []

    monkeypatch.setattr(audio_worker, "AUDIO_LOCK_PATH", tmp_path / "audio.lock")
    monkeypatch.setattr(audio_worker.ks, "load_config", lambda: config)
    monkeypatch.setattr(
        audio_worker,
        "ensure_speaker",
        lambda: prepared.append(True)
        or {
            "config": config,
            "engine": object(),
            "voice_cache": {"test-voice": object()},
        },
    )
    monkeypatch.setattr(
        audio_worker.ks,
        "play_stream",
        lambda *_args, **_kwargs: played.append(True),
    )
    monkeypatch.setattr(audio_worker, "append_log", lambda _line: None)

    def cancelled():
        checks.append(True)
        return len(checks) >= 2

    assert audio_worker.speak_line("Your input is needed.", cancelled) is False
    assert prepared == [True]
    assert played == []
    assert len(checks) == 2


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


def test_worker_trace_records_speaking_completion_and_memory_exit(monkeypatch):
    jobs = [
        {
            "message_id": "abc",
            "jarvis_line": "secret line",
            "phase": "final",
            "session_key": "/private/session.jsonl",
        },
        None,
    ]
    events = []

    monkeypatch.setattr(audio_worker, "dequeue_audio_job", lambda: jobs.pop(0))
    monkeypatch.setattr(audio_worker, "speak_line", lambda _line: None)
    monkeypatch.setattr(audio_worker, "rss_limit_exceeded", lambda: (True, 700.0, 512.0))
    monkeypatch.setattr(audio_worker, "warm_tts_if_configured", lambda: None)
    monkeypatch.setattr(audio_worker, "update_worker_heartbeat", lambda: None)
    monkeypatch.setattr(audio_worker, "append_log", lambda _line: None)
    monkeypatch.setattr(
        audio_worker.diagnostics,
        "record_event",
        lambda event, **metadata: events.append((event, metadata)),
    )

    assert audio_worker.run_worker() == 0

    assert [event for event, _metadata in events] == [
        "worker_started",
        "speaking",
        "completed",
        "worker_rss_exit",
    ]
    assert all("line" not in metadata for _event, metadata in events)
