import io
import json

from jarvis_line import codex_hook


def permission_payload(**overrides):
    payload = {
        "hook_event_name": "PermissionRequest",
        "session_id": "session-1",
        "permission_mode": "plan",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin develop"},
    }
    payload.update(overrides)
    return payload


def patch_runtime(monkeypatch, *, enabled=True):
    monkeypatch.setattr(
        codex_hook,
        "load_config",
        lambda: {
            "attention_enabled": enabled,
            "speech_enabled": True,
            "speak_mode": "final_only",
            "line_language": "English",
        },
    )
    monkeypatch.setattr(codex_hook.diagnostics, "record_event", lambda *_args, **_kwargs: None)


def test_permission_hook_emits_normalized_event_without_stdout(monkeypatch, capsys):
    patch_runtime(monkeypatch)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )

    assert codex_hook.permission_request_main(
        io.StringIO(json.dumps(permission_payload()))
    ) == 0

    assert len(accepted) == 1
    assert accepted[0].source == "codex"
    assert accepted[0].session_id == "session-1"
    assert accepted[0].phase == "attention"
    assert accepted[0].attention_type == "permission_request"
    assert accepted[0].line == "Permission is needed to push changes to the remote repository."
    assert capsys.readouterr().out == ""


def test_permission_hook_skips_auto_review_from_payload(monkeypatch, capsys):
    patch_runtime(monkeypatch)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )

    assert codex_hook.permission_request_main(
        io.StringIO(
            json.dumps(
                permission_payload(
                    approval_context={"approvals_reviewer": "auto_review"}
                )
            )
        )
    ) == 0

    assert accepted == []
    assert capsys.readouterr().out == ""


def test_permission_hook_skips_auto_review_from_latest_turn_context(
    tmp_path,
    monkeypatch,
    capsys,
):
    patch_runtime(monkeypatch)
    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / "2026" / "07" / "18"
    session_dir.mkdir(parents=True)
    session_path = (
        session_dir / "rollout-2026-07-18T00-00-00-session-transcript.jsonl"
    )
    session_path.write_text(
        json.dumps(
            {
                "type": "turn_context",
                "payload": {"approvals_reviewer": "auto_review"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_hook, "SESSIONS_ROOT", sessions_root, raising=False)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )

    assert codex_hook.permission_request_main(
        io.StringIO(
            json.dumps(permission_payload(session_id="session-transcript"))
        )
    ) == 0

    assert accepted == []
    assert capsys.readouterr().out == ""


def test_permission_hook_skips_auto_review_from_watcher_cache(
    tmp_path,
    monkeypatch,
):
    patch_runtime(monkeypatch)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "__approval_contexts__": {
                    "codex:session-1": {
                        "approvals_reviewer": "auto_review",
                        "updated_ts_ms": 100_000,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_hook.events.watcher, "STATE_PATH", state_path)
    monkeypatch.setattr(codex_hook.events.watcher.time, "time", lambda: 100.0)
    monkeypatch.setattr(codex_hook, "SESSIONS_ROOT", tmp_path / "missing", raising=False)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )

    assert codex_hook.permission_request_main(
        io.StringIO(json.dumps(permission_payload()))
    ) == 0

    assert accepted == []


def test_permission_hook_keeps_user_reviewed_request(monkeypatch):
    patch_runtime(monkeypatch)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )

    assert codex_hook.permission_request_main(
        io.StringIO(
            json.dumps(
                permission_payload(
                    approval_context={"approvals_reviewer": "user"}
                )
            )
        )
    ) == 0

    assert len(accepted) == 1
    assert accepted[0].attention_type == "permission_request"


def test_permission_hook_discards_raw_request_content(monkeypatch):
    patch_runtime(monkeypatch)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )
    payload = permission_payload(
        tool_input={
            "command": "curl https://api.example.com/private?token=top-secret",
            "description": "Bearer private-secret",
        }
    )

    assert codex_hook.permission_request_main(io.StringIO(json.dumps(payload))) == 0

    serialized = repr(accepted[0])
    assert "top-secret" not in serialized
    assert "private-secret" not in serialized
    assert "/private" not in serialized


def test_permission_hook_is_noop_when_attention_is_disabled(monkeypatch, capsys):
    patch_runtime(monkeypatch, enabled=False)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )

    assert codex_hook.permission_request_main(
        io.StringIO(json.dumps(permission_payload()))
    ) == 0

    assert accepted == []
    assert capsys.readouterr().out == ""


def test_permission_hook_is_fail_soft_for_invalid_or_oversized_input(monkeypatch, capsys):
    patch_runtime(monkeypatch)
    accepted = []
    monkeypatch.setattr(
        codex_hook.events,
        "emit_event",
        lambda event: accepted.append(event) or True,
    )

    assert codex_hook.permission_request_main(io.StringIO("not-json")) == 0
    assert codex_hook.permission_request_main(io.StringIO("x" * 65_537)) == 0
    assert codex_hook.permission_request_main(
        io.StringIO(json.dumps(permission_payload(hook_event_name="PostToolUse")))
    ) == 0
    assert codex_hook.permission_request_main(
        io.StringIO(json.dumps(permission_payload(session_id="")))
    ) == 0

    assert accepted == []
    assert capsys.readouterr().out == ""


def test_permission_hook_contains_formatter_failure(monkeypatch, capsys):
    patch_runtime(monkeypatch)
    monkeypatch.setattr(
        codex_hook,
        "format_permission_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private failure")),
    )

    assert codex_hook.permission_request_main(
        io.StringIO(json.dumps(permission_payload()))
    ) == 0
    assert capsys.readouterr().out == ""
