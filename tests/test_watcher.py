import json
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


def test_inline_jarvis_line_is_extracted(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})

    text = (
        "Projelerim ekranı arka planda oluşmuş. "
        "Jarvis line: The projects list screen exists, and I am generating the project detail view."
    )

    assert watcher.extract_jarvis_line(text) == "The projects list screen exists, and I am generating the project detail view."


def test_speak_mode_final_only(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speak_mode": "final_only"})

    assert watcher.speak_mode_allows("final_answer") is True
    assert watcher.speak_mode_allows("commentary") is False


def test_codex_history_user_payload_is_ignored(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})
    payload = {
        "type": "message",
        "role": "user",
        "content": [{
            "type": "input_text",
            "text": (
                "The following is the Codex agent history added since your last approval assessment.\n\n"
                "Done.\n\n"
                "Jarvis line: Audio is working again.\n\n"
                "::git-stage{cwd=\"/tmp/repo\"}"
            ),
        }],
    }

    extracted = watcher.assistant_payload_from_event({"type": "response_item", "payload": payload})

    assert extracted == payload


def test_task_complete_last_agent_message_is_final(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})

    extracted = watcher.assistant_payload_from_event({
        "type": "event_msg",
        "payload": {
            "type": "task_complete",
            "last_agent_message": "Done.\n\nJarvis line: Task complete is ready.",
        },
    })

    assert extracted is not None
    assert extracted["role"] == "assistant"
    assert extracted["phase"] == "final_answer"
    assert watcher.extract_jarvis_line(extracted["content"]) == "Task complete is ready."


def test_regular_user_payload_with_jarvis_line_is_ignored(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})
    payload = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "Jarvis line: do not speak user prompts"}],
    }

    assert watcher.assistant_payload_from_event({"type": "response_item", "payload": payload}) == payload


def test_assistant_message_without_prefix_derives_spoken_line(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LATEST_MESSAGES_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {
            "speak_without_prefix": True,
            "speak_mode": "commentary_and_final",
            "max_spoken_chars": 120,
        },
    )
    queued = []
    monkeypatch.setattr(
        watcher,
        "queue_jarvis_line",
        lambda session_key, phase, line, text="": queued.append((session_key, phase, line)) or True,
    )
    raw_line = json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "phase": "final_answer",
            "content": [{"type": "output_text", "text": "Implemented the watcher fix and verified it.\n\nSkills used: 1"}],
        },
    })

    watcher.process_line(raw_line, "session-1")

    assert queued == [("session-1", "final_answer", "Implemented the watcher fix and verified it.")]


def test_assistant_message_without_prefix_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LATEST_MESSAGES_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speak_without_prefix": False})
    queued = []
    monkeypatch.setattr(watcher, "queue_jarvis_line", lambda *args, **kwargs: queued.append(args) or True)

    watcher.process_line(json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "phase": "final_answer",
            "content": "Implemented the watcher fix and verified it.",
        },
    }), "session-1")

    assert queued == []


def test_notify_payload_can_carry_final_jarvis_line(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})
    payload = watcher.assistant_payload_from_notify_event({
        "last_agent_message": "Done.\n\nJarvis line: Notify payload is ready.",
    })

    assert payload is not None
    assert payload["phase"] == "final_answer"
    assert watcher.extract_jarvis_line(payload["content"]) == "Notify payload is ready."


def test_process_line_ignores_codex_history_final_in_notify_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LATEST_MESSAGES_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {
            "line_prefixes": ["Jarvis line:"],
            "speak_mode": "commentary_and_final",
            "final_trigger_mode": "notify",
        },
    )
    queued = []
    monkeypatch.setattr(
        watcher,
        "queue_jarvis_line",
        lambda session_key, phase, line, text="": queued.append((session_key, phase, line)) or True,
    )
    raw_line = json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": (
                    "The following is the Codex agent history added since your last approval assessment.\n"
                    "Done.\n\n"
                    "Jarvis line: Direct watcher final."
                ),
            }],
        },
    })

    watcher.process_line(raw_line, "session-1")

    assert queued == []


def test_recover_latest_recent_line_speaks_newly_discovered_session(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LATEST_MESSAGES_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {
            "line_prefixes": ["Jarvis line:"],
            "speak_mode": "commentary_and_final",
        },
    )
    queued = []
    monkeypatch.setattr(
        watcher,
        "queue_jarvis_line",
        lambda session_key, phase, line, text="": queued.append((session_key, phase, line)) or True,
    )
    session = tmp_path / "session.jsonl"
    session.write_text("\n".join([
        json.dumps({
            "timestamp": "2026-06-09T09:00:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "Old.\nJarvis line: Old line."}],
            },
        }),
        json.dumps({
            "timestamp": "2026-06-09T09:14:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "Fresh.\nJarvis line: Fresh line."}],
            },
        }),
    ]) + "\n")

    recovered = watcher.recover_latest_recent_line(session, "session-1", 1780996200000)

    assert recovered is True
    assert queued == [("session-1", "commentary", "Fresh line.")]


def test_recover_latest_recent_line_skips_old_session_line(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})
    queued = []
    monkeypatch.setattr(watcher, "queue_jarvis_line", lambda *args, **kwargs: queued.append(args) or True)
    session = tmp_path / "session.jsonl"
    session.write_text(json.dumps({
        "timestamp": "2026-06-09T09:00:00.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "phase": "commentary",
            "content": [{"type": "output_text", "text": "Old.\nJarvis line: Old line."}],
        },
    }) + "\n")

    recovered = watcher.recover_latest_recent_line(session, "session-1", 1780996200000)

    assert recovered is False
    assert queued == []


def test_current_session_candidates_prefers_active_thread_id(tmp_path, monkeypatch):
    sessions_root = tmp_path / "sessions"
    active = sessions_root / "2026" / "05" / "11" / "rollout-2026-05-11T08-44-08-019e1590-7384-76a3-bb84-363d7045f9e5.jsonl"
    unrelated = sessions_root / "2026" / "05" / "13" / "rollout-2026-05-13T09-06-17-019e1ff1-706b-7093-b80a-415e103e027f.jsonl"
    active.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    active.write_text("{}\n")
    unrelated.write_text("{}\n")
    monkeypatch.setattr(watcher, "SESSIONS_ROOT", sessions_root)
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setenv("CODEX_THREAD_ID", "019e1590-7384-76a3-bb84-363d7045f9e5")
    monkeypatch.setattr(watcher.time, "time", lambda: 200.0)

    candidates = watcher.current_session_candidates()

    assert candidates[0] == active
    assert unrelated in candidates


def test_should_speak_preserves_runtime_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {})
    watcher.save_json(tmp_path / "state.json", {
        "__runtime__": {
            "stopped": False,
            "active_thread_ids": {"thread-a": 123},
        }
    })

    assert watcher.should_speak("session-1", "final_answer", "new line") is True

    state = watcher.load_json(tmp_path / "state.json", {})
    assert state["__runtime__"]["active_thread_ids"] == {"thread-a": 123}


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


def test_final_duplicate_stays_suppressed_after_dedupe_window(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"dedupe_window_seconds": 2})
    clock = [100.0]
    monkeypatch.setattr(watcher.time, "time", lambda: clock[0])

    assert watcher.should_speak("s1", "final_answer", "same line") is True
    assert watcher.should_speak("s1", "final_answer", "same line") is False

    clock[0] = 103.0
    assert watcher.should_speak("s1", "final_answer", "same line") is False


def test_find_audio_worker_pids_matches_packaged_worker(monkeypatch):
    monkeypatch.setattr(watcher, "CODEX_HOME", watcher.Path("/Users/me/.codex"))
    monkeypatch.setattr(watcher, "KOKORO_VENV", watcher.Path("/Users/me/.jarvis-line/tts/kokoro-venv"))
    monkeypatch.setattr(watcher, "PACKAGE_DIR", watcher.Path("/Users/me/projects/jarvis-line/src/jarvis_line"))
    monkeypatch.setattr(watcher, "process_lines", lambda: [
        "201 /usr/bin/python /Users/me/.jarvis-line/tts/kokoro-venv/lib/python3.11/site-packages/jarvis_line/audio_worker.py",
        "202 /usr/bin/python /Users/me/projects/jarvis-line/src/jarvis_line/audio_worker.py",
        "203 /usr/bin/python /tmp/not-ours/jarvis_line/audio_worker.py",
        "202 /usr/bin/python /Users/me/.gemini/hooks/jarvis_line_watcher.py --watch",
    ])

    assert watcher.find_audio_worker_pids() == [201, 202]


def test_pid_alive_rejects_zombie_process(monkeypatch):
    monkeypatch.setattr(watcher.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(watcher.os, "name", "posix")
    monkeypatch.setattr(watcher.subprocess, "check_output", lambda *args, **kwargs: "Z+")

    assert watcher.pid_alive(123) is False


def test_audio_worker_health_rejects_zombie_process(monkeypatch):
    monkeypatch.setattr(watcher.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(watcher.os, "name", "posix")
    monkeypatch.setattr(watcher.subprocess, "check_output", lambda *args, **kwargs: "Z")

    state = {"__audio_worker__": {"pid": 123, "heartbeat_ts_ms": int(watcher.time.time() * 1000)}}

    assert watcher.audio_worker_is_healthy(state) is False


def test_audio_queue_has_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    watcher.save_json(tmp_path / "queue.json", {"jobs": [{"jarvis_line": "pending"}]})

    assert watcher.audio_queue_has_jobs() is True


def test_notify_does_not_launch_when_runtime_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    watcher.save_json(tmp_path / "state.json", {"__runtime__": {"stopped": True}})
    launched = []
    monkeypatch.setattr(watcher, "launch_watcher", lambda: launched.append(True))

    rc = watcher.notify_trigger('{"type":"agent-turn-complete"}')

    assert rc == 0
    assert launched == []
    assert "notify-skip runtime-stopped" in (tmp_path / "watcher.log").read_text()


def test_notify_does_not_launch_when_speech_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speech_enabled": False})
    launched = []
    monkeypatch.setattr(watcher, "launch_watcher", lambda: launched.append(True))

    rc = watcher.notify_trigger('{"type":"agent-turn-complete"}')

    assert rc == 0
    assert launched == []
    assert "notify-skip speech-disabled" in (tmp_path / "watcher.log").read_text()


def test_notify_without_final_payload_uses_only_recent_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speech_enabled": True})
    monkeypatch.setattr(watcher, "watcher_is_healthy", lambda state=None: True)
    monkeypatch.setattr(watcher, "session_file_from_notify_event", lambda event: (_ for _ in ()).throw(AssertionError("session lookup should not run")))
    calls = []
    monkeypatch.setattr(watcher, "speak_latest_final_from_cache", lambda session_key=None, min_updated_ts_ms=0: calls.append(min_updated_ts_ms) or "missing")
    monkeypatch.setattr(watcher, "speak_latest_final_from_session", lambda path: (_ for _ in ()).throw(AssertionError("session replay should not run")))
    now = [100.0]
    monkeypatch.setattr(watcher.time, "time", lambda: now.__setitem__(0, now[0] + 0.2) or now[0])

    rc = watcher.notify_trigger('{"type":"agent-turn-complete"}')

    assert rc == 0
    assert calls
    assert all(value >= 70000 for value in calls)
    assert "notify-skip no-recent-final-payload" in (tmp_path / "watcher.log").read_text()


def test_notify_without_final_payload_speaks_recent_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(watcher, "LATEST_MESSAGES_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speech_enabled": True})
    monkeypatch.setattr(watcher, "watcher_is_healthy", lambda state=None: True)
    monkeypatch.setattr(watcher.time, "time", lambda: 100.0)
    watcher.save_json(tmp_path / "latest.json", {
        "active_session_key": "s1",
        "sessions": {
            "s1": {
                "latest_final": {
                    "session_key": "s1",
                    "phase": "final_answer",
                    "text": "done\nJarvis line: Recent cache only.",
                    "jarvis_line": "Recent cache only.",
                    "updated_ts_ms": 100000,
                }
            }
        },
    })
    queued = []
    monkeypatch.setattr(watcher, "queue_jarvis_line", lambda session_key, phase, line, text="": queued.append((session_key, phase, line)) or True)

    rc = watcher.notify_trigger('{"type":"agent-turn-complete"}')

    assert rc == 0
    assert queued == [("s1", "final_answer", "Recent cache only.")]
    assert "notify-cache-spoken" in (tmp_path / "watcher.log").read_text()


def test_notify_with_final_payload_queues_only_that_payload(tmp_path, monkeypatch):
    session = tmp_path / "session.jsonl"
    session.write_text("")
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(watcher, "LATEST_MESSAGES_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speech_enabled": True})
    monkeypatch.setattr(watcher, "watcher_is_healthy", lambda state=None: True)
    monkeypatch.setattr(watcher, "session_file_from_notify_event", lambda event: session)
    queued = []
    monkeypatch.setattr(watcher, "queue_jarvis_line", lambda session_key, phase, line, text="": queued.append((session_key, phase, line)) or True)
    monkeypatch.setattr(watcher, "speak_latest_final_from_cache", lambda session_key=None, min_updated_ts_ms=0: (_ for _ in ()).throw(AssertionError("cache replay should not run")))
    monkeypatch.setattr(watcher, "speak_latest_final_from_session", lambda path: (_ for _ in ()).throw(AssertionError("session replay should not run")))

    rc = watcher.notify_trigger(
        '{"type":"agent-turn-complete","last_agent_message":"done\\nJarvis line: Fresh payload only."}'
    )

    assert rc == 0
    assert queued == [(str(session.resolve()), "final_answer", "Fresh payload only.")]


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
