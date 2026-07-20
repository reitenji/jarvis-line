#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from jarvis_line import cleanup, diagnostics, kokoro_say as ks
from jarvis_line.attention import (
    ATTENTION_TYPES,
    correlation_token,
    format_input_required,
    parse_input_request_payload,
)
from jarvis_line.queue_policy import (
    attention_cancellation_key,
    is_attention_phase,
    prune_attention_cancellations,
    schedule_job,
)


CODEX_HOME = Path.home() / ".codex"
JARVIS_HOME = Path.home() / ".jarvis-line"
SESSIONS_ROOT = CODEX_HOME / "sessions"
STATE_PATH = CODEX_HOME / "hooks" / ".jarvis_line_state.json"
LATEST_MESSAGES_PATH = CODEX_HOME / "hooks" / "jarvis_line_latest_messages.json"
AUDIO_QUEUE_PATH = CODEX_HOME / "hooks" / "jarvis_line_audio_queue.json"
LOG_PATH = CODEX_HOME / "hooks" / "jarvis_line_watcher.log"
KOKORO_VENV = JARVIS_HOME / "tts" / "kokoro-venv"
KOKORO_PY = KOKORO_VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
WORKER_PATH = Path(__file__).resolve().with_name("audio_worker.py")
PACKAGE_DIR = Path(__file__).resolve().parent
LOCK_PATH = CODEX_HOME / "hooks" / ".jarvis_line.lock"
DEFAULT_LINE_PREFIXES = ["Jarvis line:"]
COMMENTARY_DEBOUNCE_SECONDS = 20
FINAL_DEBOUNCE_SECONDS = 2
SESSION_SCAN_WINDOW_SECONDS = 60 * 60 * 8
SESSION_DISCOVERY_INTERVAL_SECONDS = 2.0
RECENT_BYTES = 256 * 1024
NOTIFY_RETRY_SECONDS = 2.5
NOTIFY_POLL_SECONDS = 0.1
LOG_ROTATE_BYTES = 2 * 1024 * 1024
WATCHER_HEARTBEAT_SECONDS = 5.0
WATCHER_STALE_SECONDS = 30
AUDIO_WORKER_STALE_SECONDS = 120
AUDIO_QUEUE_STALE_SECONDS = 90
AUDIO_QUEUE_MAX_JOBS = 8
ATTENTION_TTL_SECONDS = 30
ATTENTION_CANCELLATION_MAX_ENTRIES = 64
SESSION_RECOVERY_WINDOW_SECONDS = 5 * 60
APPROVAL_CONTEXTS_MAX_ENTRIES = 64
CLEANUP_CHECK_GATE_SECONDS = 60 * 60
CODEX_SESSION_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


try:
    import fcntl
except Exception:
    fcntl = None

try:
    import msvcrt
except Exception:
    msvcrt = None


def _prepare_windows_lock_file(lock_file) -> None:
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
    lock_file.seek(0)


def _try_windows_file_lock(lock_file) -> bool:
    _prepare_windows_lock_file(lock_file)
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _release_windows_file_lock(lock_file) -> None:
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def is_final_phase(phase: str) -> bool:
    return phase in ("final", "final_answer")


def runtime_config() -> dict[str, Any]:
    try:
        return ks.load_config()
    except Exception:
        return {}


def line_prefixes(cfg: dict[str, Any] | None = None) -> list[str]:
    cfg = cfg if cfg is not None else runtime_config()
    prefixes = cfg.get("line_prefixes") or DEFAULT_LINE_PREFIXES
    if isinstance(prefixes, str):
        prefixes = [part.strip() for part in prefixes.split(",")]
    return [str(prefix).strip() for prefix in prefixes if str(prefix).strip()]


def speak_mode_allows(phase: str, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg if cfg is not None else runtime_config()
    mode = str(cfg.get("speak_mode") or "final_only").strip().lower()
    if mode in ("off", "silent", "disabled"):
        return False
    if is_attention_phase(phase):
        return True
    if mode in ("both", "commentary_and_final", "all"):
        return True
    if mode in ("commentary_only", "commentary"):
        return phase == "commentary"
    return is_final_phase(phase)


def trim_spoken_text(text: str, cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg if cfg is not None else runtime_config()
    max_chars = int(cfg.get("max_spoken_chars") or 240)
    text = " ".join(str(text or "").split())
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def quiet_hours_active(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg if cfg is not None else runtime_config()
    value = cfg.get("quiet_hours")
    if not value or not isinstance(value, str) or "-" not in value:
        return False
    start_text, end_text = [part.strip() for part in value.split("-", 1)]
    try:
        start_h, start_m = [int(part) for part in start_text.split(":", 1)]
        end_h, end_m = [int(part) for part in end_text.split(":", 1)]
    except Exception:
        return False
    now = datetime.now()
    now_min = now.hour * 60 + now.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start <= end:
        return start <= now_min < end
    return now_min >= start or now_min < end


def quiet_day_active(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg if cfg is not None else runtime_config()
    days = cfg.get("quiet_days") or []
    if isinstance(days, str):
        days = [part.strip() for part in days.split(",")]
    normalized = {str(day).strip().lower() for day in days if str(day).strip()}
    if not normalized:
        return False
    now = datetime.now()
    return now.strftime("%A").lower() in normalized or str(now.weekday()) in normalized


def append_log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rotate_log_if_needed()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{int(time.time())} {message}\n")
    except Exception:
        pass


def maybe_run_cleanup(
    last_check_monotonic: float,
    now_monotonic: float | None = None,
) -> float:
    current = time.monotonic() if now_monotonic is None else now_monotonic
    if (
        last_check_monotonic > 0
        and current - last_check_monotonic < CLEANUP_CHECK_GATE_SECONDS
    ):
        return last_check_monotonic
    try:
        report = cleanup.run_if_due(runtime_config())
    except Exception as error:
        append_log(
            f"cleanup-error type={error.__class__.__name__} error_count=1"
        )
        return current
    if report is not None and not report.already_running:
        append_log(
            "cleanup-run mode=automatic "
            f"removed={report.removed_files} "
            f"reclaimed_bytes={report.removed_bytes} "
            f"error_count={report.error_count}"
        )
    return current


def rotate_log_if_needed() -> None:
    try:
        if not LOG_PATH.exists() or LOG_PATH.stat().st_size < LOG_ROTATE_BYTES:
            return
        rotated = LOG_PATH.with_suffix(LOG_PATH.suffix + ".1")
        rotated.unlink(missing_ok=True)
        os.replace(LOG_PATH, rotated)
    except Exception:
        pass


@contextmanager
def file_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None and msvcrt is not None:
        with LOCK_PATH.open("a+b") as lock_file:
            while not _try_windows_file_lock(lock_file):
                time.sleep(0.05)
            try:
                yield
            finally:
                _release_windows_file_lock(lock_file)
        return
    if fcntl is None:
        lock_dir = LOCK_PATH.with_name(LOCK_PATH.name + ".d")
        while True:
            try:
                lock_dir.mkdir()
                break
            except FileExistsError:
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                lock_dir.rmdir()
            except OSError:
                pass
        return
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json_unlocked(path: Path, data) -> None:
    tmp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    descriptor: int | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        descriptor = os.open(
            tmp_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        stream = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = None
        with stream as f:
            f.write(payload)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        pass


def save_json_locked(path: Path, data) -> None:
    with file_lock():
        save_json_unlocked(path, data)


def save_json(path: Path, data) -> None:
    save_json_locked(path, data)


def update_json(path: Path, default, mutator) -> Any:
    with file_lock():
        data = load_json(path, default)
        result = mutator(data)
        save_json_unlocked(path, data)
        return result


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if os.name != "nt":
        try:
            stat = subprocess.check_output(["ps", "-o", "stat=", "-p", str(pid)], text=True, stderr=subprocess.DEVNULL).strip()
            if stat.startswith("Z"):
                return False
        except Exception:
            pass
    return True


def reap_child_processes() -> None:
    if os.name == "nt" or not hasattr(os, "waitpid"):
        return
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        except OSError:
            return
        if pid <= 0:
            return
        append_log(f"child-reaped pid={pid}")


def process_lines() -> list[str]:
    if os.name == "nt":
        commands = [
            ["wmic", "process", "get", "ProcessId,CommandLine", "/FORMAT:LIST"],
            ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"],
        ]
    else:
        commands = [["ps", "-ax", "-o", "pid=,command="]]
    for command in commands:
        try:
            out = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
            return out.splitlines()
        except Exception:
            continue
    return []


def terminate_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if not pid_alive(pid):
                    return
                time.sleep(0.05)
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def find_watcher_pids() -> list[int]:
    pids = []
    this_pid = os.getpid()
    for line in process_lines():
        if (
            "jarvis_line/watcher.py --watch-file" not in line
            and "jarvis_line/watcher.py --watch-sessions" not in line
            and "jarvis_line.watcher --watch-sessions" not in line
            and "jarvis_line_watcher.py --watch-file" not in line
            and "jarvis_line_watcher.py --watch-sessions" not in line
        ):
            continue
        parts = line.strip().split()
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid != this_pid:
            pids.append(pid)
    return pids


def terminate_stale_watchers(keep_pid: int | None = None) -> None:
    for pid in find_watcher_pids():
        if keep_pid and pid == keep_pid:
            continue
        terminate_pid(pid)
        append_log(f"stale-watcher-killed pid={pid}")


def normalized_path_text(value: object) -> str:
    return str(value).replace("\\", "/")


def find_audio_worker_pids() -> list[int]:
    pids = []
    this_pid = os.getpid()
    allowed_roots = (
        normalized_path_text(CODEX_HOME),
        normalized_path_text(KOKORO_VENV),
        normalized_path_text(PACKAGE_DIR),
    )
    for line in process_lines():
        normalized_line = normalized_path_text(line)
        if (
            "jarvis_line/audio_worker.py" not in normalized_line
            and "jarvis_line.audio_worker" not in normalized_line
            and "jarvis_line_audio_worker.py" not in normalized_line
        ):
            continue
        if not any(root and root in normalized_line for root in allowed_roots):
            continue
        parts = line.strip().split()
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid != this_pid:
            pids.append(pid)
    return pids


def terminate_stale_audio_workers(keep_pid: int | None = None) -> None:
    for pid in find_audio_worker_pids():
        if keep_pid and pid == keep_pid:
            continue
        terminate_pid(pid)
        append_log(f"stale-audio-worker-killed pid={pid}")


def current_thread_id() -> str:
    return str(os.environ.get("CODEX_THREAD_ID") or "").strip()


def active_thread_ids(state: dict[str, Any] | None = None) -> list[str]:
    state = state if state is not None else load_json(STATE_PATH, {})
    runtime = state.get("__runtime__") if isinstance(state, dict) else {}
    raw_ids = (runtime or {}).get("active_thread_ids") or {}
    if isinstance(raw_ids, dict):
        ids = [str(key).strip() for key in raw_ids.keys()]
    elif isinstance(raw_ids, list):
        ids = [str(value).strip() for value in raw_ids]
    else:
        ids = []
    env_id = current_thread_id()
    if env_id:
        ids.append(env_id)
    seen = set()
    result = []
    for thread_id in ids:
        if not thread_id or thread_id in seen:
            continue
        seen.add(thread_id)
        result.append(thread_id)
    return result


def record_active_thread_id(thread_id: str | None = None) -> None:
    thread_id = str(thread_id or current_thread_id() or "").strip()
    if not thread_id:
        return
    now_ms = int(time.time() * 1000)

    def mutate(state):
        runtime = state.setdefault("__runtime__", {})
        active = runtime.setdefault("active_thread_ids", {})
        if not isinstance(active, dict):
            active = {}
            runtime["active_thread_ids"] = active
        active[thread_id] = now_ms
        stale_before = now_ms - (SESSION_SCAN_WINDOW_SECONDS * 1000)
        for key in list(active.keys()):
            if int(active.get(key) or 0) < stale_before:
                active.pop(key, None)

    update_json(STATE_PATH, {}, mutate)


def session_candidates_for_thread_ids(thread_ids: list[str]) -> list[Path]:
    paths: list[Path] = []
    if not SESSIONS_ROOT.exists():
        return paths
    for thread_id in thread_ids:
        safe_id = re.sub(r"[^A-Za-z0-9-]", "", thread_id)
        if not safe_id:
            continue
        paths.extend(SESSIONS_ROOT.rglob(f"*{safe_id}*.jsonl"))
    unique = {}
    for path in paths:
        try:
            unique[str(path.resolve())] = path
        except OSError:
            continue
    result = list(unique.values())
    result.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return result


def current_session_candidates() -> list[Path]:
    if not SESSIONS_ROOT.exists():
        return []
    thread_candidates = session_candidates_for_thread_ids(active_thread_ids())

    now = time.time()
    paths = []
    for path in SESSIONS_ROOT.rglob("*.jsonl"):
        try:
            if now - path.stat().st_mtime <= SESSION_SCAN_WINDOW_SECONDS:
                paths.append(path)
        except OSError:
            continue
    paths.extend(thread_candidates)
    unique = {}
    for path in paths:
        try:
            unique[str(path.resolve())] = path
        except OSError:
            continue
    paths = list(unique.values())
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if thread_candidates:
        thread_keys = {str(path.resolve()) for path in thread_candidates}
        paths.sort(key=lambda p: (str(p.resolve()) not in thread_keys, -p.stat().st_mtime))
    return paths


def session_key_for_path(path: Path) -> str:
    matches = CODEX_SESSION_ID_RE.findall(path.name)
    if matches:
        return f"codex:{matches[-1].lower()}"
    return str(path.resolve())


def collect_text(value: Any) -> list[str]:
    parts: list[str] = []
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, list):
        for item in value:
            parts.extend(collect_text(item))
    elif isinstance(value, dict):
        item_type = value.get("type")
        if item_type in (None, "text", "output_text", "input_text"):
            for key in ("text", "content", "value"):
                if key in value:
                    parts.extend(collect_text(value.get(key)))
        elif "text" in value:
            parts.extend(collect_text(value.get("text")))
    return [part for part in parts if part]


def assistant_payload_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("type") == "response_item":
        payload = event.get("payload") or {}
        if isinstance(payload, dict):
            return payload
    payload = event.get("payload") or {}
    if isinstance(payload, dict) and payload.get("type") == "task_complete":
        text = str(payload.get("last_agent_message") or "").strip()
        if text and extract_jarvis_line(text):
            return {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": text,
            }
    if isinstance(payload, dict) and payload.get("type") == "agent_message":
        return {
            "type": "message",
            "role": "assistant",
            "phase": payload.get("phase") or event.get("phase") or "commentary",
            "content": payload.get("message") or payload.get("content") or payload.get("text") or "",
        }
    for key in ("message", "item"):
        payload = event.get(key) or {}
        if isinstance(payload, dict) and (payload.get("role") == "assistant" or payload.get("type") == "message"):
            return payload
    return None


def assistant_payload_from_notify_event(event: dict[str, Any]) -> dict[str, Any] | None:
    parts = []
    for key in ("last_agent_message", "agent_message", "message", "content", "text"):
        parts.extend(collect_text(event.get(key)))
    text = "\n".join(parts).strip()
    if not text or not extract_jarvis_line(text):
        return None
    return {
        "type": "message",
        "role": "assistant",
        "phase": event.get("phase") or event.get("message_phase") or "final_answer",
        "content": text,
    }


def phase_from_payload(payload: dict[str, Any]) -> str:
    return str(payload.get("phase") or "final")


def payload_is_assistant_message(payload: dict[str, Any]) -> bool:
    payload_type = payload.get("type")
    role = payload.get("role")
    return (payload_type in ("message", "agent_message", None)) and role in ("assistant", None)


def assistant_text_from_payload(payload: dict) -> tuple[str, str]:
    phase = phase_from_payload(payload)
    parts = []
    for key in ("content", "text", "message", "output_text"):
        parts.extend(collect_text(payload.get(key)))
    return phase, "\n".join(parts).strip()


def message_id(
    session_key: str,
    phase: str,
    jarvis_line: str,
    attention_type: str | None = None,
) -> str:
    digest = hashlib.sha256(
        f"{session_key}\0{phase}\0{attention_type or ''}\0{jarvis_line}".encode("utf-8")
    ).hexdigest()
    return digest[:20]


def remember_latest_message(session_key: str, phase: str, text: str, jarvis_line: str) -> None:
    if not jarvis_line:
        return
    def mutate(cache):
        sessions = cache.setdefault("sessions", {})
        now_ms = int(time.time() * 1000)
        entry = {
            "session_key": session_key,
            "phase": phase,
            "text": text,
            "jarvis_line": jarvis_line,
            "message_id": message_id(session_key, phase, jarvis_line),
            "updated_ts_ms": now_ms,
        }
        session_cache = sessions.setdefault(session_key, {})
        session_cache["latest"] = entry
        if is_final_phase(phase):
            session_cache["latest_final"] = entry
        cache["active_session_key"] = session_key
        cache["updated_ts_ms"] = now_ms

        stale_before = now_ms - (SESSION_SCAN_WINDOW_SECONDS * 1000)
        for key in list(sessions.keys()):
            latest = (sessions.get(key) or {}).get("latest") or {}
            if int(latest.get("updated_ts_ms") or 0) < stale_before:
                sessions.pop(key, None)
    update_json(LATEST_MESSAGES_PATH, {}, mutate)


def latest_cached_message(
    session_key: str | None = None,
    final_only: bool = True,
    min_updated_ts_ms: int = 0,
) -> dict[str, Any] | None:
    cache = load_json(LATEST_MESSAGES_PATH, {})
    sessions = cache.get("sessions") or {}
    key = session_key or cache.get("active_session_key")
    if not key or key not in sessions:
        return None
    session_cache = sessions.get(key) or {}
    entry = session_cache.get("latest_final" if final_only else "latest")
    if not isinstance(entry, dict):
        return None
    if min_updated_ts_ms and int(entry.get("updated_ts_ms") or 0) < min_updated_ts_ms:
        return None
    return entry


def remember_approval_reviewer(session_key: str, reviewer: object) -> bool:
    normalized = str(reviewer or "").strip().lower()
    if normalized not in {"user", "auto_review", "guardian_subagent"}:
        return False
    now_ms = int(time.time() * 1000)

    def mutate(state):
        contexts = state.setdefault("__approval_contexts__", {})
        if not isinstance(contexts, dict):
            contexts = {}
            state["__approval_contexts__"] = contexts
        contexts[session_key] = {
            "approvals_reviewer": normalized,
            "updated_ts_ms": now_ms,
        }
        stale_before = now_ms - SESSION_SCAN_WINDOW_SECONDS * 1000
        ordered = sorted(
            (
                (key, value)
                for key, value in contexts.items()
                if isinstance(value, dict)
            ),
            key=lambda item: int(item[1].get("updated_ts_ms") or 0),
            reverse=True,
        )
        state["__approval_contexts__"] = {
            key: value
            for key, value in ordered[:APPROVAL_CONTEXTS_MAX_ENTRIES]
            if int(value.get("updated_ts_ms") or 0) >= stale_before
        }

    update_json(STATE_PATH, {}, mutate)
    return True


def cached_approval_reviewer(session_key: str) -> str | None:
    state = load_json(STATE_PATH, {})
    contexts = state.get("__approval_contexts__") if isinstance(state, dict) else {}
    if not isinstance(contexts, dict):
        return None
    context = contexts.get(session_key)
    if not isinstance(context, dict):
        return None
    updated_ts_ms = int(context.get("updated_ts_ms") or 0)
    if updated_ts_ms < int(time.time() * 1000) - SESSION_SCAN_WINDOW_SECONDS * 1000:
        return None
    reviewer = str(context.get("approvals_reviewer") or "").strip().lower()
    if reviewer not in {"user", "auto_review", "guardian_subagent"}:
        return None
    return reviewer


def enqueue_audio_job(
    session_key: str,
    phase: str,
    jarvis_line: str,
    text: str = "",
    attention_type: str | None = None,
    correlation_token: str | None = None,
) -> str | None:
    jarvis_line = str(jarvis_line or "").strip()
    if not jarvis_line:
        return None
    job_id = message_id(session_key, phase, jarvis_line, attention_type)
    now_ms = int(time.time() * 1000)
    cfg = runtime_config()

    def mutate(queue):
        jobs = list(queue.get("jobs") or [])
        stale_before = now_ms - (AUDIO_QUEUE_STALE_SECONDS * 1000)
        new_job = {
            "message_id": job_id,
            "session_key": session_key,
            "phase": phase,
            "jarvis_line": jarvis_line,
            "text": text[:4096],
            "enqueued_ts_ms": now_ms,
        }
        if is_attention_phase(phase):
            new_job["attention_type"] = attention_type
            new_job["correlation_token"] = correlation_token
            new_job["expires_ts_ms"] = now_ms + ATTENTION_TTL_SECONDS * 1000
        max_jobs = int(cfg.get("max_queue_size") or AUDIO_QUEUE_MAX_JOBS)
        jobs = schedule_job(jobs, new_job, max_jobs, stale_before)
        queue["jobs"] = jobs
        queue["updated_ts_ms"] = now_ms
        return job_id

    return update_json(AUDIO_QUEUE_PATH, {"jobs": []}, mutate)


def cancel_attention_job(
    session_key: str,
    attention_type: str,
    correlation_token: str,
) -> bool:
    if not session_key or attention_type not in ATTENTION_TYPES or not correlation_token:
        return False
    cancellation_key = attention_cancellation_key(
        session_key,
        attention_type,
        correlation_token,
    )
    if not cancellation_key:
        return False
    now_ms = int(time.time() * 1000)

    def mutate(queue):
        jobs = list(queue.get("jobs") or [])
        kept = [
            job
            for job in jobs
            if not (
                job.get("session_key") == session_key
                and is_attention_phase(str(job.get("phase") or ""))
                and job.get("attention_type") == attention_type
                and job.get("correlation_token") == correlation_token
            )
        ]
        cancellations = prune_attention_cancellations(
            queue.get("attention_cancellations"),
            now_ms - AUDIO_QUEUE_STALE_SECONDS * 1000,
            ATTENTION_CANCELLATION_MAX_ENTRIES - 1,
        )
        cancellations[cancellation_key] = now_ms
        queue["jobs"] = kept
        queue["attention_cancellations"] = cancellations
        queue["updated_ts_ms"] = now_ms
        return len(kept) != len(jobs)

    removed = bool(update_json(AUDIO_QUEUE_PATH, {"jobs": []}, mutate))
    append_log(f"attention-cancelled type={attention_type} queued={str(removed).lower()}")
    diagnostics.record_event(
        "cancelled",
        session_key=session_key,
        phase="attention",
        attention_type=attention_type,
        queued=removed,
    )
    return True


def audio_worker_is_healthy(state: dict[str, Any] | None = None) -> bool:
    state = state if state is not None else load_json(STATE_PATH, {})
    worker = state.get("__audio_worker__", {}) if isinstance(state, dict) else {}
    pid = int((worker or {}).get("pid") or 0)
    heartbeat_ms = int((worker or {}).get("heartbeat_ts_ms") or 0)
    if not pid or not pid_alive(pid):
        return False
    if heartbeat_ms and int(time.time() * 1000) - heartbeat_ms > AUDIO_WORKER_STALE_SECONDS * 1000:
        return False
    return True


def audio_queue_has_jobs() -> bool:
    queue = load_json(AUDIO_QUEUE_PATH, {"jobs": []})
    return bool((queue or {}).get("jobs") or [])


def launch_audio_worker() -> None:
    if runtime_config().get("speech_enabled") is False:
        append_log("audio-worker-skip speech-disabled")
        return
    reap_child_processes()
    state = load_json(STATE_PATH, {})
    if audio_worker_is_healthy(state):
        pid = int(((state.get("__audio_worker__") or {}) if isinstance(state, dict) else {}).get("pid") or 0)
        terminate_stale_audio_workers(keep_pid=pid)
        return

    terminate_stale_audio_workers()

    worker = state.get("__audio_worker__", {}) if isinstance(state, dict) else {}
    old_pid = int((worker or {}).get("pid") or 0)
    if old_pid and old_pid != os.getpid():
        terminate_pid(old_pid)
        append_log(f"audio-worker-stale-killed pid={old_pid}")
    cmd = [str(KOKORO_PY if KOKORO_PY.exists() else Path(sys.executable)), str(WORKER_PATH)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def mutate(new_state):
        new_state["__audio_worker__"] = {
            "pid": proc.pid,
            "mode": "audio",
            "started_ts": int(time.time()),
            "heartbeat_ts_ms": int(time.time() * 1000),
        }
    update_json(STATE_PATH, {}, mutate)
    append_log(f"audio-worker-launch pid={proc.pid}")


def queue_jarvis_line(
    session_key: str,
    phase: str,
    jarvis_line: str,
    text: str = "",
    attention_type: str | None = None,
    correlation_token: str | None = None,
) -> bool:
    cfg = runtime_config()
    if runtime_is_stopped():
        append_log(f"skip-queue runtime-stopped phase={phase}")
        diagnostics.record_event(
            "skipped",
            session_key=session_key,
            phase=phase,
            attention_type=attention_type,
            reason="runtime_stopped",
        )
        return False
    if cfg.get("speech_enabled") is False:
        append_log(f"skip-queue speech-disabled phase={phase}")
        diagnostics.record_event("skipped", session_key=session_key, phase=phase, reason="speech_disabled")
        return False
    if is_attention_phase(phase):
        if not bool(cfg.get("attention_enabled", False)):
            append_log(f"skip-queue attention-disabled type={attention_type or 'unknown'}")
            diagnostics.record_event(
                "skipped",
                session_key=session_key,
                phase=phase,
                attention_type=attention_type,
                reason="attention_disabled",
            )
            return False
        if attention_type not in ATTENTION_TYPES:
            append_log("skip-queue invalid-attention-type")
            return False
        text = jarvis_line
        if correlation_token and not re.fullmatch(r"[a-f0-9]{20}", correlation_token):
            correlation_token = None
    else:
        attention_type = None
        correlation_token = None
    if quiet_day_active(cfg):
        append_log(f"skip-queue quiet-day phase={phase}")
        diagnostics.record_event("skipped", session_key=session_key, phase=phase, reason="quiet_day")
        return False
    if quiet_hours_active(cfg):
        append_log(f"skip-queue quiet-hours phase={phase}")
        diagnostics.record_event("skipped", session_key=session_key, phase=phase, reason="quiet_hours")
        return False
    if not speak_mode_allows(phase, cfg):
        append_log(f"skip-queue speak-mode phase={phase}")
        diagnostics.record_event("skipped", session_key=session_key, phase=phase, reason="speak_mode")
        return False
    jarvis_line = trim_spoken_text(jarvis_line, cfg)
    template = str(cfg.get("message_template") or "{line}")
    jarvis_line = trim_spoken_text(template.replace("{line}", jarvis_line), cfg)
    if not should_speak(session_key, phase, jarvis_line, attention_type):
        context = diagnostics.runtime_log_context(
            session_key=session_key,
            line=jarvis_line,
            include_content=bool(cfg.get("debug_content_logging", False)),
        )
        append_log(f"skip-queue-debounced phase={phase} {context}".rstrip())
        diagnostics.record_event("skipped", session_key=session_key, phase=phase, reason="debounced")
        return False
    job_id = enqueue_audio_job(
        session_key,
        phase,
        jarvis_line,
        text,
        attention_type,
        correlation_token,
    )
    if not job_id:
        return False
    context = diagnostics.runtime_log_context(
        session_key=session_key,
        line=jarvis_line,
        include_content=bool(cfg.get("debug_content_logging", False)),
    )
    append_log(f"queued-audio phase={phase} job={job_id} {context}".rstrip())
    diagnostics.record_event(
        "queued",
        session_key=session_key,
        message_id=job_id,
        phase=phase,
        attention_type=attention_type,
    )
    launch_audio_worker()
    return True


def find_active_session_file() -> Path | None:
    candidates = current_session_candidates()
    return candidates[0] if candidates else None


def normalize_session_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        return None
    if path.suffix != ".jsonl":
        return None
    return path


def session_file_from_notify_event(event: dict[str, Any]) -> Path | None:
    keys = (
        "session_file",
        "session_path",
        "sessionFile",
        "sessionPath",
        "transcript_path",
        "transcriptPath",
        "conversation_file",
        "conversationFile",
    )
    for key in keys:
        path = normalize_session_path(event.get(key))
        if path:
            return path
    nested = event.get("session") or event.get("conversation") or {}
    if isinstance(nested, dict):
        for key in keys + ("path", "file"):
            path = normalize_session_path(nested.get(key))
            if path:
                return path
    return None


def read_recent_lines(path: Path, max_bytes: int = RECENT_BYTES) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
    except OSError:
        return []

    text = data.decode("utf-8", errors="ignore")
    if start > 0:
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
    return [line for line in text.splitlines() if line.strip()]


def maybe_speak_from_payload(payload: dict[str, Any], session_key: str) -> bool:
    if not payload_is_assistant_message(payload):
        return False
    cfg = runtime_config()
    phase, text = assistant_text_from_payload(payload)
    jarvis_line = extract_jarvis_line(text)
    if not jarvis_line and cfg.get("speak_without_prefix", False):
        jarvis_line = derive_spoken_line(text, cfg)
    if not jarvis_line:
        return False
    remember_latest_message(session_key, phase, text, jarvis_line)
    if queue_jarvis_line(session_key, phase, jarvis_line, text):
        return True
    return False


def speak_latest_final_from_session(path: Path) -> str:
    session_key = session_key_for_path(path)
    for raw_line in reversed(read_recent_lines(path)):
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        payload = assistant_payload_from_event(event)
        if not payload or not payload_is_assistant_message(payload):
            continue
        phase = phase_from_payload(payload)
        if not is_final_phase(phase):
            continue
        _, text = assistant_text_from_payload(payload)
        jarvis_line = extract_jarvis_line(text)
        if not jarvis_line:
            continue
        remember_latest_message(session_key, phase, text, jarvis_line)
        if queue_jarvis_line(session_key, phase, jarvis_line, text):
            return "spoken"
        return "duplicate"
    return "missing"


def speak_latest_final_from_cache(session_key: str | None = None, min_updated_ts_ms: int = 0) -> str:
    entry = latest_cached_message(session_key, final_only=True, min_updated_ts_ms=min_updated_ts_ms)
    if not entry:
        return "missing"
    cached_session = str(entry.get("session_key") or session_key or "")
    phase = str(entry.get("phase") or "final")
    jarvis_line = str(entry.get("jarvis_line") or "").strip()
    if not cached_session or not is_final_phase(phase) or not jarvis_line:
        return "missing"
    text = str(entry.get("text") or "")
    if queue_jarvis_line(cached_session, phase, jarvis_line, text):
        return "spoken"
    return "duplicate"


def extract_jarvis_line(text: str) -> str | None:
    matches = []
    for prefix in line_prefixes():
        pattern = re.compile(rf"(?im)^{re.escape(prefix)}\s*(.+?)\s*$")
        matches.extend(pattern.findall(text or ""))
    if not matches:
        return None
    return trim_spoken_text(matches[-1].strip())


def derive_spoken_line(text: str, cfg: dict[str, Any] | None = None) -> str | None:
    cfg = cfg if cfg is not None else runtime_config()
    cleaned = re.sub(r"```.*?```", " ", str(text or ""), flags=re.S)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    candidates = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("::", "{", "}", "[", "]")):
            continue
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if not line or line.lower().startswith(("skills used:", "jarvis line:")):
            continue
        candidates.append(line)
        if len(" ".join(candidates)) >= 80:
            break
    if not candidates:
        return None
    spoken = " ".join(candidates)
    sentence_match = re.match(r"^(.+?[.!?])(?:\s|$)", spoken)
    if sentence_match:
        spoken = sentence_match.group(1)
    return trim_spoken_text(spoken, cfg)


def should_speak(
    session_key: str,
    phase: str,
    jarvis_line: str,
    attention_type: str | None = None,
) -> bool:
    def mutate(state):
        session_state = state.setdefault(session_key, {})
        now_ms = int(time.time() * 1000)
        cfg = runtime_config()
        configured_window = cfg.get("dedupe_window_seconds")
        debounce_ms = int(float(configured_window) * 1000) if configured_window is not None else (COMMENTARY_DEBOUNCE_SECONDS if phase == "commentary" else FINAL_DEBOUNCE_SECONDS) * 1000
        last_text = str(session_state.get("last_text") or "")
        identity_phase = f"attention:{attention_type}" if is_attention_phase(phase) else phase
        last_phase = str(session_state.get("last_phase") or "")
        last_ts = int(session_state.get("last_ts_ms") or 0)
        if jarvis_line == last_text and identity_phase == last_phase and is_final_phase(phase):
            return False
        if jarvis_line == last_text and identity_phase == last_phase and now_ms - last_ts < debounce_ms:
            return False
        session_state["last_text"] = jarvis_line
        session_state["last_phase"] = identity_phase
        session_state["last_ts_ms"] = now_ms
        stale_before = now_ms - (SESSION_SCAN_WINDOW_SECONDS * 1000)
        for key in list(state.keys()):
            if str(key).startswith("__"):
                continue
            if int((state.get(key, {}) or {}).get("last_ts_ms") or 0) < stale_before:
                state.pop(key, None)
        return True
    return bool(update_json(STATE_PATH, {}, mutate))


def process_line(raw_line: str, session_key: str) -> None:
    try:
        event = json.loads(raw_line)
    except Exception:
        return
    if not isinstance(event, dict):
        return
    if event.get("type") == "turn_context":
        turn_payload = event.get("payload")
        if isinstance(turn_payload, dict):
            remember_approval_reviewer(
                session_key,
                turn_payload.get("approvals_reviewer"),
            )
        return
    if event.get("type") == "response_item":
        response_payload = event.get("payload")
        if isinstance(response_payload, dict):
            input_request = parse_input_request_payload(response_payload)
            if input_request is not None:
                cfg = runtime_config()
                if bool(cfg.get("attention_enabled", False)):
                    message = format_input_required(
                        input_request.header,
                        input_request.question,
                        cfg.get("line_language", "English"),
                    )
                    queue_jarvis_line(
                        session_key,
                        "attention",
                        message.line,
                        message.line,
                        attention_type="input_required",
                        correlation_token=input_request.correlation_token,
                    )
                return
            if response_payload.get("type") in {
                "function_call_output",
                "custom_tool_call_output",
            }:
                token = correlation_token(response_payload.get("call_id"))
                if token:
                    cancel_attention_job(session_key, "input_required", token)
                return
    payload = assistant_payload_from_event(event)
    if payload:
        maybe_speak_from_payload(payload, session_key)


def event_timestamp_ms(event: dict[str, Any]) -> int | None:
    raw = str(event.get("timestamp") or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return int(datetime.fromisoformat(raw).timestamp() * 1000)
    except Exception:
        return None


def recover_latest_recent_line(path: Path, session_key: str, min_ts_ms: int) -> bool:
    for raw_line in reversed(read_recent_lines(path)):
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        ts_ms = event_timestamp_ms(event)
        if ts_ms is None or ts_ms < min_ts_ms:
            return False
        payload = assistant_payload_from_event(event)
        if not payload:
            continue
        return maybe_speak_from_payload(payload, session_key)
    return False


def load_notify_event(arg_payload: str = "") -> dict[str, Any]:
    event_data: dict[str, Any] = {}

    raw_arg = str(arg_payload or "").strip()
    loaded_from_arg = False
    if raw_arg.startswith("{"):
        try:
            parsed = json.loads(raw_arg)
            if isinstance(parsed, dict):
                event_data.update(parsed)
                loaded_from_arg = True
        except Exception:
            pass

    if not loaded_from_arg and not sys.stdin.isatty():
        try:
            raw_stdin = sys.stdin.read().strip()
        except OSError:
            raw_stdin = ""
        if raw_stdin:
            try:
                parsed = json.loads(raw_stdin)
                if isinstance(parsed, dict):
                    event_data.update(parsed)
            except Exception:
                pass

    return event_data


def watcher_is_healthy(state: dict[str, Any] | None = None) -> bool:
    state = state if state is not None else load_json(STATE_PATH, {})
    watcher = state.get("__watcher__", {}) if isinstance(state, dict) else {}
    pid = int((watcher or {}).get("pid") or 0)
    heartbeat_ms = int((watcher or {}).get("heartbeat_ts_ms") or 0)
    if not pid or not pid_alive(pid):
        return False
    if heartbeat_ms and int(time.time() * 1000) - heartbeat_ms > WATCHER_STALE_SECONDS * 1000:
        return False
    return True


def update_watcher_heartbeat() -> None:
    pid = os.getpid()
    now_ms = int(time.time() * 1000)
    def mutate(state):
        watcher = state.setdefault("__watcher__", {})
        watcher["pid"] = pid
        watcher["mode"] = "supervisor"
        watcher["heartbeat_ts_ms"] = now_ms
        watcher.setdefault("started_ts", int(time.time()))
    update_json(STATE_PATH, {}, mutate)


def is_turn_complete_notify(event: dict[str, Any]) -> bool:
    raw_event = str(
        event.get("hook_event_name")
        or event.get("event")
        or event.get("type")
        or ""
    ).strip()
    notif_type = str(event.get("notification_type") or "").strip().lower()
    event_key = raw_event.lower().replace("_", "-")
    return event_key in ("agent-turn-complete", "assistant-turn-complete", "turn-complete") or notif_type == "turn_complete"


def runtime_is_stopped(state: dict[str, Any] | None = None) -> bool:
    state = state if state is not None else load_json(STATE_PATH, {})
    runtime = state.get("__runtime__") if isinstance(state, dict) else {}
    return bool((runtime or {}).get("stopped"))


def notify_trigger(arg_payload: str = "") -> int:
    started_ms = int(time.time() * 1000)
    event = load_notify_event(arg_payload)
    if not is_turn_complete_notify(event):
        append_log("notify-skip unsupported-event")
        return 0
    record_active_thread_id()

    state = load_json(STATE_PATH, {})
    if runtime_is_stopped(state):
        append_log("notify-skip runtime-stopped")
        return 0
    if runtime_config().get("speech_enabled") is False:
        append_log("notify-skip speech-disabled")
        return 0

    payload = assistant_payload_from_notify_event(event)
    if not payload or not payload_is_assistant_message(payload):
        deadline = time.time() + NOTIFY_RETRY_SECONDS
        min_updated_ts_ms = started_ms - 30000
        while time.time() < deadline:
            status = speak_latest_final_from_cache(min_updated_ts_ms=min_updated_ts_ms)
            if status in ("spoken", "duplicate"):
                append_log(f"notify-cache-{status}")
                return 0
            time.sleep(NOTIFY_POLL_SECONDS)
        append_log("notify-skip no-recent-final-payload")
        return 0

    phase, text = assistant_text_from_payload(payload)
    jarvis_line = extract_jarvis_line(text)
    if not jarvis_line or not is_final_phase(phase):
        append_log("notify-skip no-recent-final-payload")
        return 0

    if not watcher_is_healthy(state):
        append_log("notify-watchdog unhealthy-launch")
        launch_watcher()

    target = session_file_from_notify_event(event) or find_active_session_file()
    if target is None:
        append_log("notify-skip no-session-file")
        return 0

    append_log(f"notify-turn-complete {diagnostics.runtime_log_context(session_key=target)}")
    session_key = session_key_for_path(target)

    remember_latest_message(session_key, phase, text, jarvis_line)
    queue_jarvis_line(session_key, phase, jarvis_line, text)
    return 0


def watch_file(path: Path, read_existing: bool = False) -> int:
    session_key = session_key_for_path(path)
    append_log(f"watch-start {diagnostics.runtime_log_context(session_key=session_key)}")
    launch_audio_worker()
    last_cleanup_check = maybe_run_cleanup(0.0)
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        if not read_existing:
            f.seek(0, os.SEEK_END)
        while True:
            last_cleanup_check = maybe_run_cleanup(last_cleanup_check)
            line = f.readline()
            if line:
                process_line(line, session_key)
                continue
            time.sleep(0.35)


def watch_sessions(read_existing: bool = False) -> int:
    append_log("watch-sessions-start")
    launch_audio_worker()
    last_cleanup_check = maybe_run_cleanup(0.0)

    handles: dict[str, Any] = {}
    last_refresh = 0.0
    last_heartbeat = 0.0
    while True:
        last_cleanup_check = maybe_run_cleanup(last_cleanup_check)
        now = time.time()
        if now - last_heartbeat >= WATCHER_HEARTBEAT_SECONDS:
            reap_child_processes()
            update_watcher_heartbeat()
            if audio_queue_has_jobs() and not audio_worker_is_healthy():
                append_log("audio-worker-relaunch pending-queue")
                launch_audio_worker()
            last_heartbeat = now

        if now - last_refresh >= SESSION_DISCOVERY_INTERVAL_SECONDS:
            candidates = current_session_candidates()
            candidate_keys = {str(path.resolve()) for path in candidates}

            for path in candidates:
                key = str(path.resolve())
                if key in handles:
                    continue
                try:
                    f = path.open("r", encoding="utf-8", errors="ignore")
                    if not read_existing:
                        if recover_latest_recent_line(
                            path,
                            session_key_for_path(path),
                            int((now - SESSION_RECOVERY_WINDOW_SECONDS) * 1000),
                        ):
                            append_log(f"watch-recover {diagnostics.runtime_log_context(session_key=key)}")
                        f.seek(0, os.SEEK_END)
                    handles[key] = f
                    append_log(f"watch-add {diagnostics.runtime_log_context(session_key=key)}")
                except OSError:
                    continue

            for key in list(handles.keys()):
                if key in candidate_keys:
                    continue
                try:
                    handles[key].close()
                except Exception:
                    pass
                handles.pop(key, None)
                append_log(f"watch-drop {diagnostics.runtime_log_context(session_key=key)}")

            last_refresh = now

        had_line = False
        for key, f in list(handles.items()):
            try:
                line = f.readline()
            except Exception:
                try:
                    f.close()
                except Exception:
                    pass
                handles.pop(key, None)
                append_log(f"watch-error {diagnostics.runtime_log_context(session_key=key)}")
                continue
            if not line:
                continue
            had_line = True
            process_line(line, session_key_for_path(Path(key)))

        if not had_line:
            time.sleep(0.2)


def launch_watcher() -> int:
    record_active_thread_id()
    candidates = current_session_candidates()
    if not candidates:
        append_log("launch-skip no-session-file")
        return 0

    state = load_json(STATE_PATH, {})
    if runtime_is_stopped(state):
        append_log("launch-skip runtime-stopped")
        return 0
    watcher = state.get("__watcher__", {})
    pid = int(watcher.get("pid") or 0)
    watched_mode = str(watcher.get("mode") or "")

    # Keep the current healthy watcher alive; otherwise we can cut off audio
    # mid-playback when UserPromptSubmit fires while Jarvis is speaking.
    if pid and watched_mode == "supervisor" and watcher_is_healthy(state):
        terminate_stale_watchers(keep_pid=pid)
        launch_audio_worker()
        append_log(f"launch-skip already-running pid={pid} mode=supervisor")
        return 0

    terminate_stale_watchers()

    cmd = [sys.executable, str(Path(__file__).resolve()), "--watch-sessions"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    def mutate(new_state):
        new_state["__watcher__"] = {
            "pid": proc.pid,
            "mode": "supervisor",
            "started_ts": int(time.time()),
            "heartbeat_ts_ms": int(time.time() * 1000),
        }
    update_json(STATE_PATH, {}, mutate)
    append_log(f"launch-ok pid={proc.pid} mode=supervisor")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--watch-file")
    parser.add_argument("--watch-sessions", action="store_true")
    parser.add_argument("--read-existing", action="store_true")
    parser.add_argument("notify_payload", nargs="?")
    args = parser.parse_args()

    if args.launch:
        return launch_watcher()
    if args.notify:
        return notify_trigger(args.notify_payload or "")
    if args.watch_file:
        return watch_file(Path(args.watch_file).expanduser(), read_existing=args.read_existing)
    if args.watch_sessions:
        return watch_sessions(read_existing=args.read_existing)

    return launch_watcher()


if __name__ == "__main__":
    raise SystemExit(main())
