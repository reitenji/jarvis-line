import argparse
import json

from jarvis_line import cli, diagnostics


def configure_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "TRACE_PATH", tmp_path / "trace.jsonl")
    monkeypatch.setattr(diagnostics, "TRACE_LOCK_PATH", tmp_path / "trace.lock")


def test_record_event_hashes_session_and_omits_spoken_text(tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)

    diagnostics.record_event(
        "queued",
        session_key="/private/session.jsonl",
        line="secret spoken content",
        text="secret transcript",
        message_id="abc",
    )

    event = diagnostics.read_events(1)[0]
    assert event["session_id"] != "/private/session.jsonl"
    assert len(event["session_id"]) == 12
    assert event["message_id"] == "abc"
    assert "line" not in event
    assert "text" not in event


def test_trace_rotation_preserves_newest_events(tmp_path, monkeypatch):
    configure_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(diagnostics, "TRACE_MAX_BYTES", 512)

    for index in range(40):
        diagnostics.record_event("queued", message_id=str(index), phase="commentary")

    events = diagnostics.read_events(3)
    assert [event["message_id"] for event in events] == ["37", "38", "39"]
    assert diagnostics.TRACE_PATH.stat().st_size <= 1024


def test_runtime_log_context_is_private_by_default():
    value = diagnostics.runtime_log_context(
        session_key="/private/session.jsonl",
        line="secret spoken content",
        include_content=False,
    )

    assert "/private/session.jsonl" not in value
    assert "secret spoken content" not in value
    assert "session=" in value


def test_runtime_log_context_can_include_content_for_debugging():
    value = diagnostics.runtime_log_context(
        session_key="session-a",
        line="safe test line",
        include_content=True,
    )

    assert "safe test line" in value
    assert "session-a" not in value


def test_trace_command_outputs_json_and_can_clear(tmp_path, monkeypatch, capsys):
    configure_paths(tmp_path, monkeypatch)
    diagnostics.record_event("completed", message_id="abc", duration_ms=25)

    args = argparse.Namespace(limit=20, json_output=True, clear=False)
    assert cli.trace_command(args) == 0
    assert json.loads(capsys.readouterr().out)[0]["event"] == "completed"

    assert cli.trace_command(argparse.Namespace(limit=20, json_output=False, clear=True)) == 0
    assert diagnostics.read_events(20) == []


def test_trace_parser_routes_to_trace_command():
    args = cli.build_parser().parse_args(["trace", "--limit", "12", "--json"])

    assert args.func is cli.trace_command
    assert args.limit == 12
    assert args.json_output is True
