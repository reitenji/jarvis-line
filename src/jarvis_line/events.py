from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from jarvis_line import diagnostics, watcher
from jarvis_line.attention import ATTENTION_TYPES


EVENT_VERSION = 1
MAX_IDENTIFIER_CHARS = 128
MAX_LINE_CHARS = 4096
MAX_TEXT_CHARS = 16384
PHASE_ALIASES = {
    "commentary": "commentary",
    "commentary_only": "commentary",
    "progress": "commentary",
    "status": "commentary",
    "final": "final",
    "final_answer": "final",
    "final-response": "final",
    "final_response": "final",
    "attention": "attention",
}


def _identifier(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > MAX_IDENTIFIER_CHARS:
        raise ValueError(f"{name} must be at most {MAX_IDENTIFIER_CHARS} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{name} contains control characters")
    return text


def _source(value: object) -> str:
    source = _identifier(value, "source").lower()
    source = re.sub(r"[^a-z0-9._-]+", "-", source).strip("-")
    if not source:
        raise ValueError("source must contain a letter or number")
    if source.startswith("__"):
        raise ValueError("source must not start with '__'")
    return source


def _phase(value: object) -> str:
    phase = _identifier(value, "phase").lower().replace(" ", "_")
    normalized = PHASE_ALIASES.get(phase)
    if not normalized:
        raise ValueError("phase must be commentary, final, or attention")
    return normalized


def _attention_type(value: object, phase: str) -> str | None:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if phase != "attention":
        if raw:
            raise ValueError("attention_type is only valid for attention events")
        return None
    if raw not in ATTENTION_TYPES:
        allowed = ", ".join(sorted(ATTENTION_TYPES))
        raise ValueError(f"attention_type must be one of: {allowed}")
    return raw


def _line(value: object) -> str:
    line = " ".join(str(value or "").split())
    if not line:
        raise ValueError("line is required")
    if len(line) > MAX_LINE_CHARS:
        raise ValueError(f"line must be at most {MAX_LINE_CHARS} characters")
    return line


@dataclass(frozen=True)
class SpeechEvent:
    version: int
    source: str
    session_id: str
    phase: str
    line: str
    text: str = ""
    attention_type: str | None = None

    @property
    def session_key(self) -> str:
        return f"{self.source}:{self.session_id}"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SpeechEvent":
        if not isinstance(value, Mapping):
            raise ValueError("event must be a JSON object")
        try:
            version = int(value.get("version", EVENT_VERSION))
        except (TypeError, ValueError) as exc:
            raise ValueError("version must be an integer") from exc
        if version != EVENT_VERSION:
            raise ValueError(f"unsupported event version: {version}")
        text = str(value.get("text") or "")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"text must be at most {MAX_TEXT_CHARS} characters")
        phase = _phase(value.get("phase"))
        return cls(
            version=version,
            source=_source(value.get("source")),
            session_id=_identifier(value.get("session_id"), "session_id"),
            phase=phase,
            line=_line(value.get("line")),
            text=text,
            attention_type=_attention_type(value.get("attention_type"), phase),
        )


def emit_event(event: SpeechEvent) -> bool:
    text = event.text or event.line
    diagnostics.record_event(
        "received",
        session_key=event.session_key,
        source=event.source,
        phase=event.phase,
        attention_type=event.attention_type,
    )
    if event.phase == "attention":
        text = event.line
        return watcher.queue_jarvis_line(
            event.session_key,
            event.phase,
            event.line,
            text,
            attention_type=event.attention_type,
        )
    watcher.remember_latest_message(
        event.session_key,
        event.phase,
        text,
        event.line,
    )
    return watcher.queue_jarvis_line(
        event.session_key,
        event.phase,
        event.line,
        text,
    )
