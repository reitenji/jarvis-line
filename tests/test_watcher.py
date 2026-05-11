import types

from jarvis_line import watcher


def test_custom_prefix_and_trim(monkeypatch):
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {
            "line_prefixes": ["Jarvis line:", "Friday line:"],
            "max_spoken_chars": 12,
        },
    )

    assert watcher.extract_jarvis_line("Done\nFriday line: Hello from Friday") == "Hello from…"


def test_speak_mode_final_only(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speak_mode": "final_only"})

    assert watcher.speak_mode_allows("final_answer") is True
    assert watcher.speak_mode_allows("commentary") is False


def test_queue_replaces_latest_final(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speak_mode": "final_only"})
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: None)

    assert watcher.queue_jarvis_line("s1", "final_answer", "one", "one") is True
    assert watcher.queue_jarvis_line("s2", "final_answer", "two", "two") is True
    assert watcher.queue_jarvis_line("s1", "final_answer", "new one", "new one") is True

    queue = watcher.load_json(tmp_path / "queue.json", {})
    assert [job["jarvis_line"] for job in queue["jobs"]] == ["two", "new one"]


def test_find_audio_worker_pids_matches_packaged_worker(monkeypatch):
    monkeypatch.setattr(watcher, "CODEX_HOME", watcher.Path("/Users/me/.codex"))
    monkeypatch.setattr(watcher, "KOKORO_VENV", watcher.Path("/Users/me/.codex/tts/kokoro-venv"))
    monkeypatch.setattr(watcher, "process_lines", lambda: [
        "201 /usr/bin/python /Users/me/.codex/tts/kokoro-venv/lib/python3.11/site-packages/jarvis_line/audio_worker.py",
        "202 /usr/bin/python /Users/me/.gemini/hooks/jarvis_line_watcher.py --watch",
    ])

    assert watcher.find_audio_worker_pids() == [201]


def test_launch_audio_worker_kills_orphans_instead_of_adopting(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(watcher, "audio_worker_is_healthy", lambda state=None: False)
    monkeypatch.setattr(watcher, "find_audio_worker_pids", lambda: [301])
    killed = []
    monkeypatch.setattr(watcher, "terminate_pid", lambda pid: killed.append(pid))

    class Proc:
        pid = 302

    monkeypatch.setattr(watcher.subprocess, "Popen", lambda *args, **kwargs: Proc())

    watcher.launch_audio_worker()
    state = watcher.load_json(tmp_path / "state.json", {})

    assert killed == [301]
    assert state["__audio_worker__"]["pid"] == 302
