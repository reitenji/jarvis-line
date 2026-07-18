from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, TextIO

from jarvis_line import diagnostics, events, kokoro_say
from jarvis_line.attention import format_permission_request
from jarvis_line.events import SpeechEvent


MAX_HOOK_INPUT_BYTES = 65_536
MAX_APPROVAL_CONTEXT_BYTES = 2 * 1024 * 1024
SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
AUTO_REVIEWERS = frozenset({"auto_review", "guardian_subagent"})
KNOWN_REVIEWERS = AUTO_REVIEWERS | {"user"}
SAFE_SESSION_ID_RE = re.compile(r"[A-Za-z0-9-]{1,128}")


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


def _normalize_reviewer(value: object) -> str | None:
    reviewer = str(value or "").strip().lower()
    return reviewer if reviewer in KNOWN_REVIEWERS else None


def _payload_reviewer(payload: Mapping[str, Any]) -> str | None:
    approval_context = payload.get("approval_context")
    if isinstance(approval_context, Mapping):
        reviewer = _normalize_reviewer(
            approval_context.get("approvals_reviewer")
            or approval_context.get("approvalsReviewer")
        )
        if reviewer:
            return reviewer
    return _normalize_reviewer(
        payload.get("approvals_reviewer") or payload.get("approvalsReviewer")
    )


def _transcript_reviewer(session_id: str) -> str | None:
    if not SAFE_SESSION_ID_RE.fullmatch(session_id) or not SESSIONS_ROOT.exists():
        return None
    try:
        candidates = list(SESSIONS_ROOT.rglob(f"*{session_id}*.jsonl"))
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for path in candidates[:2]:
        for raw_line in reversed(
            events.watcher.read_recent_lines(path, max_bytes=MAX_APPROVAL_CONTEXT_BYTES)
        ):
            try:
                event = json.loads(raw_line)
            except (TypeError, ValueError):
                continue
            if not isinstance(event, Mapping) or event.get("type") != "turn_context":
                continue
            turn_payload = event.get("payload")
            if not isinstance(turn_payload, Mapping):
                return None
            return _normalize_reviewer(turn_payload.get("approvals_reviewer"))
    return None


def effective_approvals_reviewer(
    payload: Mapping[str, Any],
    session_id: str,
) -> str | None:
    reviewer = _payload_reviewer(payload)
    if reviewer:
        return reviewer
    session_key = f"codex:{session_id}"
    try:
        reviewer = events.watcher.cached_approval_reviewer(session_key)
    except Exception:
        reviewer = None
    if reviewer:
        return reviewer
    reviewer = _transcript_reviewer(session_id)
    if reviewer:
        try:
            events.watcher.remember_approval_reviewer(session_key, reviewer)
        except Exception:
            pass
    return reviewer


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
        if effective_approvals_reviewer(payload, session_id) in AUTO_REVIEWERS:
            _record_skip("automatic_reviewer")
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
