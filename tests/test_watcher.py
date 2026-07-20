import json
import types

import pytest

from jarvis_line import audio_worker, cleanup, watcher


def test_windows_watcher_lock_contends_with_audio_worker(tmp_path, monkeypatch):
    class SharedMSVCRT:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self):
            self.held = False

        def locking(self, _descriptor, mode, _size):
            if mode == self.LK_NBLCK:
                if self.held:
                    raise OSError("busy")
                self.held = True
            else:
                self.held = False

    lock_path = tmp_path / "runtime.lock"
    windows_lock = SharedMSVCRT()
    monkeypatch.setattr(watcher, "LOCK_PATH", lock_path)
    monkeypatch.setattr(watcher, "fcntl", None)
    monkeypatch.setattr(watcher, "msvcrt", windows_lock)
    monkeypatch.setattr(audio_worker, "fcntl", None)
    monkeypatch.setattr(audio_worker, "msvcrt", windows_lock)

    with watcher.file_lock():
        with audio_worker.try_file_lock(lock_path) as acquired:
            assert acquired is False


def test_save_json_unlocked_closes_descriptor_when_fdopen_fails(tmp_path, monkeypatch):
    real_open = watcher.os.open
    real_close = watcher.os.close
    opened = []
    closed = []

    def recording_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def recording_close(descriptor):
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(watcher.os, "open", recording_open)
    monkeypatch.setattr(watcher.os, "close", recording_close)
    monkeypatch.setattr(
        watcher.os,
        "fdopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fdopen failed")),
    )

    watcher.save_json_unlocked(tmp_path / "state.json", {"ok": True})

    leaked = [descriptor for descriptor in opened if descriptor not in closed]
    for descriptor in leaked:
        real_close(descriptor)
    assert leaked == []


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


def test_inline_jarvis_line_is_ignored(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})

    text = (
        "The README says: Jarvis line: "
        "export API_KEY=sk-testsecret-inline-leak"
    )

    assert watcher.extract_jarvis_line(text) is None


def test_speak_mode_final_only(monkeypatch):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"speak_mode": "final_only"})

    assert watcher.speak_mode_allows("final_answer") is True
    assert watcher.speak_mode_allows("commentary") is False
    assert watcher.speak_mode_allows("attention") is True


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


def test_process_line_queues_structured_plan_mode_input_without_options(monkeypatch):
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {
            "attention_enabled": True,
            "speak_mode": "final_only",
            "line_language": "English",
        },
    )
    queued = []
    monkeypatch.setattr(
        watcher,
        "queue_jarvis_line",
        lambda *args, **kwargs: queued.append((args, kwargs)) or True,
    )
    event = {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "request_user_input",
            "call_id": "call-private-1",
            "arguments": json.dumps(
                {
                    "questions": [
                        {
                            "header": "Release",
                            "id": "release",
                            "question": "Which release channel should be used?",
                            "options": [
                                {
                                    "label": "Secret beta",
                                    "description": "TOKEN=do-not-store",
                                }
                            ],
                        }
                    ]
                }
            ),
        },
    }

    watcher.process_line(json.dumps(event), "codex-session-1")

    assert len(queued) == 1
    args, kwargs = queued[0]
    assert args[:3] == (
        "codex-session-1",
        "attention",
        "Your input is needed: Release. Which release channel should be used?",
    )
    assert kwargs["attention_type"] == "input_required"
    assert len(kwargs["correlation_token"]) == 20
    assert "call-private-1" not in repr(queued)
    assert "Secret beta" not in repr(queued)
    assert "do-not-store" not in repr(queued)


def test_process_line_ignores_auto_resolving_plan_mode_input(monkeypatch):
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {
            "attention_enabled": True,
            "speak_mode": "final_only",
            "line_language": "English",
        },
    )
    queued = []
    monkeypatch.setattr(
        watcher,
        "queue_jarvis_line",
        lambda *args, **kwargs: queued.append((args, kwargs)) or True,
    )
    event = {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "request_user_input",
            "call_id": "call-optional-1",
            "arguments": json.dumps(
                {
                    "autoResolutionMs": 60_000,
                    "questions": [
                        {
                            "header": "Preference",
                            "question": "Which option do you prefer?",
                        }
                    ],
                }
            ),
        },
    }

    watcher.process_line(json.dumps(event), "codex-session-1")

    assert queued == []


def test_process_line_caches_effective_approval_reviewer(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")

    watcher.process_line(
        json.dumps(
            {
                "type": "turn_context",
                "payload": {"approvals_reviewer": "auto_review"},
            }
        ),
        "codex:session-1",
    )

    state = watcher.load_json(tmp_path / "state.json", {})
    assert state["__approval_contexts__"]["codex:session-1"][
        "approvals_reviewer"
    ] == "auto_review"


def test_cached_approval_reviewer_ignores_stale_context(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher.time, "time", lambda: 100_000.0)
    watcher.save_json(
        tmp_path / "state.json",
        {
            "__approval_contexts__": {
                "codex:session-1": {
                    "approvals_reviewer": "auto_review",
                    "updated_ts_ms": 1,
                }
            }
        },
    )

    assert watcher.cached_approval_reviewer("codex:session-1") is None


def test_process_line_replaces_malformed_approval_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    watcher.save_json(
        tmp_path / "state.json",
        {"__approval_contexts__": {"broken": "not-an-object"}},
    )

    watcher.process_line(
        json.dumps(
            {
                "type": "turn_context",
                "payload": {"approvals_reviewer": "user"},
            }
        ),
        "codex:session-1",
    )

    assert watcher.cached_approval_reviewer("codex:session-1") == "user"


def test_process_line_cancels_matching_plan_mode_input_result(monkeypatch):
    cancelled = []
    monkeypatch.setattr(
        watcher,
        "cancel_attention_job",
        lambda *args: cancelled.append(args) or True,
    )
    event = {
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": "call-private-1",
            "output": "Beta TOKEN=do-not-store",
        },
    }

    watcher.process_line(json.dumps(event), "codex-session-1")

    assert cancelled == [
        (
            "codex-session-1",
            "input_required",
            watcher.correlation_token("call-private-1"),
        )
    ]
    assert "do-not-store" not in repr(cancelled)


def test_process_line_ignores_malformed_plan_mode_input(monkeypatch):
    queued = []
    monkeypatch.setattr(
        watcher,
        "queue_jarvis_line",
        lambda *args, **kwargs: queued.append((args, kwargs)) or True,
    )

    watcher.process_line(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "request_user_input",
                    "call_id": "call-1",
                    "arguments": "not-json",
                },
            }
        ),
        "codex-session-1",
    )

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


@pytest.mark.parametrize("timestamp", [None, "not-a-timestamp"])
def test_recover_latest_recent_line_skips_missing_or_invalid_timestamp(tmp_path, monkeypatch, timestamp):
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"line_prefixes": ["Jarvis line:"]})
    queued = []
    monkeypatch.setattr(watcher, "queue_jarvis_line", lambda *args, **kwargs: queued.append(args) or True)
    session = tmp_path / "session.jsonl"
    event = {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "phase": "commentary",
            "content": [{"type": "output_text", "text": "Old.\nJarvis line: Old line."}],
        },
    }
    if timestamp is not None:
        event["timestamp"] = timestamp
    session.write_text(json.dumps(event) + "\n")

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


def test_session_key_for_path_matches_codex_hook_session_identity(tmp_path):
    session_id = "019e1590-7384-76a3-bb84-363d7045f9e5"
    path = tmp_path / f"rollout-2026-05-11T08-44-08-{session_id}.jsonl"

    assert watcher.session_key_for_path(path) == f"codex:{session_id}"


def test_session_key_for_path_falls_back_for_unknown_filename(tmp_path):
    path = tmp_path / "session.jsonl"

    assert watcher.session_key_for_path(path) == str(path.resolve())


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


def test_queue_trimming_preserves_finals_before_commentary(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {"speak_mode": "commentary_and_final", "max_queue_size": 2},
    )
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: None)

    assert watcher.queue_jarvis_line("s1", "final_answer", "final one") is True
    assert watcher.queue_jarvis_line("s2", "commentary", "working") is True
    assert watcher.queue_jarvis_line("s3", "final_answer", "final three") is True

    queue = watcher.load_json(tmp_path / "queue.json", {})
    assert [job["jarvis_line"] for job in queue["jobs"]] == ["final one", "final three"]


def test_attention_queue_requires_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {"speak_mode": "final_only", "attention_enabled": False},
    )
    launched = []
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: launched.append(True))

    assert watcher.queue_jarvis_line(
        "s1",
        "attention",
        "Permission is needed.",
        attention_type="permission_request",
    ) is False
    assert not (tmp_path / "queue.json").exists()
    assert launched == []


def test_attention_queue_respects_stopped_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    watcher.save_json(tmp_path / "state.json", {"__runtime__": {"stopped": True}})
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {"speak_mode": "final_only", "attention_enabled": True},
    )
    launched = []
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: launched.append(True))

    assert watcher.queue_jarvis_line(
        "s1",
        "attention",
        "Permission is needed.",
        attention_type="permission_request",
    ) is False
    assert not (tmp_path / "queue.json").exists()
    assert launched == []


def test_attention_queue_stores_only_bounded_metadata_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {"speak_mode": "final_only", "attention_enabled": True},
    )
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: None)
    monkeypatch.setattr(watcher.time, "time", lambda: 100.0)

    assert watcher.queue_jarvis_line(
        "codex:s1",
        "attention",
        "Permission is needed to push changes.",
        "Permission is needed to push changes.",
        attention_type="permission_request",
        correlation_token="0123456789abcdef0123",
    ) is True

    job = watcher.load_json(tmp_path / "queue.json", {})["jobs"][0]
    assert job["attention_type"] == "permission_request"
    assert job["correlation_token"] == "0123456789abcdef0123"
    assert job["expires_ts_ms"] == 130_000
    assert set(job) == {
        "message_id",
        "session_key",
        "phase",
        "attention_type",
        "correlation_token",
        "jarvis_line",
        "text",
        "enqueued_ts_ms",
        "expires_ts_ms",
    }


def test_cancel_attention_job_is_session_and_token_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    watcher.save_json(
        tmp_path / "queue.json",
        {
            "jobs": [
                {
                    "message_id": "a1",
                    "session_key": "codex:s1",
                    "phase": "attention",
                    "attention_type": "input_required",
                    "correlation_token": "token-1",
                },
                {
                    "message_id": "a2",
                    "session_key": "codex:s2",
                    "phase": "attention",
                    "attention_type": "input_required",
                    "correlation_token": "token-1",
                },
            ]
        },
    )

    assert watcher.cancel_attention_job(
        "codex:s1", "input_required", "token-1"
    ) is True

    jobs = watcher.load_json(tmp_path / "queue.json", {})["jobs"]
    assert [job["message_id"] for job in jobs] == ["a2"]


def test_cancel_attention_job_records_in_flight_tombstone(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    watcher.save_json(tmp_path / "queue.json", {"jobs": []})

    assert watcher.cancel_attention_job(
        "codex:s1", "input_required", "token-1"
    ) is True

    queue = watcher.load_json(tmp_path / "queue.json", {})
    assert len(queue["attention_cancellations"]) == 1
    assert "codex:s1" not in repr(queue["attention_cancellations"])
    assert "token-1" not in repr(queue["attention_cancellations"])


def test_cancel_attention_job_keeps_new_tombstone_at_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher.time, "time", lambda: 100.0)
    watcher.save_json(
        tmp_path / "queue.json",
        {
            "jobs": [],
            "attention_cancellations": {
                f"existing-{index}": 100_000
                for index in range(watcher.ATTENTION_CANCELLATION_MAX_ENTRIES)
            },
        },
    )

    assert watcher.cancel_attention_job(
        "codex:s1", "input_required", "token-1"
    ) is True

    cancellations = watcher.load_json(tmp_path / "queue.json", {})[
        "attention_cancellations"
    ]
    expected_key = watcher.attention_cancellation_key(
        "codex:s1", "input_required", "token-1"
    )
    assert len(cancellations) == watcher.ATTENTION_CANCELLATION_MAX_ENTRIES
    assert expected_key in cancellations


def test_queue_log_is_private_and_trace_records_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "AUDIO_QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(watcher, "LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(
        watcher,
        "runtime_config",
        lambda: {"speak_mode": "final_only", "debug_content_logging": False},
    )
    events = []
    lifecycle = []
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: lifecycle.append("launch"))
    monkeypatch.setattr(
        watcher.diagnostics,
        "record_event",
        lambda event, **metadata: (events.append((event, metadata)), lifecycle.append(event)),
    )

    assert watcher.queue_jarvis_line("/private/session.jsonl", "final", "secret line") is True

    log_text = (tmp_path / "watcher.log").read_text()
    assert "secret line" not in log_text
    assert "/private/session.jsonl" not in log_text
    assert events[-1][0] == "queued"
    assert events[-1][1]["phase"] == "final"
    assert "line" not in events[-1][1]
    assert lifecycle == ["queued", "launch"]


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
    monkeypatch.setattr(watcher, "LOCK_PATH", tmp_path / "lock")
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


def test_maybe_run_cleanup_uses_hourly_memory_gate(monkeypatch):
    calls = []
    config = {"cleanup_enabled": True, "cleanup_interval_hours": 24}
    monkeypatch.setattr(watcher, "runtime_config", lambda: config)
    monkeypatch.setattr(
        watcher.cleanup,
        "run_if_due",
        lambda cfg: calls.append(cfg) or None,
    )

    checked = watcher.maybe_run_cleanup(0.0, now_monotonic=100.0)
    checked = watcher.maybe_run_cleanup(checked, now_monotonic=200.0)
    checked = watcher.maybe_run_cleanup(checked, now_monotonic=3_701.0)

    assert calls == [config, config]
    assert checked == 3_701.0


def test_maybe_run_cleanup_logs_only_safe_run_totals(monkeypatch):
    report = cleanup.CleanupReport(mode="automatic", last_success_at=200_000)
    category = report.categories["generated_audio"]
    category.removed_files = 3
    category.removed_bytes = 48 * 1024 * 1024
    logs = []
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"cleanup_enabled": True})
    monkeypatch.setattr(watcher.cleanup, "run_if_due", lambda _cfg: report)
    monkeypatch.setattr(watcher, "append_log", logs.append)

    assert watcher.maybe_run_cleanup(0.0, now_monotonic=100.0) == 100.0
    assert logs == [
        "cleanup-run mode=automatic removed=3 "
        "reclaimed_bytes=50331648 error_count=0"
    ]


def test_maybe_run_cleanup_swallows_exception_without_message(monkeypatch):
    secret = "/Users/private/customer-session.jsonl"
    logs = []
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"cleanup_enabled": True})
    monkeypatch.setattr(
        watcher.cleanup,
        "run_if_due",
        lambda _cfg: (_ for _ in ()).throw(PermissionError(secret)),
    )
    monkeypatch.setattr(watcher, "append_log", logs.append)

    assert watcher.maybe_run_cleanup(0.0, now_monotonic=100.0) == 100.0
    assert logs == ["cleanup-error type=PermissionError error_count=1"]
    assert secret not in logs[0]


def test_maybe_run_cleanup_does_not_log_already_running(monkeypatch):
    report = cleanup.CleanupReport(mode="automatic", already_running=True)
    logs = []
    monkeypatch.setattr(watcher, "runtime_config", lambda: {"cleanup_enabled": True})
    monkeypatch.setattr(watcher.cleanup, "run_if_due", lambda _cfg: report)
    monkeypatch.setattr(watcher, "append_log", logs.append)

    assert watcher.maybe_run_cleanup(0.0, now_monotonic=100.0) == 100.0
    assert logs == []


def test_watch_file_checks_cleanup_at_startup_and_in_loop(tmp_path, monkeypatch):
    session = tmp_path / "session.jsonl"
    session.write_text("")
    calls = []

    def stop_on_loop(last_check, now_monotonic=None):
        calls.append(last_check)
        if len(calls) == 2:
            raise RuntimeError("stop loop")
        return 123.0

    monkeypatch.setattr(watcher, "append_log", lambda _message: None)
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: 0)
    monkeypatch.setattr(watcher, "maybe_run_cleanup", stop_on_loop)

    with pytest.raises(RuntimeError, match="stop loop"):
        watcher.watch_file(session)

    assert calls == [0.0, 123.0]


def test_watch_sessions_checks_cleanup_at_startup_and_in_loop(monkeypatch):
    calls = []

    def stop_on_loop(last_check, now_monotonic=None):
        calls.append(last_check)
        if len(calls) == 2:
            raise RuntimeError("stop loop")
        return 123.0

    monkeypatch.setattr(watcher, "append_log", lambda _message: None)
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: 0)
    monkeypatch.setattr(watcher, "maybe_run_cleanup", stop_on_loop)

    with pytest.raises(RuntimeError, match="stop loop"):
        watcher.watch_sessions()

    assert calls == [0.0, 123.0]


def test_watch_sessions_uses_rolling_recovery_cutoff(tmp_path, monkeypatch):
    session = tmp_path / "session.jsonl"
    session.write_text("")
    times = iter([2_000.0, 2_601.0])
    recovery_cutoffs = []
    discovery_calls = 0

    monkeypatch.setattr(watcher, "append_log", lambda _message: None)
    monkeypatch.setattr(watcher, "launch_audio_worker", lambda: 0)
    monkeypatch.setattr(watcher, "maybe_run_cleanup", lambda last_check: last_check)

    def candidates():
        nonlocal discovery_calls
        discovery_calls += 1
        return [] if discovery_calls == 1 else [session]

    monkeypatch.setattr(watcher, "current_session_candidates", candidates)
    monkeypatch.setattr(watcher.time, "time", lambda: next(times))
    monkeypatch.setattr(watcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(watcher, "reap_child_processes", lambda: None)
    monkeypatch.setattr(watcher, "update_watcher_heartbeat", lambda: None)
    monkeypatch.setattr(watcher, "audio_queue_has_jobs", lambda: False)

    def record_cutoff(_path, _session_key, min_ts_ms):
        recovery_cutoffs.append(min_ts_ms)
        raise RuntimeError("stop after recovery")

    monkeypatch.setattr(watcher, "recover_latest_recent_line", record_cutoff)

    with pytest.raises(RuntimeError, match="stop after recovery"):
        watcher.watch_sessions()

    assert recovery_cutoffs == [2_301_000]
