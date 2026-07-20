import argparse
import io
import json
import sys

import pytest

from jarvis_line import cli, events
from jarvis_line.events import SpeechEvent


def test_speech_event_normalizes_final_phase():
    event = SpeechEvent.from_mapping(
        {
            "version": 1,
            "source": "Claude",
            "session_id": "abc",
            "phase": "final_answer",
            "line": "Done.",
        }
    )

    assert event.source == "claude"
    assert event.phase == "final"
    assert event.session_key == "claude:abc"


def test_speech_event_accepts_attention_with_supported_type():
    event = SpeechEvent.from_mapping(
        {
            "version": 1,
            "source": "Claude",
            "session_id": "abc",
            "phase": "attention",
            "attention_type": "input_required",
            "line": "Your input is needed.",
        }
    )

    assert event.phase == "attention"
    assert event.attention_type == "input_required"


@pytest.mark.parametrize("attention_type", [None, "", "unknown"])
def test_speech_event_rejects_missing_or_unknown_attention_type(attention_type):
    with pytest.raises(ValueError, match="attention_type"):
        SpeechEvent.from_mapping(
            {
                "version": 1,
                "source": "custom",
                "session_id": "abc",
                "phase": "attention",
                "attention_type": attention_type,
                "line": "Attention.",
            }
        )


def test_speech_event_rejects_attention_type_on_regular_phase():
    with pytest.raises(ValueError, match="attention_type"):
        SpeechEvent.from_mapping(
            {
                "version": 1,
                "source": "custom",
                "session_id": "abc",
                "phase": "final",
                "attention_type": "input_required",
                "line": "Done.",
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "source": "custom", "session_id": "abc", "phase": "final", "line": "Done."},
        {"version": 1, "source": "", "session_id": "abc", "phase": "final", "line": "Done."},
        {"version": 1, "source": "custom", "session_id": "", "phase": "final", "line": "Done."},
        {"version": 1, "source": "custom", "session_id": "abc", "phase": "tool", "line": "Done."},
        {"version": 1, "source": "custom", "session_id": "abc", "phase": "final", "line": ""},
    ],
)
def test_speech_event_rejects_invalid_payload(payload):
    with pytest.raises(ValueError):
        SpeechEvent.from_mapping(payload)


def test_speech_event_rejects_control_characters():
    with pytest.raises(ValueError):
        SpeechEvent.from_mapping(
            {
                "version": 1,
                "source": "custom\ncommand",
                "session_id": "abc",
                "phase": "final",
                "line": "Done.",
            }
        )


def test_speech_event_rejects_internal_source_namespace():
    with pytest.raises(ValueError, match="must not start"):
        SpeechEvent.from_mapping(
            {
                "version": 1,
                "source": "__external_adapter",
                "session_id": "abc",
                "phase": "final",
                "line": "Done.",
            }
        )


def test_emit_event_queues_normalized_session_key(monkeypatch):
    remembered = []
    queued = []
    monkeypatch.setattr(
        events.watcher,
        "remember_latest_message",
        lambda session, phase, text, line: remembered.append((session, phase, text, line)),
    )
    monkeypatch.setattr(
        events.watcher,
        "queue_jarvis_line",
        lambda session, phase, line, text="": queued.append((session, phase, line, text)) or True,
    )
    monkeypatch.setattr(events.diagnostics, "record_event", lambda *_args, **_kwargs: None)
    event = SpeechEvent.from_mapping(
        {
            "version": 1,
            "source": "gemini",
            "session_id": "abc",
            "phase": "commentary",
            "line": "Working.",
            "text": "Longer optional context.",
        }
    )

    assert events.emit_event(event) is True
    assert remembered == [("gemini:abc", "commentary", "Longer optional context.", "Working.")]
    assert queued == [("gemini:abc", "commentary", "Working.", "Longer optional context.")]


def test_emit_attention_does_not_replace_cached_assistant_message(monkeypatch):
    remembered = []
    queued = []
    monkeypatch.setattr(
        events.watcher,
        "remember_latest_message",
        lambda *args: remembered.append(args),
    )
    monkeypatch.setattr(
        events.watcher,
        "queue_jarvis_line",
        lambda session, phase, line, text="", attention_type=None: queued.append(
            (session, phase, line, text, attention_type)
        )
        or True,
    )
    monkeypatch.setattr(events.diagnostics, "record_event", lambda *_args, **_kwargs: None)
    event = SpeechEvent.from_mapping(
        {
            "source": "codex",
            "session_id": "abc",
            "phase": "attention",
            "attention_type": "permission_request",
            "line": "Permission is required for Bash.",
            "text": "raw command with TOKEN=secret must be discarded",
        }
    )

    assert events.emit_event(event) is True
    assert remembered == []
    assert queued == [
        (
            "codex:abc",
            "attention",
            "Permission is required for Bash.",
            "Permission is required for Bash.",
            "permission_request",
        )
    ]


def test_emit_stdin_accepts_versioned_json(monkeypatch, capsys):
    payload = {
        "version": 1,
        "source": "custom",
        "session_id": "abc",
        "phase": "final",
        "line": "Done.",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    accepted = []
    monkeypatch.setattr(cli.events, "emit_event", lambda event: accepted.append(event) or True)

    assert cli.emit_command(
        argparse.Namespace(
            stdin=True,
            source=None,
            session=None,
            phase=None,
            line=None,
            text=None,
        )
    ) == 0

    assert accepted[0].session_key == "custom:abc"
    assert "queued" in capsys.readouterr().out.lower()


def test_emit_command_reports_invalid_input(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not-json"))

    assert cli.emit_command(argparse.Namespace(stdin=True)) == 2
    assert "invalid event" in capsys.readouterr().err.lower()


def test_emit_parser_supports_direct_arguments():
    args = cli.build_parser().parse_args(
        [
            "emit",
            "--source",
            "claude",
            "--session",
            "abc",
            "--phase",
            "commentary",
            "--line",
            "Working.",
        ]
    )

    assert args.func is cli.emit_command
    assert args.source == "claude"
    assert args.session == "abc"


def test_emit_parser_supports_attention_arguments():
    args = cli.build_parser().parse_args(
        [
            "emit",
            "--source",
            "claude",
            "--session",
            "abc",
            "--phase",
            "attention",
            "--attention-type",
            "input_required",
            "--line",
            "Your deployment choice is required.",
        ]
    )

    assert args.func is cli.emit_command
    assert args.phase == "attention"
    assert args.attention_type == "input_required"
