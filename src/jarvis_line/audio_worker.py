#!/usr/bin/env python3
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from jarvis_line import kokoro_say as ks


CODEX_HOME = Path.home() / ".codex"
HOOKS_DIR = CODEX_HOME / "hooks"
QUEUE_PATH = HOOKS_DIR / "jarvis_line_audio_queue.json"
STATE_PATH = HOOKS_DIR / ".jarvis_line_state.json"
LOG_PATH = HOOKS_DIR / "jarvis_line_audio_worker.log"
LOCK_PATH = HOOKS_DIR / ".jarvis_line.lock"
AUDIO_LOCK_PATH = HOOKS_DIR / ".jarvis_line_audio.lock"

QUEUE_STALE_SECONDS = 90
WORKER_HEARTBEAT_SECONDS = 5.0
IDLE_SLEEP_SECONDS = 0.2
LOG_ROTATE_BYTES = 2 * 1024 * 1024
_SPEAKER = None


try:
    import fcntl
except Exception:
    fcntl = None


def rotate_log_if_needed() -> None:
    try:
        if not LOG_PATH.exists() or LOG_PATH.stat().st_size < LOG_ROTATE_BYTES:
            return
        rotated = LOG_PATH.with_suffix(LOG_PATH.suffix + ".1")
        rotated.unlink(missing_ok=True)
        os.replace(LOG_PATH, rotated)
    except Exception:
        pass


def append_log(message: str) -> None:
    try:
        HOOKS_DIR.mkdir(parents=True, exist_ok=True)
        rotate_log_if_needed()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        lock_dir = path.with_name(path.name + ".d")
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
    with path.open("a+", encoding="utf-8") as lock_file:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
            f.write(payload)
            f.write("\n")
            tmp_name = f.name
        os.replace(tmp_name, path)
    except Exception:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)
        raise


def update_json(path: Path, default, mutator, lock_path: Path = LOCK_PATH) -> Any:
    with file_lock(lock_path):
        data = load_json(path, default)
        result = mutator(data)
        save_json_unlocked(path, data)
        return result


def drop_stale_jobs(jobs: list[dict[str, Any]], now_ms: int) -> list[dict[str, Any]]:
    stale_before = now_ms - QUEUE_STALE_SECONDS * 1000
    return [job for job in jobs if int(job.get("enqueued_ts_ms") or 0) >= stale_before]


def dequeue_audio_job() -> dict[str, Any] | None:
    now_ms = int(time.time() * 1000)

    def mutate(queue):
        jobs = drop_stale_jobs(list(queue.get("jobs") or []), now_ms)
        job = jobs.pop(0) if jobs else None
        queue["jobs"] = jobs
        queue["updated_ts_ms"] = now_ms
        return job

    return update_json(QUEUE_PATH, {"jobs": []}, mutate)


def update_worker_heartbeat() -> None:
    pid = os.getpid()
    now_ms = int(time.time() * 1000)

    def mutate(state):
        worker = state.setdefault("__audio_worker__", {})
        worker["pid"] = pid
        worker["mode"] = "audio"
        worker["heartbeat_ts_ms"] = now_ms
        worker.setdefault("started_ts", int(time.time()))

    update_json(STATE_PATH, {}, mutate)


def ensure_speaker(preload_voice: bool = False):
    cfg = ks.load_config()
    global _SPEAKER
    if _SPEAKER is None:
        started = time.perf_counter()
        model_path = Path(cfg.get("model_path", ""))
        voices_path = Path(cfg.get("voices_path", ""))
        engine = ks.Kokoro(str(model_path), str(voices_path))
        _SPEAKER = {"config": cfg, "engine": engine, "voice_cache": {}}
        append_log(f"speaker-init duration_ms={(time.perf_counter() - started) * 1000:.0f}")
    if preload_voice:
        speaker = _SPEAKER
        voice_spec = str(speaker["config"].get("voice", "bm_george:70,bm_lewis:30"))
        voice_cache = speaker["voice_cache"]
        if voice_spec not in voice_cache:
            started = time.perf_counter()
            voice_cache[voice_spec] = ks.build_voice_tensor(speaker["engine"], voice_spec)
            append_log(f"voice-warm voice={voice_spec} duration_ms={(time.perf_counter() - started) * 1000:.0f}")
    return _SPEAKER


def warm_tts_if_configured() -> None:
    cfg = ks.load_config()
    if cfg.get("speech_enabled") is False:
        return
    if cfg.get("warm_tts") is False:
        return
    backend = str(cfg.get("tts") or "kokoro").strip().lower()
    if backend != "kokoro":
        return
    try:
        speaker = ensure_speaker(preload_voice=True)
        voice_spec = str(speaker["config"].get("voice", "bm_george:70,bm_lewis:30"))
        voice = speaker["voice_cache"][voice_spec]
        warm_text = str(cfg.get("warm_tts_text") or "Ready.").strip() or "Ready."
        lang = str(cfg.get("lang", "en-gb"))
        speed = float(cfg.get("speed", 1.08))
        metrics = ks.warm_stream(speaker["engine"], warm_text, voice, lang, speed)
        first_chunk_ms = metrics.get("first_chunk_ms") if isinstance(metrics, dict) else None
        if first_chunk_ms is not None:
            append_log(f"stream-warm first_chunk_ms={float(first_chunk_ms):.0f}")
        append_log("tts-warm-ready backend=kokoro")
    except Exception as exc:
        append_log(f"tts-warm-error backend=kokoro reason={exc.__class__.__name__}")


def speak_line(line: str) -> None:
    if not line:
        return
    with file_lock(AUDIO_LOCK_PATH):
        started = time.perf_counter()
        cfg = ks.load_config()
        fallback = str(cfg.get("fallback_tts") or "").strip().lower()
        backend = str(cfg.get("tts") or "kokoro").strip().lower()
        try:
            speak_with_backend(line, cfg, backend)
            append_log(f"backend-done backend={backend} duration_ms={(time.perf_counter() - started) * 1000:.0f}")
            return
        except Exception as exc:
            if not fallback or fallback == backend:
                raise
            append_log(f"backend-fallback from={backend} to={fallback} reason={exc.__class__.__name__}")
            fallback_cfg = dict(cfg)
            fallback_cfg["tts"] = fallback
            speak_with_backend(line, fallback_cfg, fallback)
            append_log(f"backend-done backend={fallback} fallback_from={backend} duration_ms={(time.perf_counter() - started) * 1000:.0f}")


def speak_with_backend(line: str, cfg: dict[str, Any], backend: str) -> None:
        if backend == "command":
            speak_command(line, cfg)
            return
        if backend == "system":
            speak_system(line, cfg)
            return
        if backend == "macos":
            speak_macos(line, cfg)
            return
        speaker = ensure_speaker()
        voice_spec = str(speaker["config"].get("voice", "bm_george:70,bm_lewis:30"))
        voice_cache = speaker["voice_cache"]
        if voice_spec not in voice_cache:
            voice_cache[voice_spec] = ks.build_voice_tensor(speaker["engine"], voice_spec)

        playback_mode = str(speaker["config"].get("playback_mode", "stream")).strip().lower()
        volume = float(speaker["config"].get("volume", 0.7))
        lang = str(speaker["config"].get("lang", "en-gb"))
        speed = float(speaker["config"].get("speed", 1.08))
        voice = voice_cache[voice_spec]

        if playback_mode == "stream":
            try:
                metrics = ks.play_stream(speaker["engine"], line, voice, lang, speed, volume) or {}
                first_chunk_ms = metrics.get("first_chunk_ms") if isinstance(metrics, dict) else None
                if first_chunk_ms is not None:
                    append_log(f"stream-played first_chunk_ms={float(first_chunk_ms):.0f}")
                return
            except Exception as exc:
                append_log(f"stream-fallback reason={exc.__class__.__name__}")
                if str(speaker["config"].get("fallback_playback_mode", "tempfile")).strip().lower() != "tempfile":
                    raise

        temp_dir = Path(speaker["config"].get("temp_dir", str(CODEX_HOME / "tts" / "generated")))
        filename = f"kokoro_{int(time.time() * 1000)}.wav"
        out_path = temp_dir / filename
        ks.synthesize_to_file(speaker["engine"], line, voice, lang, speed, out_path)
        try:
            ks.spawn_player(out_path, volume)
        finally:
            if speaker["config"].get("delete_after_play", True):
                out_path.unlink(missing_ok=True)


def format_command_parts(parts: list[str], line: str, output_path: Path | None = None) -> list[str]:
    output = str(output_path or "")
    return [
        str(part)
        .replace("{text}", line)
        .replace("{text_json}", json.dumps(line, ensure_ascii=False))
        .replace("{output}", output)
        for part in parts
    ]


def command_parts(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(part) for part in value]
    if isinstance(value, str):
        return shlex.split(value)
    return []


def speak_command(line: str, cfg: dict[str, Any]) -> None:
    mode = str(cfg.get("command_mode") or "play").strip().lower()
    timeout = float(cfg.get("command_timeout_seconds") or 60)
    retries = int(cfg.get("command_retries") or 0)
    cwd = str(cfg.get("command_cwd") or "") or None
    env = os.environ.copy()
    extra_env = cfg.get("command_env") or {}
    if isinstance(extra_env, dict):
        env.update({str(key): str(value) for key, value in extra_env.items()})
    command = command_parts(cfg.get("command"))
    if not command:
        raise RuntimeError("command backend requires command")
    attempts = max(1, retries + 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            run_command_backend(line, cfg, command, mode, timeout, cwd, env)
            return
        except Exception as exc:
            last_error = exc
            append_log(f"command-attempt-error attempt={attempt + 1} reason={exc.__class__.__name__}")
            if attempt + 1 < attempts:
                time.sleep(0.25)
    if last_error:
        raise last_error


def run_command_backend(
    line: str,
    cfg: dict[str, Any],
    command: list[str],
    mode: str,
    timeout: float,
    cwd: str | None,
    env: dict[str, str],
) -> None:
    if mode == "file":
        temp_dir = Path(cfg.get("temp_dir", str(CODEX_HOME / "tts" / "generated")))
        temp_dir.mkdir(parents=True, exist_ok=True)
        suffix = str(cfg.get("command_output_suffix") or ".wav")
        output_path = temp_dir / f"jarvis_line_{int(time.time() * 1000)}{suffix}"
        subprocess.run(format_command_parts(command, line, output_path), check=True, timeout=timeout, cwd=cwd, env=env)
        player = command_parts(cfg.get("player"))
        try:
            if player:
                subprocess.run(format_command_parts(player, line, output_path), check=True, timeout=timeout, cwd=cwd, env=env)
        finally:
            if cfg.get("delete_after_play", True):
                output_path.unlink(missing_ok=True)
        return
    subprocess.run(format_command_parts(command, line), check=True, timeout=timeout, cwd=cwd, env=env)


def speak_macos(line: str, cfg: dict[str, Any]) -> None:
    voice = str(cfg.get("macos_voice") or "Daniel")
    rate = str(cfg.get("macos_rate") or 185)
    subprocess.run(["say", "-v", voice, "-r", rate, line], check=True, timeout=60)


def speak_system(line: str, cfg: dict[str, Any]) -> None:
    system = platform.system()
    rate = cfg.get("system_rate")
    voice = cfg.get("system_voice")
    volume = int(float(cfg.get("volume", 0.7)) * 100)
    parsed_rate = int(float(rate)) if rate is not None else None
    if system == "Darwin":
        cmd = ["say"]
        if voice:
            cmd.extend(["-v", str(voice)])
        if parsed_rate is not None:
            cmd.extend(["-r", str(parsed_rate)])
        cmd.append(line)
        subprocess.run(cmd, check=True, timeout=60)
        return
    if system == "Windows":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            raise RuntimeError("system TTS requires PowerShell on Windows")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Volume={volume}; "
            f"$s.Rate={parsed_rate if parsed_rate is not None else 0}; "
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        subprocess.run([shell, "-NoProfile", "-Command", script], input=line, text=True, check=True, timeout=60)
        return
    for name in ("spd-say", "espeak-ng", "espeak"):
        path = shutil.which(name)
        if not path:
            continue
        if name == "spd-say":
            cmd = [path]
            if voice:
                cmd.extend(["-o", str(voice)])
            if parsed_rate is not None:
                cmd.extend(["-r", str(parsed_rate)])
            cmd.append(line)
        else:
            cmd = [path]
            if voice:
                cmd.extend(["-v", str(voice)])
            if parsed_rate is not None:
                cmd.extend(["-s", str(parsed_rate)])
            cmd.append(line)
        subprocess.run(cmd, check=True, timeout=60)
        return
    raise RuntimeError("system TTS requires spd-say, espeak-ng, or espeak on Linux")


def run_worker() -> int:
    append_log("worker-start")
    update_worker_heartbeat()
    warm_tts_if_configured()
    last_heartbeat = 0.0
    while True:
        now = time.time()
        if now - last_heartbeat >= WORKER_HEARTBEAT_SECONDS:
            update_worker_heartbeat()
            last_heartbeat = now

        job = dequeue_audio_job()
        if not job:
            time.sleep(IDLE_SLEEP_SECONDS)
            continue

        line = str(job.get("jarvis_line") or "").strip()
        phase = str(job.get("phase") or "")
        session_key = str(job.get("session_key") or "")
        enqueued_ts_ms = int(job.get("enqueued_ts_ms") or 0)
        queue_delay_ms = max(0, int(time.time() * 1000) - enqueued_ts_ms) if enqueued_ts_ms else 0
        if not line:
            append_log("job-skip empty-line")
            continue
        append_log(f"job-speak phase={phase} queue_delay_ms={queue_delay_ms} session={session_key} line={line}")
        started = time.perf_counter()
        try:
            speak_line(line)
            append_log(f"job-done phase={phase} duration_ms={(time.perf_counter() - started) * 1000:.0f}")
        except Exception as exc:
            append_log(f"job-error reason={exc.__class__.__name__}")


if __name__ == "__main__":
    raise SystemExit(run_worker())
