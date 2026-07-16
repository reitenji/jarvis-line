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
