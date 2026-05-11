#!/usr/bin/env python3
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from jarvis_line import __version__


CODEX_HOME = Path.home() / ".codex"
HOOKS_DIR = CODEX_HOME / "hooks"
CONFIG_PATH = HOOKS_DIR / "jarvis_line_config.json"
CONFIG_PROFILES_PATH = HOOKS_DIR / "jarvis_line_profiles.json"
LEGACY_CONFIG_PATH = HOOKS_DIR / "kokoro_tts_config.json"
HOOKS_JSON = CODEX_HOME / "hooks.json"
PACKAGE_DIR = Path(__file__).resolve().parent
WATCHER_PATH = PACKAGE_DIR / "watcher.py"
WORKER_PATH = PACKAGE_DIR / "audio_worker.py"
STATE_PATH = HOOKS_DIR / ".jarvis_line_state.json"
QUEUE_PATH = HOOKS_DIR / "jarvis_line_audio_queue.json"
LATEST_PATH = HOOKS_DIR / "jarvis_line_latest_messages.json"
WATCHER_LOG_PATH = HOOKS_DIR / "jarvis_line_watcher.log"
AUDIO_WORKER_LOG_PATH = HOOKS_DIR / "jarvis_line_audio_worker.log"
KOKORO_VENV = CODEX_HOME / "tts" / "kokoro-venv"
KOKORO_PY = KOKORO_VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
KOKORO_MODEL = CODEX_HOME / "tts" / "kokoro-models" / "kokoro-v1.0.onnx"
KOKORO_VOICES = CODEX_HOME / "tts" / "kokoro-models" / "voices-v1.0.bin"


DEFAULT_KOKORO_CONFIG = {
    "tts": "kokoro",
    "speak_mode": "final_only",
    "line_prefixes": ["Jarvis line:"],
    "line_language": "en",
    "max_spoken_chars": 240,
    "quiet_hours": None,
    "quiet_days": [],
    "max_queue_size": 8,
    "dedupe_window_seconds": None,
    "fallback_tts": None,
    "warm_tts": True,
    "warm_tts_text": "Ready.",
    "message_template": "{line}",
    "assistant_name": "Jarvis",
    "speech_enabled": True,
    "update_check_enabled": True,
    "update_check_interval_hours": 24,
    "update_index_url": "https://pypi.org/pypi/jarvis-line/json",
    "update_source": "pypi",
    "update_git_repo": None,
    "update_git_ref": "main",
    "last_update_check_ts": 0,
    "model_path": str(KOKORO_MODEL),
    "voices_path": str(KOKORO_VOICES),
    "voice": "bm_george:70,bm_lewis:30",
    "lang": "en-gb",
    "speed": 1.08,
    "volume": 0.7,
    "play_by_default": True,
    "final_trigger_mode": "notify",
    "playback_mode": "stream",
    "fallback_playback_mode": "tempfile",
    "delete_after_play": True,
    "temp_dir": str(CODEX_HOME / "tts" / "generated"),
}


DEFAULT_MACOS_CONFIG = {
    **DEFAULT_KOKORO_CONFIG,
    "tts": "macos",
    "macos_voice": "Daniel",
    "macos_rate": 185,
}


DEFAULT_SYSTEM_CONFIG = {
    **DEFAULT_KOKORO_CONFIG,
    "tts": "system",
    "system_voice": None,
    "system_rate": None,
}


DEFAULT_COMMAND_CONFIG = {
    **DEFAULT_KOKORO_CONFIG,
    "tts": "command",
    "command_mode": "play",
    "command": [],
    "player": [],
    "command_timeout_seconds": 60,
    "command_output_suffix": ".wav",
    "command_env": {},
    "command_cwd": None,
    "command_retries": 0,
}


COMMON_CONFIG_KEYS = {
    "tts",
    "speak_mode",
    "line_prefixes",
    "line_language",
    "max_spoken_chars",
    "quiet_hours",
    "quiet_days",
    "max_queue_size",
    "dedupe_window_seconds",
    "fallback_tts",
    "warm_tts",
    "warm_tts_text",
    "message_template",
    "assistant_name",
    "speech_enabled",
    "update_check_enabled",
    "update_check_interval_hours",
    "update_index_url",
    "update_source",
    "update_git_repo",
    "update_git_ref",
    "last_update_check_ts",
    "play_by_default",
    "final_trigger_mode",
    "volume",
    "delete_after_play",
    "temp_dir",
}


BACKEND_CAPABILITIES = {
    "kokoro": {
        "supports": COMMON_CONFIG_KEYS | {
            "model_path",
            "voices_path",
            "voice",
            "lang",
            "speed",
            "playback_mode",
            "fallback_playback_mode",
        },
        "unsupported": {"macos_voice", "macos_rate", "system_voice", "system_rate"},
        "description": "Local Kokoro ONNX voice. Supports voice mix, lang, speed, stream/tempfile playback.",
    },
    "macos": {
        "supports": COMMON_CONFIG_KEYS | {"macos_voice", "macos_rate"},
        "unsupported": {
            "model_path",
            "voices_path",
            "voice",
            "lang",
            "speed",
            "playback_mode",
            "fallback_playback_mode",
            "system_voice",
            "system_rate",
        },
        "description": "macOS say fallback. Supports macos_voice and macos_rate; Kokoro model/lang/speed fields are ignored.",
    },
    "system": {
        "supports": COMMON_CONFIG_KEYS | {"system_voice", "system_rate"},
        "unsupported": {
            "model_path",
            "voices_path",
            "voice",
            "lang",
            "speed",
            "playback_mode",
            "fallback_playback_mode",
            "macos_voice",
            "macos_rate",
        },
        "description": "Platform default TTS fallback. Uses say on macOS, PowerShell SpeechSynthesizer on Windows, or spd-say/espeak on Linux.",
    },
    "command": {
        "supports": COMMON_CONFIG_KEYS | {
            "command_mode",
            "command",
            "player",
            "command_timeout_seconds",
            "command_output_suffix",
            "command_env",
            "command_cwd",
            "command_retries",
        },
        "unsupported": {
            "model_path",
            "voices_path",
            "voice",
            "lang",
            "speed",
            "playback_mode",
            "fallback_playback_mode",
            "macos_voice",
            "macos_rate",
            "system_voice",
            "system_rate",
        },
        "description": "Custom command backend. Use placeholders {text}, {text_json}, and {output}. Advanced custom_* and backend_* keys are allowed.",
    },
}


CONFIG_FIELD_HELP = {
    "tts": {"type": "string", "description": "Selected TTS backend.", "values": sorted(BACKEND_CAPABILITIES.keys())},
    "speak_mode": {"type": "string", "description": "When Jarvis Line should speak.", "values": ["final_only", "commentary_and_final", "off"]},
    "line_prefixes": {"type": "array[string]", "description": "Accepted spoken-line prefixes."},
    "line_language": {"type": "string", "description": "Expected language for generated Jarvis lines.", "values": sorted(LANGUAGE_PROFILES.keys()) if "LANGUAGE_PROFILES" in globals() else ["en", "tr", "user"]},
    "max_spoken_chars": {"type": "integer", "description": "Maximum spoken summary length."},
    "quiet_hours": {"type": "string|null", "description": "Optional quiet-hours range, for example 22:00-08:00."},
    "quiet_days": {"type": "array[string]", "description": "Optional days where speech is skipped, for example saturday,sunday."},
    "max_queue_size": {"type": "integer", "description": "Maximum queued audio jobs."},
    "dedupe_window_seconds": {"type": "integer|null", "description": "Override duplicate suppression window."},
    "fallback_tts": {"type": "string|null", "description": "Fallback TTS backend if the selected backend fails.", "values": ["system", "macos", "command", None]},
    "warm_tts": {"type": "boolean", "description": "Preload the selected TTS engine in the audio worker to reduce first-speech delay."},
    "warm_tts_text": {"type": "string", "description": "Short text used for silent Kokoro stream warm-up."},
    "message_template": {"type": "string", "description": "Template for spoken output. Use {line} for the Jarvis line."},
    "assistant_name": {"type": "string", "description": "Assistant/persona name used in generated instructions."},
    "speech_enabled": {"type": "boolean", "description": "Project/user switch for all Jarvis Line speech."},
    "update_check_enabled": {"type": "boolean", "description": "Whether doctor may show update notices."},
    "update_check_interval_hours": {"type": "integer", "description": "Minimum interval between doctor update checks."},
    "update_index_url": {"type": "string", "description": "Package index JSON URL used for update checks."},
    "update_source": {"type": "string", "description": "Default update install source.", "values": ["pypi", "git"]},
    "update_git_repo": {"type": "string|null", "description": "Git repository URL used by git-based updates."},
    "update_git_ref": {"type": "string", "description": "Git ref used by git-based updates."},
    "last_update_check_ts": {"type": "integer", "description": "Last update check unix timestamp."},
    "model_path": {"type": "string", "description": "Kokoro ONNX model path."},
    "voices_path": {"type": "string", "description": "Kokoro voices file path."},
    "voice": {"type": "string", "description": "Kokoro voice or weighted voice mix."},
    "lang": {"type": "string", "description": "Kokoro language code."},
    "speed": {"type": "number", "description": "Kokoro speech speed."},
    "volume": {"type": "number", "description": "Playback volume where supported."},
    "play_by_default": {"type": "boolean", "description": "Play audio unless explicitly disabled."},
    "final_trigger_mode": {"type": "string", "description": "Final response trigger strategy."},
    "playback_mode": {"type": "string", "description": "Kokoro playback mode.", "values": ["stream", "tempfile"]},
    "fallback_playback_mode": {"type": "string", "description": "Kokoro fallback playback mode.", "values": ["tempfile"]},
    "delete_after_play": {"type": "boolean", "description": "Delete generated temporary audio after playback."},
    "temp_dir": {"type": "string", "description": "Temporary/generated audio directory."},
    "system_voice": {"type": "string|null", "description": "Platform system TTS voice, where supported."},
    "system_rate": {"type": "integer|null", "description": "Platform system TTS rate, where supported."},
    "macos_voice": {"type": "string", "description": "macOS say voice name."},
    "macos_rate": {"type": "integer", "description": "macOS say speech rate."},
    "command_mode": {"type": "string", "description": "Custom command mode.", "values": ["play", "file"]},
    "command": {"type": "string|array[string]", "description": "Custom TTS command."},
    "player": {"type": "string|array[string]", "description": "Player command for file mode."},
    "command_timeout_seconds": {"type": "number", "description": "Custom command timeout."},
    "command_output_suffix": {"type": "string", "description": "Output suffix for command file mode."},
    "command_env": {"type": "object", "description": "Extra environment variables for custom command backend."},
    "command_cwd": {"type": "string|null", "description": "Working directory for custom command backend."},
    "command_retries": {"type": "integer", "description": "Retry count for custom command failures."},
}


LANGUAGE_PROFILES = {
    "en": {
        "instruction_language": "en",
        "recommended_tts": "kokoro",
        "kokoro_lang": "en-gb",
        "note": "English Jarvis line with Kokoro English voice.",
    },
    "user": {
        "instruction_language": "user",
        "recommended_tts": None,
        "kokoro_lang": None,
        "note": "Agent follows user language. Choose a TTS backend that supports the languages your users use.",
    },
    "tr": {
        "instruction_language": "tr",
        "recommended_tts": "command",
        "kokoro_lang": None,
        "note": "Turkish is not supported by the current Kokoro ONNX language list; use command/Edge/OpenAI/custom TTS.",
    },
}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_effective_config(default=None) -> dict[str, Any]:
    default = DEFAULT_KOKORO_CONFIG if default is None else default
    primary = load_json(CONFIG_PATH, None)
    if isinstance(primary, dict):
        return primary
    legacy = load_json(LEGACY_CONFIG_PATH, None)
    if isinstance(legacy, dict):
        return {**default, **legacy}
    return dict(default)


def print_check(ok: bool, label: str, detail: str = "") -> None:
    status = "OK" if ok else "WARN"
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")


def print_next(message: str) -> None:
    print(f"Next: {message}")


SECRET_KEYWORDS = ("key", "token", "secret", "password", "authorization", "api")


def redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(word in lowered for word in SECRET_KEYWORDS):
        return "[REDACTED]"
    if isinstance(value, str):
        home = str(Path.home())
        value = value.replace(home, "~")
        if len(value) > 500:
            return value[:500] + "…"
    if isinstance(value, list):
        return [redact_value(key, item) for item in value[:20]]
    if isinstance(value, dict):
        return redact_dict(value)
    return value


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: redact_value(key, value) for key, value in data.items()}


def redact_log_line(line: str) -> str:
    home = str(Path.home())
    line = line.replace(home, "~")
    if " line=" in line:
        prefix, _, rest = line.partition(" line=")
        preview = rest[:80] + ("…" if len(rest) > 80 else "")
        return f"{prefix} line={preview}"
    return line[:500] + ("…" if len(line) > 500 else "")


def tail_lines(path: Path, limit: int = 80) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    except Exception:
        return []


def read_log_for_bundle(path: Path, full: bool = False, max_bytes: int = 5_000_000) -> tuple[list[str], dict[str, Any]]:
    meta = {"path": str(path).replace(str(Path.home()), "~"), "exists": path.exists(), "truncated": False}
    if not path.exists():
        return [], meta
    if not full:
        lines = tail_lines(path)
        meta["mode"] = "tail"
        meta["lines"] = len(lines)
        return lines, meta
    try:
        size = path.stat().st_size
        meta["mode"] = "full"
        meta["size_bytes"] = size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(max(0, size - max_bytes))
                meta["truncated"] = True
                meta["included_bytes"] = max_bytes
            else:
                meta["included_bytes"] = size
            text = f.read().decode("utf-8", errors="ignore")
        return text.splitlines(), meta
    except Exception as exc:
        meta["error"] = exc.__class__.__name__
        return [], meta


def parse_since_seconds(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip().lower()
    try:
        if text.endswith("h"):
            return int(float(text[:-1]) * 3600)
        if text.endswith("m"):
            return int(float(text[:-1]) * 60)
        if text.endswith("s"):
            return int(float(text[:-1]))
        return int(float(text))
    except Exception:
        return None


def filter_lines_since(lines: list[str], seconds: int | None) -> list[str]:
    if not seconds:
        return lines
    cutoff = int(time.time()) - seconds
    kept = []
    for line in lines:
        first = str(line).split(maxsplit=1)[0] if line else ""
        try:
            if int(first) >= cutoff:
                kept.append(line)
        except Exception:
            kept.append(line)
    return kept


def selected_backend(cfg: dict[str, Any]) -> str:
    return str(cfg.get("tts") or "kokoro")


def unsupported_config_keys(cfg: dict[str, Any]) -> list[str]:
    backend = selected_backend(cfg)
    caps = BACKEND_CAPABILITIES.get(backend)
    if not caps:
        return []
    unsupported = set(caps["unsupported"])
    return sorted(key for key in cfg.keys() if key in unsupported)


def validate_config(cfg: dict[str, Any]) -> list[str]:
    backend = selected_backend(cfg)
    warnings = []
    if backend not in BACKEND_CAPABILITIES:
        warnings.append(f"unknown tts backend: {backend}")
        return warnings
    for key in unsupported_config_keys(cfg):
        warnings.append(f"{key} is ignored by {backend}")
    if backend == "kokoro":
        lang = str(cfg.get("lang") or "")
        if lang and lang not in ("en-us", "en-gb", "fr-fr", "it", "ja", "cmn"):
            warnings.append(f"kokoro lang {lang!r} is not in supported language list")
    line_language = str(cfg.get("line_language") or "en")
    if line_language == "tr" and backend == "kokoro":
        warnings.append("line_language is Turkish but kokoro does not support Turkish; use command/Edge/OpenAI/custom TTS")
    if line_language == "user" and backend == "kokoro":
        warnings.append("line_language follows the user, but kokoro only supports configured Kokoro languages")
    if line_language == "en" and backend == "kokoro" and str(cfg.get("lang") or "") not in ("en-us", "en-gb"):
        warnings.append("line_language is English but kokoro lang is not en-us/en-gb")
    return warnings


def version_key(version: str) -> tuple[int, int, int, int, int]:
    text = str(version or "0").strip().lstrip("v")
    pre_rank = 9
    pre_num = 0
    for marker, rank in (("a", 0), ("b", 1), ("rc", 2)):
        if marker in text:
            base, _, rest = text.partition(marker)
            text = base
            pre_rank = rank
            try:
                pre_num = int(rest.split(".")[0] or 0)
            except Exception:
                pre_num = 0
            break
    parts = []
    for part in text.split(".")[:3]:
        try:
            parts.append(int("".join(ch for ch in part if ch.isdigit()) or 0))
        except Exception:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2], pre_rank, pre_num)


def is_newer_version(latest: str, current: str = __version__) -> bool:
    return version_key(latest) > version_key(current)


def fetch_latest_version(index_url: str, timeout: float = 5.0) -> str | None:
    try:
        req = urllib.request.Request(index_url, headers={"User-Agent": f"jarvis-line/{__version__}"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        version = ((data.get("info") or {}) if isinstance(data, dict) else {}).get("version")
        return str(version) if version else None
    except Exception:
        return None


def update_check(args) -> int:
    cfg = load_effective_config()
    index_url = str(getattr(args, "index_url", None) or cfg.get("update_index_url") or DEFAULT_KOKORO_CONFIG["update_index_url"])
    latest = fetch_latest_version(index_url)
    if not latest:
        print("Could not check for updates.")
        print_next("check your network or set `update_index_url` to a reachable package index.")
        return 1
    print("Current version:", __version__)
    print("Latest version:", latest)
    cfg["last_update_check_ts"] = int(time.time())
    save_json(CONFIG_PATH, cfg)
    if is_newer_version(latest):
        print("Update available.")
        print_next("run `jarvis-line update install`.")
        return 10
    print("Jarvis Line is up to date.")
    return 0


def update_install(args) -> int:
    cfg = load_effective_config()
    source = getattr(args, "source", None) or cfg.get("update_source") or "pypi"
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if source == "pypi" and getattr(args, "pre", False):
        cmd.append("--pre")
    if source == "git":
        repo = getattr(args, "repo", None) or cfg.get("update_git_repo")
        ref = getattr(args, "ref", None) or cfg.get("update_git_ref") or "main"
        if not repo:
            print("Git update requires --repo or config key update_git_repo.")
            print_next("set it with `jarvis-line update configure --source git --git-repo <url> --git-ref main`.")
            return 1
        package = f"git+{repo}@{ref}"
    else:
        package = getattr(args, "package", None) or "jarvis-line"
    cmd.append(package)
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode == 0:
        print_next("run `jarvis-line --version` and `jarvis-line doctor`.")
    return proc.returncode


def update_configure(args) -> int:
    cfg = load_effective_config()
    enabled = getattr(args, "enabled", None)
    interval_hours = getattr(args, "interval_hours", None)
    index_url = getattr(args, "index_url", None)
    source = getattr(args, "source", None)
    git_repo = getattr(args, "git_repo", None)
    git_ref = getattr(args, "git_ref", None)
    if enabled is not None:
        cfg["update_check_enabled"] = enabled == "true"
    if interval_hours is not None:
        cfg["update_check_interval_hours"] = interval_hours
    if index_url:
        cfg["update_index_url"] = index_url
    if source:
        cfg["update_source"] = source
    if git_repo:
        cfg["update_git_repo"] = git_repo
    if git_ref:
        cfg["update_git_ref"] = git_ref
    save_json(CONFIG_PATH, cfg)
    print("Updated update-check settings.")
    return 0


def maybe_print_update_notice(cfg: dict[str, Any]) -> None:
    if cfg.get("update_check_enabled") is False:
        return
    interval = int(cfg.get("update_check_interval_hours") or 24) * 3600
    last = int(cfg.get("last_update_check_ts") or 0)
    if time.time() - last < interval:
        return
    latest = fetch_latest_version(str(cfg.get("update_index_url") or DEFAULT_KOKORO_CONFIG["update_index_url"]), timeout=2.0)
    if not latest:
        return
    cfg["last_update_check_ts"] = int(time.time())
    save_json(CONFIG_PATH, cfg)
    if is_newer_version(latest):
        print(f"[WARN] update available - current={__version__} latest={latest}")
        print_next("run `jarvis-line update install`.")


def sync_language_config(language: str, apply_tts: bool = False) -> None:
    profile = LANGUAGE_PROFILES.get(language, LANGUAGE_PROFILES["en"])
    cfg = load_effective_config()
    cfg["line_language"] = language
    if language == "en" and selected_backend(cfg) == "kokoro":
        cfg["lang"] = profile["kokoro_lang"]
    if apply_tts and profile.get("recommended_tts"):
        recommended = str(profile["recommended_tts"])
        if recommended == "kokoro":
            cfg = config_for_preset("kokoro", cfg)
            cfg["line_language"] = language
            cfg["lang"] = profile["kokoro_lang"]
        elif recommended == "command":
            cfg = config_for_preset("command", cfg)
            cfg["line_language"] = language
    save_json(CONFIG_PATH, cfg)


def config_for_preset(preset: str, current: dict[str, Any]) -> dict[str, Any]:
    if preset == "kokoro":
        cfg = {**DEFAULT_KOKORO_CONFIG, **current, "tts": "kokoro"}
        for key in BACKEND_CAPABILITIES["kokoro"]["unsupported"]:
            cfg.pop(key, None)
        return cfg
    if preset == "macos":
        cfg = {**DEFAULT_MACOS_CONFIG, **current, "tts": "macos"}
        for key in BACKEND_CAPABILITIES["macos"]["unsupported"]:
            cfg.pop(key, None)
        cfg.setdefault("macos_voice", DEFAULT_MACOS_CONFIG["macos_voice"])
        cfg.setdefault("macos_rate", DEFAULT_MACOS_CONFIG["macos_rate"])
        return cfg
    if preset == "system":
        cfg = {**DEFAULT_SYSTEM_CONFIG, **current, "tts": "system"}
        for key in BACKEND_CAPABILITIES["system"]["unsupported"]:
            cfg.pop(key, None)
        cfg.setdefault("system_voice", DEFAULT_SYSTEM_CONFIG["system_voice"])
        cfg.setdefault("system_rate", DEFAULT_SYSTEM_CONFIG["system_rate"])
        return cfg
    if preset == "command":
        cfg = {**DEFAULT_COMMAND_CONFIG, **current, "tts": "command"}
        for key in BACKEND_CAPABILITIES["command"]["unsupported"]:
            cfg.pop(key, None)
        cfg.setdefault("command", DEFAULT_COMMAND_CONFIG["command"])
        cfg.setdefault("command_mode", DEFAULT_COMMAND_CONFIG["command_mode"])
        return cfg
    raise ValueError(f"Unknown preset: {preset}")


def kokoro_model_paths() -> tuple[Path, Path]:
    cfg = load_effective_config()
    model = Path(str(cfg.get("model_path") or KOKORO_MODEL)).expanduser()
    voices = Path(str(cfg.get("voices_path") or KOKORO_VOICES)).expanduser()
    return model, voices


def kokoro_ready() -> tuple[bool, str]:
    model_path, voices_path = kokoro_model_paths()
    if not KOKORO_PY.exists():
        return False, "kokoro venv python missing"
    if not model_path.exists():
        return False, "kokoro model missing"
    if not voices_path.exists():
        return False, "kokoro voices missing"
    try:
        subprocess.run(
            [str(KOKORO_PY), "-c", "import kokoro_onnx, sounddevice, soundfile, numpy"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=True,
        )
    except Exception:
        return False, "kokoro python dependencies missing"
    return True, "ready"


def kokoro_status(_args) -> int:
    model_path, voices_path = kokoro_model_paths()
    ready, reason = kokoro_ready()
    print("Kokoro status")
    print_check(KOKORO_PY.exists(), "venv python", str(KOKORO_PY))
    print_check(model_path.exists(), "model", str(model_path))
    print_check(voices_path.exists(), "voices", str(voices_path))
    print_check(ready, "dependencies", reason)
    if ready:
        print_next("run `jarvis-line tts use kokoro` or `jarvis-line tts test`.")
    else:
        print_next("run `jarvis-line kokoro install-deps`, add model files, or use `jarvis-line tts use system`.")
    return 0 if ready else 1


def kokoro_install_deps(_args) -> int:
    KOKORO_VENV.parent.mkdir(parents=True, exist_ok=True)
    if not KOKORO_PY.exists():
        subprocess.run([sys.executable, "-m", "venv", str(KOKORO_VENV)], check=True)
    subprocess.run(
        [
            str(KOKORO_PY),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "kokoro-onnx",
            "sounddevice",
            "soundfile",
            "numpy",
        ],
        check=True,
    )
    print("Installed Kokoro Python dependencies into:", KOKORO_VENV)
    print("Model path expected:", KOKORO_MODEL)
    print("Voices path expected:", KOKORO_VOICES)
    print_next("place model files there, or run `jarvis-line kokoro configure --model-path ... --voices-path ...`.")
    return kokoro_status(argparse.Namespace())


def kokoro_configure(args) -> int:
    cfg = config_for_preset("kokoro", load_effective_config())
    if args.model_path:
        cfg["model_path"] = str(Path(args.model_path).expanduser())
    if args.voices_path:
        cfg["voices_path"] = str(Path(args.voices_path).expanduser())
    if args.voice:
        cfg["voice"] = args.voice
    if args.lang:
        cfg["lang"] = args.lang
    save_json(CONFIG_PATH, cfg)
    print("Configured Kokoro paths in:", CONFIG_PATH)
    warnings = validate_config(cfg)
    if warnings:
        print("Config warnings:")
        for warning in warnings:
            print(f"- {warning}")
    print_next("run `jarvis-line kokoro status`, then `jarvis-line tts use kokoro`.")
    return 0


def linux_player_ready() -> tuple[bool, str]:
    players = [name for name in ("paplay", "aplay", "ffplay") if shutil.which(name)]
    if players:
        return True, ", ".join(players)
    return False, "install paplay, aplay, or ffplay for tempfile fallback"


def system_tts_ready() -> tuple[bool, str]:
    system = platform.system()
    if system == "Darwin":
        return (True, "say") if shutil.which("say") else (False, "macOS say missing")
    if system == "Windows":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        return (True, Path(shell).name) if shell else (False, "PowerShell missing")
    if system == "Linux":
        engines = [name for name in ("spd-say", "espeak-ng", "espeak") if shutil.which(name)]
        if engines:
            return True, ", ".join(engines)
        return False, "install spd-say, espeak-ng, or espeak"
    return False, f"no built-in system TTS preset for {system or 'unknown platform'}"


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def process_lines() -> list[str]:
    if platform.system() == "Windows":
        commands = [
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


def normalized_path_text(value: object) -> str:
    return str(value).replace("\\", "/")


def find_runtime_pids(kind: str) -> list[int]:
    pids = []
    this_pid = os.getpid()
    if kind == "watcher":
        markers = (
            "jarvis_line/watcher.py --watch-sessions",
            "jarvis_line.watcher --watch-sessions",
        )
    else:
        markers = (
            "jarvis_line/audio_worker.py",
            "jarvis_line.audio_worker",
        )
    codex_home = normalized_path_text(CODEX_HOME)
    kokoro_venv = normalized_path_text(KOKORO_VENV)
    for line in process_lines():
        normalized_line = normalized_path_text(line)
        if not any(marker in normalized_line for marker in markers):
            continue
        if codex_home not in normalized_line and kokoro_venv not in normalized_line:
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


def terminate_pid(pid: int) -> None:
    if not pid:
        return
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def watcher_command() -> list[str]:
    py = KOKORO_PY if KOKORO_PY.exists() else Path(sys.executable)
    return [str(py), "-m", "jarvis_line.watcher", "--launch"]


def hook_command_string() -> str:
    return " ".join(watcher_command())


def is_jarvis_hook_command(command: str) -> bool:
    return any(marker in command for marker in (
        "jarvis_line_watcher.py",
        "jarvis_line.watcher",
        "jarvis-line",
    ))


def launch_runtime(args, selected: str) -> int:
    if not WATCHER_PATH.exists() or not WORKER_PATH.exists():
        print("Jarvis Line hook scripts are missing.")
        return 1

    proc = subprocess.run(watcher_command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
    print(f"Selected TTS: {selected}")
    print("Config written:", CONFIG_PATH)
    print("Watcher launch:", "OK" if proc.returncode == 0 else f"FAILED ({proc.returncode})")
    if proc.stderr.strip():
        print(proc.stderr.strip())
    if getattr(args, "test", False):
        return tts_test(argparse.Namespace(text="Jarvis line setup is ready."))
    return 0 if proc.returncode == 0 else proc.returncode


def setup_default(args) -> int:
    ready, reason = kokoro_ready()
    if ready:
        cfg = config_for_preset("kokoro", load_effective_config({}))
        save_json(CONFIG_PATH, cfg)
        selected = "kokoro"
    else:
        system_ready, system_reason = system_tts_ready()
        if not system_ready:
            print(f"[WARN] Kokoro is not ready: {reason}")
            print(f"[WARN] System TTS fallback is not ready: {system_reason}")
            print_next("install Kokoro with `jarvis-line kokoro install-deps`, or configure `jarvis-line tts use command --command ...`.")
            return 1
        print(f"[WARN] Kokoro is not ready: {reason}")
        print("Kokoro is the recommended default voice. Falling back to system TTS for now.")
        print_next("keep system TTS, or install Kokoro and run `jarvis-line tts use kokoro`.")
        cfg = config_for_preset("system", load_effective_config({}))
        save_json(CONFIG_PATH, cfg)
        selected = "system"

    return launch_runtime(args, selected)


def init_project(args) -> int:
    setup_rc = setup_default(argparse.Namespace(test=getattr(args, "test", False)))
    if setup_rc != 0:
        return setup_rc

    if not getattr(args, "no_hook", False):
        hook_rc = install_codex(argparse.Namespace())
        if hook_rc != 0:
            return hook_rc

    if not getattr(args, "no_instructions", False):
        instruction_rc = instructions_install(argparse.Namespace(
            target=getattr(args, "target", "agents"),
            language=getattr(args, "language", "en"),
            path=getattr(args, "path", None),
            sync_config=True,
            apply_tts=getattr(args, "apply_tts", False),
        ))
        if instruction_rc != 0:
            return instruction_rc

    print("Jarvis Line init complete.")
    print_next("run `jarvis-line doctor` to verify the install, or start using your agent.")
    return 0


def tts_use(args) -> int:
    preset = args.preset
    current = load_effective_config()
    if preset == "kokoro":
        ready, reason = kokoro_ready()
        if not ready:
            print(f"Kokoro is not ready: {reason}")
            print_next("run `jarvis-line kokoro status` for details, or use `jarvis-line tts use system`.")
            return 1
        cfg = config_for_preset("kokoro", current)
    elif preset == "macos":
        if platform.system() != "Darwin" or not shutil.which("say"):
            print("macOS say is not available on this system.")
            return 1
        cfg = config_for_preset("macos", current)
    elif preset == "system":
        ready, reason = system_tts_ready()
        if not ready:
            print(f"System TTS is not ready: {reason}")
            print_next("install a platform TTS tool or use `jarvis-line tts use command --command ...`.")
            return 1
        cfg = config_for_preset("system", current)
    elif preset == "command":
        cfg = config_for_preset("command", current)
        if args.command:
            cfg["command"] = args.command
        if args.player:
            cfg["player"] = args.player
        if args.mode:
            cfg["command_mode"] = args.mode
        if not cfg.get("command"):
            print("Command backend requires --command, or set command later with config set.")
            print_next("try `jarvis-line tts use command --command 'my-tts --text {text_json}'`.")
            return 1
    else:
        print(f"Unknown preset: {preset}")
        return 1
    save_json(CONFIG_PATH, cfg)
    print(f"Selected TTS: {preset}")
    print_next("run `jarvis-line tts test` to hear a sample.")
    return 0


def tts_test(args) -> int:
    cfg = load_effective_config()
    text = args.text or "Jarvis line test is ready."
    backend = str(cfg.get("tts") or "kokoro")
    if backend == "macos":
        voice = str(cfg.get("macos_voice") or "Daniel")
        rate = str(cfg.get("macos_rate") or 185)
        proc = subprocess.run(["say", "-v", voice, "-r", rate, text], timeout=20)
        return proc.returncode
    if backend == "system":
        proc = subprocess.run(
            [sys.executable, "-c", (
                "import json, sys; "
                "from jarvis_line.audio_worker import speak_system; "
                "speak_system(sys.argv[1], json.loads(sys.argv[2]))"
            ), text, json.dumps(cfg, ensure_ascii=False)],
            timeout=60,
        )
        return proc.returncode
    if backend == "command":
        command = cfg.get("command")
        if not command:
            print("Command backend has no command configured.")
            return 1
        import shlex
        parts = command if isinstance(command, list) else shlex.split(str(command))
        parts = [str(part).replace("{text}", text).replace("{text_json}", json.dumps(text, ensure_ascii=False)) for part in parts]
        proc = subprocess.run(parts, timeout=float(cfg.get("command_timeout_seconds") or 60))
        return proc.returncode
    proc = subprocess.run([str(KOKORO_PY), "-m", "jarvis_line.kokoro_say", "--text", text, "--play"], timeout=60)
    return proc.returncode


def doctor(_args) -> int:
    cfg = load_effective_config({})
    state = load_json(STATE_PATH, {})
    watcher = state.get("__watcher__", {}) if isinstance(state, dict) else {}
    worker = state.get("__audio_worker__", {}) if isinstance(state, dict) else {}
    ready, reason = kokoro_ready()
    system_ready, system_reason = system_tts_ready()
    watcher_ok = pid_alive(int(watcher.get("pid") or 0))
    worker_ok = pid_alive(int(worker.get("pid") or 0))
    warnings = validate_config(cfg)
    if getattr(_args, "json_output", False):
        print(json.dumps({
            "config": CONFIG_PATH.exists(),
            "hooks_json": HOOKS_JSON.exists(),
            "watcher_script": WATCHER_PATH.exists(),
            "audio_worker_script": WORKER_PATH.exists(),
            "kokoro": {"ok": ready, "detail": reason},
            "system_tts": {"ok": system_ready, "detail": system_reason},
            "watcher": {"ok": watcher_ok, "pid": watcher.get("pid")},
            "audio_worker": {"ok": worker_ok, "pid": worker.get("pid")},
            "queue": QUEUE_PATH.exists(),
            "latest_cache": LATEST_PATH.exists(),
            "selected_tts": selected_backend(cfg),
            "warnings": warnings,
        }, ensure_ascii=False, indent=2))
        return 0
    print("Jarvis Line doctor")
    print_check(CONFIG_PATH.exists(), "config", str(CONFIG_PATH))
    print_check(HOOKS_JSON.exists(), "Codex hooks.json", str(HOOKS_JSON))
    print_check(WATCHER_PATH.exists(), "watcher script", str(WATCHER_PATH))
    print_check(WORKER_PATH.exists(), "audio worker script", str(WORKER_PATH))
    print_check(ready, "kokoro", reason)
    print_check(system_ready, "system TTS fallback", system_reason)
    system = platform.system()
    print_check(system == "Darwin" and bool(shutil.which("say")), "macOS say fallback")
    if system == "Linux":
        linux_ok, linux_detail = linux_player_ready()
        print_check(linux_ok, "Linux tempfile player", linux_detail)
    if getattr(_args, "fix", False) and (not watcher_ok or not worker_ok):
        subprocess.run(watcher_command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        state = load_json(STATE_PATH, {})
        watcher = state.get("__watcher__", {}) if isinstance(state, dict) else {}
        worker = state.get("__audio_worker__", {}) if isinstance(state, dict) else {}
        watcher_ok = pid_alive(int(watcher.get("pid") or 0))
        worker_ok = pid_alive(int(worker.get("pid") or 0))
    print_check(watcher_ok, "watcher process", f"pid={watcher.get('pid')}")
    print_check(worker_ok, "audio worker process", f"pid={worker.get('pid')}")
    print_check(QUEUE_PATH.exists(), "audio queue", str(QUEUE_PATH))
    print_check(LATEST_PATH.exists(), "latest message cache", str(LATEST_PATH))
    print("Selected TTS:", selected_backend(cfg))
    if warnings:
        print("Config warnings:")
        for warning in warnings:
            print(f"- {warning}")
        print_next("fix warnings with `jarvis-line config set ...` or switch TTS presets.")
    elif not watcher_ok or not worker_ok:
        print_next("run `jarvis-line doctor --fix` to restart the runtime.")
    else:
        print_next("Jarvis Line is healthy. Use `jarvis-line tts test` to test speech.")
    maybe_print_update_notice(cfg)
    return 0


def status(_args) -> int:
    cfg = load_effective_config({})
    state = load_json(STATE_PATH, {})
    queue = load_json(QUEUE_PATH, {"jobs": []})
    latest = load_json(LATEST_PATH, {"sessions": {}})
    watcher = state.get("__watcher__", {}) if isinstance(state, dict) else {}
    worker = state.get("__audio_worker__", {}) if isinstance(state, dict) else {}
    print("Jarvis Line status")
    print("tts:", selected_backend(cfg))
    print("watcher:", "running" if pid_alive(int(watcher.get("pid") or 0)) else "stopped", watcher.get("pid"))
    print("audio_worker:", "running" if pid_alive(int(worker.get("pid") or 0)) else "stopped", worker.get("pid"))
    print("queue_jobs:", len(queue.get("jobs") or []))
    print("cached_sessions:", len((latest.get("sessions") or {})))
    print("speak_mode:", cfg.get("speak_mode", "final_only"))
    return 0


def runtime_start(args) -> int:
    return launch_runtime(argparse.Namespace(test=getattr(args, "test", False)), selected_backend(load_effective_config({})))


def runtime_stop(_args) -> int:
    state = load_json(STATE_PATH, {})
    watcher = state.get("__watcher__", {}) if isinstance(state, dict) else {}
    worker = state.get("__audio_worker__", {}) if isinstance(state, dict) else {}
    pids = {
        int(watcher.get("pid") or 0),
        int(worker.get("pid") or 0),
        *find_runtime_pids("watcher"),
        *find_runtime_pids("audio_worker"),
    }
    for pid in pids:
        terminate_pid(pid)
    print("Stopped Jarvis Line runtime.")
    print_next("run `jarvis-line start` to start it again.")
    return 0


def runtime_restart(args) -> int:
    runtime_stop(argparse.Namespace())
    time.sleep(0.5)
    return runtime_start(args)


def queue_status(_args) -> int:
    queue = load_json(QUEUE_PATH, {"jobs": []})
    jobs = queue.get("jobs") or []
    print("Jarvis Line queue")
    print("jobs:", len(jobs))
    for job in jobs:
        print(f"- {job.get('phase')} {job.get('message_id')} {str(job.get('jarvis_line') or '')[:80]}")
    return 0


def queue_clear(_args) -> int:
    save_json(QUEUE_PATH, {"jobs": [], "updated_ts_ms": int(time.time() * 1000)})
    print("Cleared Jarvis Line queue.")
    return 0


def logs_tail(args) -> int:
    lines = int(getattr(args, "lines", 80) or 80)
    paths = [WATCHER_LOG_PATH, AUDIO_WORKER_LOG_PATH] if args.target == "all" else [WATCHER_LOG_PATH if args.target == "watcher" else AUDIO_WORKER_LOG_PATH]
    for path in paths:
        print(f"==> {path} <==")
        for line in tail_lines(path, lines):
            print(redact_log_line(line))
    return 0


def support_bundle(args) -> int:
    output = Path(args.output or Path.cwd() / f"jarvis-line-support-{int(time.time())}.zip")
    full_logs = bool(getattr(args, "full", False))
    since_seconds = parse_since_seconds(getattr(args, "since", None))
    max_log_bytes = int(getattr(args, "max_log_bytes", 5_000_000) or 5_000_000)
    cfg = redact_dict(load_effective_config({}))
    state = redact_dict(load_json(STATE_PATH, {}))
    queue = load_json(QUEUE_PATH, {"jobs": []})
    latest = load_json(LATEST_PATH, {"sessions": {}})
    summary = {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": sys.version.split()[0],
        },
        "paths": {
            "config": str(CONFIG_PATH).replace(str(Path.home()), "~"),
            "legacy_config": str(LEGACY_CONFIG_PATH).replace(str(Path.home()), "~"),
            "hooks_json": str(HOOKS_JSON).replace(str(Path.home()), "~"),
        },
        "selected_tts": selected_backend(cfg),
        "queue_jobs": len(queue.get("jobs") or []),
        "cached_sessions": len((latest.get("sessions") or {})),
        "config_warnings": validate_config(load_effective_config({})),
        "bundle": {
            "full_logs": full_logs,
            "max_log_bytes": max_log_bytes,
            "since": getattr(args, "since", None),
        },
    }
    queue_summary = {
        "jobs": [
            {
                "message_id": job.get("message_id"),
                "session_key": str(job.get("session_key") or "").replace(str(Path.home()), "~"),
                "phase": job.get("phase"),
                "enqueued_ts_ms": job.get("enqueued_ts_ms"),
                "jarvis_line_preview": str(job.get("jarvis_line") or "")[:80],
            }
            for job in (queue.get("jobs") or [])
        ]
    }
    latest_summary = {
        "sessions": {
            str(key).replace(str(Path.home()), "~"): {
                "latest_phase": (value.get("latest") or {}).get("phase"),
                "latest_final_id": (value.get("latest_final") or {}).get("message_id"),
                "latest_final_preview": str((value.get("latest_final") or {}).get("jarvis_line") or "")[:80],
            }
            for key, value in (latest.get("sessions") or {}).items()
            if isinstance(value, dict)
        }
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    watcher_lines, watcher_meta = read_log_for_bundle(WATCHER_LOG_PATH, full=full_logs, max_bytes=max_log_bytes)
    worker_lines, worker_meta = read_log_for_bundle(AUDIO_WORKER_LOG_PATH, full=full_logs, max_bytes=max_log_bytes)
    watcher_lines = filter_lines_since(watcher_lines, since_seconds)
    worker_lines = filter_lines_since(worker_lines, since_seconds)
    summary["logs"] = {
        "watcher": watcher_meta,
        "audio_worker": worker_meta,
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        bundle.writestr("config.redacted.json", json.dumps(cfg, ensure_ascii=False, indent=2))
        if getattr(args, "include_config_full", False):
            bundle.writestr("config.full.redacted.json", json.dumps(redact_dict(load_effective_config({})), ensure_ascii=False, indent=2))
        bundle.writestr("state.redacted.json", json.dumps(state, ensure_ascii=False, indent=2))
        bundle.writestr("queue.summary.json", json.dumps(queue_summary, ensure_ascii=False, indent=2))
        bundle.writestr("latest.summary.json", json.dumps(latest_summary, ensure_ascii=False, indent=2))
        bundle.writestr(
            "watcher.log.tail.txt",
            "\n".join(redact_log_line(line) for line in watcher_lines),
        )
        bundle.writestr(
            "audio_worker.log.tail.txt",
            "\n".join(redact_log_line(line) for line in worker_lines),
        )
    print("Wrote support bundle:", output)
    print_next("attach this zip to your issue instead of pasting raw logs.")
    return 0


def install_codex(_args) -> int:
    hooks = load_json(HOOKS_JSON, {"hooks": {}})
    hooks.setdefault("hooks", {})
    session_hooks = hooks["hooks"].setdefault("SessionStart", [])
    command = hook_command_string()
    for entry in session_hooks:
        for hook in entry.get("hooks", []):
            if is_jarvis_hook_command(str(hook.get("command", ""))):
                hook["command"] = command
                print("Codex hook already installed.")
                save_json(HOOKS_JSON, hooks)
                return 0
    backup = HOOKS_JSON.with_suffix(".json.jarvis-line.bak")
    if HOOKS_JSON.exists() and not backup.exists():
        backup.write_text(HOOKS_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    session_hooks.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": command, "timeout": 30}],
    })
    save_json(HOOKS_JSON, hooks)
    print("Installed Codex SessionStart hook.")
    return 0


def uninstall_codex(_args) -> int:
    hooks = load_json(HOOKS_JSON, {"hooks": {}})
    removed = 0
    events = hooks.get("hooks", {})
    for event_name, entries in list(events.items()):
        kept_entries = []
        for entry in entries:
            kept_hooks = []
            for hook in entry.get("hooks", []):
                command = str(hook.get("command", ""))
                if is_jarvis_hook_command(command):
                    removed += 1
                    continue
                kept_hooks.append(hook)
            if kept_hooks:
                entry["hooks"] = kept_hooks
                kept_entries.append(entry)
        if kept_entries:
            events[event_name] = kept_entries
        else:
            events.pop(event_name, None)
    save_json(HOOKS_JSON, hooks)
    print(f"Removed {removed} Codex hook(s).")
    return 0


def migrate_config(args) -> int:
    current = load_json(LEGACY_CONFIG_PATH, {})
    if not current:
        current = load_json(CONFIG_PATH, {})
    if not current:
        current = DEFAULT_KOKORO_CONFIG.copy()
    migrated = {**DEFAULT_KOKORO_CONFIG, **current}
    migrated.setdefault("config_version", 1)
    save_json(CONFIG_PATH, migrated)
    if getattr(args, "remove_legacy", False) and LEGACY_CONFIG_PATH.exists():
        backup = LEGACY_CONFIG_PATH.with_suffix(".json.migrated.bak")
        if not backup.exists():
            backup.write_text(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        LEGACY_CONFIG_PATH.unlink()
    print("Wrote migrated config:", CONFIG_PATH)
    return 0


def tts_capabilities(args) -> int:
    names = [args.preset] if args.preset else sorted(BACKEND_CAPABILITIES.keys())
    for name in names:
        caps = BACKEND_CAPABILITIES.get(name)
        if not caps:
            print(f"Unknown preset: {name}")
            return 1
        print(name)
        print("  " + str(caps["description"]))
        print("  supports: " + ", ".join(sorted(caps["supports"])))
        print("  ignores: " + ", ".join(sorted(caps["unsupported"])))
    return 0


def preset_defaults(preset: str) -> dict[str, Any]:
    if preset == "kokoro":
        return dict(DEFAULT_KOKORO_CONFIG)
    if preset == "system":
        return config_for_preset("system", {})
    if preset == "macos":
        return config_for_preset("macos", {})
    if preset == "command":
        return config_for_preset("command", {})
    raise ValueError(f"Unknown preset: {preset}")


def config_defaults(args) -> int:
    if args.preset:
        print(json.dumps(preset_defaults(args.preset), ensure_ascii=False, indent=2))
        return 0
    defaults = {name: preset_defaults(name) for name in ("kokoro", "system", "macos", "command")}
    print(json.dumps(defaults, ensure_ascii=False, indent=2))
    return 0


def config_schema(args) -> int:
    names = [args.preset] if args.preset else ("kokoro", "system", "macos", "command")
    schema: dict[str, Any] = {}
    for name in names:
        caps = BACKEND_CAPABILITIES[name]
        fields = {}
        for key in sorted(caps["supports"]):
            fields[key] = CONFIG_FIELD_HELP.get(key, {"type": "unknown", "description": "Backend-specific setting."})
        schema[name] = {
            "description": caps["description"],
            "supports": fields,
            "ignores": sorted(caps["unsupported"]),
        }
    print(json.dumps(schema if not args.preset else schema[args.preset], ensure_ascii=False, indent=2))
    return 0


def parse_config_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("none", "null"):
        return None
    if (value.startswith("[") and value.endswith("]")) or (value.startswith("{") and value.endswith("}")):
        try:
            return json.loads(value)
        except Exception:
            pass
    if "," in value:
        return [part.strip() for part in value.split(",") if part.strip()]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def config_get(args) -> int:
    cfg = load_effective_config()
    if args.key:
        print(json.dumps(cfg.get(args.key), ensure_ascii=False))
    else:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


def config_set(args) -> int:
    cfg = load_effective_config()
    backend = selected_backend(cfg)
    caps = BACKEND_CAPABILITIES.get(backend, {})
    supported = set(caps.get("supports", set()))
    custom_allowed = backend == "command" and (args.key.startswith("custom_") or args.key.startswith("backend_"))
    if supported and args.key not in supported and not custom_allowed:
        print(f"{args.key} is not supported by {backend}.")
        print("Use `jarvis-line tts capabilities` to see supported settings.")
        return 1
    cfg[args.key] = parse_config_value(args.value)
    save_json(CONFIG_PATH, cfg)
    print(f"Set {args.key} = {cfg[args.key]!r}")
    return 0


def profile_list(_args) -> int:
    profiles = load_json(CONFIG_PROFILES_PATH, {})
    if not profiles:
        print("No config profiles saved.")
        return 0
    for name in sorted(profiles.keys()):
        cfg = profiles[name]
        print(f"{name}: tts={cfg.get('tts')} speak_mode={cfg.get('speak_mode')}")
    return 0


def profile_save(args) -> int:
    profiles = load_json(CONFIG_PROFILES_PATH, {})
    profiles[args.name] = load_effective_config()
    save_json(CONFIG_PROFILES_PATH, profiles)
    print(f"Saved profile: {args.name}")
    return 0


def profile_use(args) -> int:
    profiles = load_json(CONFIG_PROFILES_PATH, {})
    cfg = profiles.get(args.name)
    if not isinstance(cfg, dict):
        print(f"Profile not found: {args.name}")
        return 1
    save_json(CONFIG_PATH, cfg)
    print(f"Activated profile: {args.name}")
    print_next("run `jarvis-line doctor` or `jarvis-line tts test`.")
    return 0


def profile_delete(args) -> int:
    profiles = load_json(CONFIG_PROFILES_PATH, {})
    if args.name not in profiles:
        print(f"Profile not found: {args.name}")
        return 1
    profiles.pop(args.name, None)
    save_json(CONFIG_PROFILES_PATH, profiles)
    print(f"Deleted profile: {args.name}")
    return 0


def prefix_list(_args) -> int:
    for prefix in load_effective_config().get("line_prefixes") or []:
        print(prefix)
    return 0


def prefix_add(args) -> int:
    cfg = load_effective_config()
    prefixes = cfg.get("line_prefixes") or []
    if isinstance(prefixes, str):
        prefixes = [part.strip() for part in prefixes.split(",") if part.strip()]
    if args.prefix not in prefixes:
        prefixes.append(args.prefix)
    cfg["line_prefixes"] = prefixes
    save_json(CONFIG_PATH, cfg)
    print(f"Added prefix: {args.prefix}")
    return 0


def prefix_remove(args) -> int:
    cfg = load_effective_config()
    prefixes = cfg.get("line_prefixes") or []
    if isinstance(prefixes, str):
        prefixes = [part.strip() for part in prefixes.split(",") if part.strip()]
    cfg["line_prefixes"] = [prefix for prefix in prefixes if prefix != args.prefix]
    save_json(CONFIG_PATH, cfg)
    print(f"Removed prefix: {args.prefix}")
    return 0


def setup_wizard(_args) -> int:
    print("Jarvis Line setup")
    print("1. Kokoro local (recommended default)")
    print("2. System TTS fallback")
    print("3. macOS say")
    print("4. Custom command")
    choice = input("Choose TTS [1]: ").strip() or "1"
    if choice == "2":
        rc = tts_use(argparse.Namespace(preset="system", command=None, player=None, mode=None))
    elif choice == "3":
        rc = tts_use(argparse.Namespace(preset="macos", command=None, player=None, mode=None))
    elif choice == "4":
        command = input("Command, use {text}: ").strip()
        rc = tts_use(argparse.Namespace(preset="command", command=command, player=None, mode="play"))
    else:
        rc = tts_use(argparse.Namespace(preset="kokoro", command=None, player=None, mode=None))
    if rc != 0:
        return rc
    speak_mode = input("Speak mode [final_only/commentary_and_final/off] (final_only): ").strip()
    if speak_mode:
        config_set(argparse.Namespace(key="speak_mode", value=speak_mode))
    prefix = input("Line prefix (Jarvis line:): ").strip()
    if prefix:
        config_set(argparse.Namespace(key="line_prefixes", value=prefix))
    return launch_runtime(argparse.Namespace(test=True), selected_backend(load_effective_config({})))


INSTRUCTION_FILES = {
    "agents": "AGENTS.md",
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
    "gemini": "GEMINI.md",
}


def instruction_snippet(target: str = "agents", language: str = "en", style: str = "strict") -> str:
    if language == "en":
        language_rule = "Any `Jarvis line` must be written in English."
    elif language == "tr":
        language_rule = "Any `Jarvis line` must be written in Turkish."
    else:
        language_rule = "Write any `Jarvis line` in the same language as the user, unless the user asks otherwise."
    if style == "minimal":
        return f"""## Jarvis Line

Every final assistant response must include exactly one short spoken status line:

`Jarvis line: <one short spoken summary>`

Rules:
- {language_rule}
- Keep the Jarvis line short and safe.
- Do not include secrets, private data, raw logs, code, or long file contents.
"""
    return f"""## Jarvis Line

Jarvis Line is enabled for this agent.

Every final assistant response must include exactly one spoken status line using this format:

`Jarvis line: <one short spoken summary>`

Rules:
- {language_rule}
- Include exactly one `Jarvis line: ...` line in every final response.
- You may include an optional `Jarvis line: ...` line in commentary/progress messages.
- Keep each Jarvis line to one short natural sentence.
- Use Jarvis lines only for status, completion, or the next action.
- Do not include secrets, private data, raw logs, code, or long file contents in the Jarvis line.
- Do not start normal messages with phrases like "Jarvis here" or similar persona announcements.
- Keep normal user-facing text in the user's language unless there is a separate reason to switch.
- If the response language differs from the Jarvis line language rule, only the Jarvis line is governed by this section.
- Before sending any final response, verify that it includes exactly one `Jarvis line: ...` line.
"""


def instructions_print(args) -> int:
    if getattr(args, "sync_config", False):
        sync_language_config(args.language, apply_tts=getattr(args, "apply_tts", False))
    print(instruction_snippet(args.target, args.language, getattr(args, "style", "strict")))
    return 0


def replace_jarvis_section(existing: str, snippet: str) -> str:
    marker = "## Jarvis Line"
    start = existing.find(marker)
    if start == -1:
        separator = "\n\n" if existing.strip() else ""
        return existing.rstrip() + separator + snippet + "\n"
    next_start = existing.find("\n## ", start + len(marker))
    if next_start == -1:
        return existing[:start].rstrip() + "\n\n" + snippet + "\n"
    return existing[:start].rstrip() + "\n\n" + snippet + "\n" + existing[next_start:].lstrip("\n")


def instructions_install(args) -> int:
    if getattr(args, "sync_config", True):
        sync_language_config(args.language, apply_tts=getattr(args, "apply_tts", False))
    filename = INSTRUCTION_FILES[args.target]
    path = Path(args.path or Path.cwd() / filename)
    snippet = instruction_snippet(args.target, args.language, getattr(args, "style", "strict"))
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "## Jarvis Line" in existing and not getattr(args, "replace", False):
        print(f"Jarvis Line instructions already exist in {path}")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if getattr(args, "replace", False):
        path.write_text(replace_jarvis_section(existing, snippet), encoding="utf-8")
    else:
        separator = "\n\n" if existing.strip() else ""
        path.write_text(existing.rstrip() + separator + snippet + "\n", encoding="utf-8")
    print(f"Installed Jarvis Line instructions into {path}")
    return 0


def instructions_doctor(args) -> int:
    filename = INSTRUCTION_FILES[args.target]
    path = Path(args.path or Path.cwd() / filename)
    if not path.exists():
        print_check(False, "instruction file", str(path))
        print_next("run `jarvis-line instructions install ...`.")
        return 1
    text = path.read_text(encoding="utf-8")
    has_section = "## Jarvis Line" in text
    has_format = "Jarvis line:" in text
    has_exactly = "exactly one" in text.lower()
    print("Jarvis Line instructions doctor")
    print_check(has_section, "Jarvis Line section", str(path))
    print_check(has_format, "Jarvis line format")
    print_check(has_exactly, "exactly-one rule")
    if has_section and has_format and has_exactly:
        print_next("instructions look ready.")
        return 0
    print_next("run `jarvis-line instructions install --replace`.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="jarvis-line")
    parser.add_argument("--version", action="version", version=f"jarvis-line {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup")
    setup.add_argument("--default", action="store_true", help="Use the recommended low-friction setup.")
    setup.add_argument("--test", action="store_true", help="Play a short test phrase after setup.")
    setup.set_defaults(func=lambda args: setup_default(args) if args.default else setup_wizard(args))

    init = sub.add_parser("init", help="One-command setup for a project.")
    init.add_argument("--language", choices=tuple(LANGUAGE_PROFILES.keys()), default="en")
    init.add_argument("--target", choices=tuple(INSTRUCTION_FILES.keys()), default="agents")
    init.add_argument("--path", help="Instruction file path. Defaults to the target's standard file in the current directory.")
    init.add_argument("--apply-tts", action="store_true", help="Also switch TTS preset when the selected language recommends it.")
    init.add_argument("--no-hook", action="store_true", help="Do not install the Codex hook.")
    init.add_argument("--no-instructions", action="store_true", help="Do not install agent instructions.")
    init.add_argument("--test", action="store_true", help="Play a short test phrase during setup.")
    init.set_defaults(func=init_project)

    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--fix", action="store_true")
    doctor_parser.add_argument("--json", action="store_true", dest="json_output")
    doctor_parser.set_defaults(func=doctor)

    sub.add_parser("status").set_defaults(func=status)

    update = sub.add_parser("update")
    update_sub = update.add_subparsers(dest="update_command", required=True)
    update_check_parser = update_sub.add_parser("check")
    update_check_parser.add_argument("--index-url")
    update_check_parser.set_defaults(func=update_check)
    update_install_parser = update_sub.add_parser("install")
    update_install_parser.add_argument("--source", choices=("pypi", "git"), help="Install from PyPI or a git repository.")
    update_install_parser.add_argument("--pre", action="store_true", help="Allow pre-release versions.")
    update_install_parser.add_argument("--package", help="Package spec to install, defaults to jarvis-line.")
    update_install_parser.add_argument("--repo", help="Git repository URL for --source git.")
    update_install_parser.add_argument("--ref", help="Git ref for --source git.")
    update_install_parser.set_defaults(func=update_install)
    update_config_parser = update_sub.add_parser("configure")
    update_config_parser.add_argument("--enabled", choices=("true", "false"))
    update_config_parser.add_argument("--interval-hours", type=int)
    update_config_parser.add_argument("--index-url")
    update_config_parser.add_argument("--source", choices=("pypi", "git"))
    update_config_parser.add_argument("--git-repo")
    update_config_parser.add_argument("--git-ref")
    update_config_parser.set_defaults(func=update_configure)
    start = sub.add_parser("start")
    start.add_argument("--test", action="store_true")
    start.set_defaults(func=runtime_start)
    sub.add_parser("stop").set_defaults(func=runtime_stop)
    restart = sub.add_parser("restart")
    restart.add_argument("--test", action="store_true")
    restart.set_defaults(func=runtime_restart)

    queue = sub.add_parser("queue")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    queue_sub.add_parser("status").set_defaults(func=queue_status)
    queue_sub.add_parser("clear").set_defaults(func=queue_clear)

    logs = sub.add_parser("logs")
    logs_sub = logs.add_subparsers(dest="logs_command", required=True)
    tail = logs_sub.add_parser("tail")
    tail.add_argument("target", choices=("all", "watcher", "audio"), nargs="?", default="all")
    tail.add_argument("--lines", type=int, default=80)
    tail.set_defaults(func=logs_tail)

    kokoro = sub.add_parser("kokoro")
    kokoro_sub = kokoro.add_subparsers(dest="kokoro_command", required=True)
    kokoro_sub.add_parser("status").set_defaults(func=kokoro_status)
    kokoro_sub.add_parser("install-deps").set_defaults(func=kokoro_install_deps)
    kokoro_config = kokoro_sub.add_parser("configure")
    kokoro_config.add_argument("--model-path")
    kokoro_config.add_argument("--voices-path")
    kokoro_config.add_argument("--voice")
    kokoro_config.add_argument("--lang")
    kokoro_config.set_defaults(func=kokoro_configure)

    bundle = sub.add_parser("support-bundle")
    bundle.add_argument("--output")
    bundle.add_argument("--full", action="store_true", help="Include full redacted logs instead of safe tails.")
    bundle.add_argument("--max-log-bytes", type=int, default=5_000_000, help="Maximum bytes per log in --full mode.")
    bundle.add_argument("--since", help="Only include log lines since this duration, for example 1h, 30m, or 300s.")
    bundle.add_argument("--include-config-full", action="store_true", help="Include a full redacted config snapshot.")
    bundle.set_defaults(func=support_bundle)

    install = sub.add_parser("install")
    install_sub = install.add_subparsers(dest="install_target", required=True)
    install_codex_parser = install_sub.add_parser("codex")
    install_codex_parser.set_defaults(func=install_codex)

    uninstall = sub.add_parser("uninstall")
    uninstall_sub = uninstall.add_subparsers(dest="uninstall_target", required=True)
    uninstall_codex_parser = uninstall_sub.add_parser("codex")
    uninstall_codex_parser.set_defaults(func=uninstall_codex)

    migrate = sub.add_parser("migrate-config")
    migrate.add_argument("--remove-legacy", action="store_true")
    migrate.set_defaults(func=migrate_config)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    get = config_sub.add_parser("get")
    get.add_argument("key", nargs="?")
    get.set_defaults(func=config_get)
    set_cmd = config_sub.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")
    set_cmd.set_defaults(func=config_set)
    defaults = config_sub.add_parser("defaults")
    defaults.add_argument("preset", nargs="?", choices=("kokoro", "system", "macos", "command"))
    defaults.set_defaults(func=config_defaults)
    schema = config_sub.add_parser("schema")
    schema.add_argument("preset", nargs="?", choices=("kokoro", "system", "macos", "command"))
    schema.set_defaults(func=config_schema)
    profiles = config_sub.add_parser("profile")
    profile_sub = profiles.add_subparsers(dest="profile_command", required=True)
    profile_sub.add_parser("list").set_defaults(func=profile_list)
    profile_save_cmd = profile_sub.add_parser("save")
    profile_save_cmd.add_argument("name")
    profile_save_cmd.set_defaults(func=profile_save)
    profile_use_cmd = profile_sub.add_parser("use")
    profile_use_cmd.add_argument("name")
    profile_use_cmd.set_defaults(func=profile_use)
    profile_delete_cmd = profile_sub.add_parser("delete")
    profile_delete_cmd.add_argument("name")
    profile_delete_cmd.set_defaults(func=profile_delete)
    prefixes = config_sub.add_parser("prefix")
    prefix_sub = prefixes.add_subparsers(dest="prefix_command", required=True)
    prefix_sub.add_parser("list").set_defaults(func=prefix_list)
    prefix_add_cmd = prefix_sub.add_parser("add")
    prefix_add_cmd.add_argument("prefix")
    prefix_add_cmd.set_defaults(func=prefix_add)
    prefix_remove_cmd = prefix_sub.add_parser("remove")
    prefix_remove_cmd.add_argument("prefix")
    prefix_remove_cmd.set_defaults(func=prefix_remove)

    instructions = sub.add_parser("instructions")
    instructions_sub = instructions.add_subparsers(dest="instructions_command", required=True)
    inst_print = instructions_sub.add_parser("print")
    inst_print.add_argument("target", choices=tuple(INSTRUCTION_FILES.keys()), nargs="?", default="agents")
    inst_print.add_argument("--language", choices=tuple(LANGUAGE_PROFILES.keys()), default="en")
    inst_print.add_argument("--style", choices=("strict", "minimal"), default="strict")
    inst_print.add_argument("--sync-config", action="store_true")
    inst_print.add_argument("--apply-tts", action="store_true")
    inst_print.set_defaults(func=instructions_print)
    inst_install = instructions_sub.add_parser("install")
    inst_install.add_argument("target", choices=tuple(INSTRUCTION_FILES.keys()), nargs="?", default="agents")
    inst_install.add_argument("--language", choices=tuple(LANGUAGE_PROFILES.keys()), default="en")
    inst_install.add_argument("--style", choices=("strict", "minimal"), default="strict")
    inst_install.add_argument("--no-sync-config", dest="sync_config", action="store_false")
    inst_install.add_argument("--apply-tts", action="store_true")
    inst_install.add_argument("--replace", action="store_true")
    inst_install.add_argument("--path")
    inst_install.set_defaults(sync_config=True)
    inst_install.set_defaults(func=instructions_install)
    inst_doctor = instructions_sub.add_parser("doctor")
    inst_doctor.add_argument("target", choices=tuple(INSTRUCTION_FILES.keys()), nargs="?", default="agents")
    inst_doctor.add_argument("--path")
    inst_doctor.set_defaults(func=instructions_doctor)

    tts = sub.add_parser("tts")
    tts_sub = tts.add_subparsers(dest="tts_command", required=True)
    use = tts_sub.add_parser("use")
    use.add_argument("preset", choices=("kokoro", "system", "macos", "command"))
    use.add_argument("--command")
    use.add_argument("--player")
    use.add_argument("--mode", choices=("play", "file"))
    use.set_defaults(func=tts_use)
    test = tts_sub.add_parser("test")
    test.add_argument("--text", default="")
    test.set_defaults(func=tts_test)
    caps = tts_sub.add_parser("capabilities")
    caps.add_argument("preset", nargs="?", choices=("kokoro", "system", "macos", "command"))
    caps.set_defaults(func=tts_capabilities)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
