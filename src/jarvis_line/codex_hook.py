from __future__ import annotations

import json
import sys
from typing import Any, Mapping, TextIO

from jarvis_line import diagnostics, events, kokoro_say
from jarvis_line.attention import format_permission_request
from jarvis_line.events import SpeechEvent


MAX_HOOK_INPUT_BYTES = 65_536


def load_config() -> dict[str, Any]:
    return kokoro_say.load_config()


def _record_skip(reason: str) -> None:
    diagnostics.record_event(
        "hook_skipped",
        source="codex",
        phase="attention",
        attention_type="permission_request",
        reason=reason,
    )


def _read_payload(stream: TextIO) -> Mapping[str, Any] | None:
    raw = stream.read(MAX_HOOK_INPUT_BYTES + 1)
    if not raw or len(raw.encode("utf-8", errors="ignore")) > MAX_HOOK_INPUT_BYTES:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def permission_request_main(stdin: TextIO | None = None) -> int:
    try:
        cfg = load_config()
        if not bool(cfg.get("attention_enabled", False)):
            _record_skip("attention_disabled")
            return 0
        if cfg.get("speech_enabled") is False:
            _record_skip("speech_disabled")
            return 0
        if str(cfg.get("speak_mode") or "final_only").strip().lower() == "off":
            _record_skip("speak_mode")
            return 0

        payload = _read_payload(stdin or sys.stdin)
        if payload is None:
            _record_skip("invalid_payload")
            return 0
        if payload.get("hook_event_name") != "PermissionRequest":
            _record_skip("unsupported_event")
            return 0

        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            _record_skip("missing_session")
            return 0
        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, Mapping):
            tool_input = {}
        message = format_permission_request(
            tool_name,
            tool_input,
            cfg.get("line_language", "English"),
        )
        event = SpeechEvent.from_mapping(
            {
                "version": 1,
                "source": "codex",
                "session_id": session_id,
                "phase": "attention",
                "attention_type": "permission_request",
                "line": message.line,
            }
        )
        events.emit_event(event)
    except Exception:
        _record_skip("adapter_error")
    return 0


if __name__ == "__main__":
    raise SystemExit(permission_request_main())
