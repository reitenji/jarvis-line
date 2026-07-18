from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


CONTRACT_VERSION = 1
JARVIS_HOME = Path.home() / ".jarvis-line"
TTS_HOME = JARVIS_HOME / "tts"
KOKORO_MODEL = TTS_HOME / "kokoro-models" / "kokoro-v1.0.onnx"
KOKORO_VOICES = TTS_HOME / "kokoro-models" / "voices-v1.0.bin"
DEFAULT_GIT_REPO = "https://github.com/reitenji/jarvis-line.git"


DEFAULT_KOKORO_CONFIG = {
    "tts": "kokoro",
    "speak_mode": "final_only",
    "line_prefixes": ["Jarvis line:"],
    "speak_without_prefix": False,
    "line_language": "English",
    "max_spoken_chars": 240,
    "quiet_hours": None,
    "quiet_days": [],
    "max_queue_size": 8,
    "dedupe_window_seconds": None,
    "fallback_tts": None,
    "warm_tts": True,
    "warm_tts_text": "Ready.",
    "audio_worker_idle_exit_seconds": 60,
    "audio_worker_max_rss_mb": 512,
    "message_template": "{line}",
    "assistant_name": "Jarvis",
    "speech_enabled": True,
    "attention_enabled": False,
    "cleanup_enabled": True,
    "cleanup_interval_hours": 24,
    "debug_content_logging": False,
    "update_check_enabled": True,
    "update_check_interval_hours": 24,
    "update_index_url": "https://pypi.org/pypi/jarvis-line/json",
    "update_source": "git",
    "update_git_repo": DEFAULT_GIT_REPO,
    "update_git_ref": "latest",
    "last_update_check_ts": 0,
    "model_path": str(KOKORO_MODEL),
    "voices_path": str(KOKORO_VOICES),
    "voice": "bm_george:70,bm_lewis:30",
    "lang": "en-gb",
    "speed": 1.08,
    "volume": 0.7,
    "play_by_default": True,
    "final_trigger_mode": "notify",
    "playback_mode": "tempfile",
    "fallback_playback_mode": "tempfile",
    "delete_after_play": True,
    "temp_dir": str(TTS_HOME / "generated"),
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
    "speak_without_prefix",
    "line_language",
    "max_spoken_chars",
    "quiet_hours",
    "quiet_days",
    "max_queue_size",
    "dedupe_window_seconds",
    "fallback_tts",
    "warm_tts",
    "warm_tts_text",
    "audio_worker_idle_exit_seconds",
    "audio_worker_max_rss_mb",
    "message_template",
    "assistant_name",
    "speech_enabled",
    "attention_enabled",
    "cleanup_enabled",
    "cleanup_interval_hours",
    "debug_content_logging",
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
        "supports": COMMON_CONFIG_KEYS
        | {"model_path", "voices_path", "voice", "lang", "speed", "playback_mode", "fallback_playback_mode"},
        "unsupported": {"macos_voice", "macos_rate", "system_voice", "system_rate"},
        "description": "Local Kokoro ONNX voice. Supports voice mix, lang, speed, stream/tempfile playback.",
    },
    "macos": {
        "supports": COMMON_CONFIG_KEYS | {"macos_voice", "macos_rate"},
        "unsupported": {
            "model_path", "voices_path", "voice", "lang", "speed", "playback_mode",
            "fallback_playback_mode", "system_voice", "system_rate",
        },
        "description": "macOS say fallback. Supports macos_voice and macos_rate; Kokoro model/lang/speed fields are ignored.",
    },
    "system": {
        "supports": COMMON_CONFIG_KEYS | {"system_voice", "system_rate"},
        "unsupported": {
            "model_path", "voices_path", "voice", "lang", "speed", "playback_mode",
            "fallback_playback_mode", "macos_voice", "macos_rate",
        },
        "description": "Platform default TTS fallback. Uses say on macOS, PowerShell SpeechSynthesizer on Windows, or spd-say/espeak on Linux.",
    },
    "command": {
        "supports": COMMON_CONFIG_KEYS
        | {"command_mode", "command", "player", "command_timeout_seconds", "command_output_suffix", "command_env", "command_cwd", "command_retries"},
        "unsupported": {
            "model_path", "voices_path", "voice", "lang", "speed", "playback_mode",
            "fallback_playback_mode", "macos_voice", "macos_rate", "system_voice", "system_rate",
        },
        "description": "Custom command backend. Use placeholders {text}, {text_json}, and {output}. Advanced custom_* and backend_* keys are allowed.",
    },
}

CONFIG_FIELD_HELP = {
    "tts": {"type": "string", "description": "Selected TTS backend.", "values": sorted(BACKEND_CAPABILITIES)},
    "speak_mode": {"type": "string", "description": "When Jarvis Line should speak.", "values": ["final_only", "commentary_and_final", "off"]},
    "line_prefixes": {"type": "array[string]", "description": "Accepted spoken-line prefixes."},
    "speak_without_prefix": {"type": "boolean", "description": "Speak a short derived status from assistant messages even when no explicit Jarvis line is present."},
    "line_language": {"type": "string", "description": "Expected language for generated Jarvis lines."},
    "max_spoken_chars": {"type": "integer", "description": "Maximum spoken summary length."},
    "quiet_hours": {"type": "string|null", "description": "Optional quiet-hours range, for example 22:00-08:00."},
    "quiet_days": {"type": "array[string]", "description": "Optional days where speech is skipped."},
    "max_queue_size": {"type": "integer", "description": "Maximum queued audio jobs."},
    "dedupe_window_seconds": {"type": "integer|null", "description": "Override duplicate suppression window."},
    "fallback_tts": {"type": "string|null", "description": "Fallback TTS backend if the selected backend fails.", "values": ["system", "macos", "command", None]},
    "warm_tts": {"type": "boolean", "description": "Preload the selected TTS engine to reduce first-speech delay."},
    "warm_tts_text": {"type": "string", "description": "Short text used for silent Kokoro stream warm-up."},
    "audio_worker_idle_exit_seconds": {"type": "integer", "description": "Seconds the audio worker can stay idle before exiting."},
    "audio_worker_max_rss_mb": {"type": "integer", "description": "Maximum worker RSS before it exits after draining queued work."},
    "message_template": {"type": "string", "description": "Template for spoken output. Use {line} for the Jarvis line."},
    "assistant_name": {"type": "string", "description": "Assistant/persona name used in generated instructions."},
    "speech_enabled": {"type": "boolean", "description": "Project/user switch for all Jarvis Line speech."},
    "attention_enabled": {"type": "boolean", "description": "Speak optional permission and input-required alerts."},
    "cleanup_enabled": {
        "type": "boolean",
        "description": "Run bounded cleanup automatically when maintenance is due.",
    },
    "cleanup_interval_hours": {
        "type": "integer",
        "description": "Minimum interval between automatic cleanup attempts.",
        "values": [24, 168],
    },
    "debug_content_logging": {"type": "boolean", "description": "Include spoken text in local runtime logs. Disabled by default."},
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

UI_OPTIONS = {
    "tts": ["kokoro", "system", "macos", "command"],
    "line_language": ["English", "Turkish", "French", "Italian", "Japanese", "Chinese"],
    "quiet_hours": [None, "22:00-08:00", "20:00-08:00", "18:00-09:00"],
    "max_spoken_chars": [120, 180, 240, 300],
    "max_queue_size": [4, 8, 16],
    "fallback_tts": [None, "system", "macos", "command"],
    "warm_tts_text": ["Ready.", "Jarvis ready.", "Speech ready."],
    "voice": ["bm_george:70,bm_lewis:30", "bm_george", "bm_lewis"],
    "lang": ["en-gb", "en-us", "fr-fr", "it", "ja", "cmn"],
    "speed": [0.9, 1.0, 1.08, 1.2],
    "system_rate": [160, 180, 185, 200, 220, 240],
    "cleanup_interval_hours": [24, 168],
    "update_check_interval_hours": [6, 12, 24, 48, 168],
}


def default_config(preset: str = "kokoro") -> dict[str, Any]:
    configs = {
        "kokoro": DEFAULT_KOKORO_CONFIG,
        "macos": DEFAULT_MACOS_CONFIG,
        "system": DEFAULT_SYSTEM_CONFIG,
        "command": DEFAULT_COMMAND_CONFIG,
    }
    if preset not in configs:
        raise ValueError(f"unknown config preset: {preset}")
    return deepcopy(configs[preset])


def field_schema() -> dict[str, dict[str, Any]]:
    return deepcopy(CONFIG_FIELD_HELP)


def backend_capabilities() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "description": value["description"],
            "supports": sorted(value["supports"]),
            "ignores": sorted(value["unsupported"]),
        }
        for name, value in BACKEND_CAPABILITIES.items()
    }


def contract_document() -> dict[str, Any]:
    return {
        "version": CONTRACT_VERSION,
        "defaults": default_config(),
        "fields": field_schema(),
        "backends": backend_capabilities(),
        "ui_options": deepcopy(UI_OPTIONS),
    }
