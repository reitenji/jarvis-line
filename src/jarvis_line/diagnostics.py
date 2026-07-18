from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


CODEX_HOME = Path.home() / ".codex"
TRACE_PATH = CODEX_HOME / "hooks" / "jarvis_line_trace.jsonl"
TRACE_LOCK_PATH = CODEX_HOME / "hooks" / ".jarvis_line_trace.lock"
TRACE_MAX_BYTES = 256 * 1024
TRACE_KEEP_BYTES = 128 * 1024
FORBIDDEN_METADATA = {"content", "line", "session_path", "session_key", "text"}


try:
    import fcntl
except Exception:
    fcntl = None


def session_id(session_key: object) -> str:
    value = str(session_key or "")
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def runtime_log_context(
    *,
    session_key: object = "",
    line: object = "",
    include_content: bool = False,
) -> str:
    parts = []
    hashed_session = session_id(session_key)
    if hashed_session:
        parts.append(f"session={hashed_session}")
    if include_content:
        normalized_line = " ".join(str(line or "").split())[:512]
        if normalized_line:
            parts.append(f"line={normalized_line}")
    return " ".join(parts)


@contextmanager
def trace_lock() -> Iterator[None]:
    TRACE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is not None:
        with TRACE_LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return

    lock_dir = TRACE_LOCK_PATH.with_name(TRACE_LOCK_PATH.name + ".d")
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - lock_dir.stat().st_mtime > 30:
                    lock_dir.rmdir()
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def _safe_value(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:256]


def _trim_trace_unlocked() -> None:
    import tempfile

    if not TRACE_PATH.exists() or TRACE_PATH.stat().st_size < TRACE_MAX_BYTES:
        return
    with TRACE_PATH.open("rb") as trace_file:
        trace_file.seek(max(0, TRACE_PATH.stat().st_size - TRACE_KEEP_BYTES))
        data = trace_file.read()
    first_newline = data.find(b"\n")
    if first_newline >= 0:
        data = data[first_newline + 1 :]
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=TRACE_PATH.parent,
            prefix=f".{TRACE_PATH.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_file.write(data)
            tmp_name = tmp_file.name
        os.replace(tmp_name, TRACE_PATH)
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


def record_event(event: str, **metadata: object) -> None:
    name = str(event or "").strip().lower().replace("-", "_")[:64]
    if not name:
        return
    entry: dict[str, Any] = {
        "ts_ms": int(time.time() * 1000),
        "event": name,
    }
    if metadata.get("session_key"):
        entry["session_id"] = session_id(metadata.get("session_key"))
    for key, value in metadata.items():
        normalized_key = str(key or "").strip().lower()
        if not normalized_key or normalized_key in FORBIDDEN_METADATA:
            continue
        entry[normalized_key] = _safe_value(value)

    try:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entry, ensure_ascii=True, separators=(",", ":"))
        with trace_lock():
            _trim_trace_unlocked()
            file_descriptor = os.open(
                TRACE_PATH,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(file_descriptor, "a", encoding="utf-8") as trace_file:
                trace_file.write(payload + "\n")
            if os.name != "nt":
                os.chmod(TRACE_PATH, 0o600)
    except Exception:
        return


def read_events(limit: int = 20) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit or 20), 500))
    try:
        lines = TRACE_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-bounded_limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def clear_events() -> None:
    try:
        with trace_lock():
            TRACE_PATH.unlink(missing_ok=True)
    except OSError:
        return
