from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from jarvis_line.config_contract import (
    BACKEND_CAPABILITIES,
    DEFAULT_COMMAND_CONFIG,
    DEFAULT_KOKORO_CONFIG,
    DEFAULT_MACOS_CONFIG,
    DEFAULT_SYSTEM_CONFIG,
    UI_OPTIONS,
)


SETUP_SCHEMA_VERSION = 1
MAX_SETUP_PLAN_BYTES = 65_536
PLAN_FIELDS = {
    "version",
    "language",
    "tts",
    "speak_mode",
    "agent_target",
    "instruction_scope",
    "install_kokoro",
    "install_codex_hook",
    "start_runtime",
    "test_voice",
    "project_path",
    "command",
}


class SetupContractError(ValueError):
    pass


def normalize_language(value: Any) -> str:
    text = str(value or "English").strip()
    aliases = {
        "en": "English",
        "english": "English",
        "tr": "Turkish",
        "turkish": "Turkish",
    }
    return aliases.get(text.casefold(), text)


def validate_full_language(value: Any) -> str:
    text = str(value or "").strip()
    if not text or (text.isascii() and text.isalpha() and len(text) <= 3):
        raise SetupContractError(
            'use a full language name, for example "English" or "Turkish"'
        )
    if len(text) > 80 or any(ord(char) < 32 for char in text):
        raise SetupContractError("language name is invalid")
    return text


@dataclass(frozen=True)
class SetupEnvironment:
    platform: str
    config_exists: bool
    kokoro_ready: bool
    kokoro_detail: str
    system_tts_ready: bool
    system_tts_detail: str
    macos_say_ready: bool


@dataclass(frozen=True)
class SetupPlan:
    version: int
    language: str
    tts: str
    speak_mode: str
    agent_target: str
    instruction_scope: str
    install_kokoro: bool = False
    install_codex_hook: bool = False
    start_runtime: bool = True
    test_voice: bool = False
    project_path: str | None = None
    command: str | list[str] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SetupPlan":
        if not isinstance(value, Mapping):
            raise SetupContractError("setup plan must be an object")
        unknown = sorted(set(value) - PLAN_FIELDS)
        if unknown:
            raise SetupContractError(f"unknown field: {unknown[0]}")
        if value.get("version") != SETUP_SCHEMA_VERSION:
            raise SetupContractError("unsupported setup plan version")
        language = validate_full_language(value.get("language"))

        def enum(name: str, allowed: set[str]) -> str:
            selected = value.get(name)
            if selected not in allowed:
                raise SetupContractError(f"invalid {name}: {selected!r}")
            return str(selected)

        def boolean(name: str, default: bool) -> bool:
            selected = value.get(name, default)
            if type(selected) is not bool:
                raise SetupContractError(f"{name} must be boolean")
            return selected

        tts = enum("tts", {"kokoro", "system", "macos", "command"})
        speak_mode = enum("speak_mode", {"final_only", "commentary_and_final", "off"})
        agent_target = enum("agent_target", {"agents", "codex", "claude", "gemini"})
        scope = enum("instruction_scope", {"project", "global"})
        install_kokoro = boolean("install_kokoro", False)
        install_hook = boolean("install_codex_hook", False)
        if install_kokoro and (tts != "kokoro" or language != "English"):
            raise SetupContractError(
                "verified Kokoro install requires English and the kokoro backend"
            )
        if install_hook and agent_target != "codex":
            raise SetupContractError(
                "Codex hook installation requires the codex target"
            )

        project_path = value.get("project_path")
        if project_path is not None and (
            not isinstance(project_path, str) or "\x00" in project_path
        ):
            raise SetupContractError("project_path must be a safe string or null")
        if scope == "global" and project_path is not None:
            raise SetupContractError("global instruction scope cannot include project_path")

        command = value.get("command")
        command_parts = [command] if isinstance(command, str) else command
        if command_parts is not None:
            if (
                not isinstance(command_parts, list)
                or not command_parts
                or len(command_parts) > 32
            ):
                raise SetupContractError("command must be a string or 1-32 argument strings")
            if any(
                not isinstance(part, str) or not part or "\x00" in part
                for part in command_parts
            ):
                raise SetupContractError("command arguments must be non-empty safe strings")
            if sum(len(part) for part in command_parts) > 2048:
                raise SetupContractError("command exceeds 2048 characters")

        return cls(
            version=SETUP_SCHEMA_VERSION,
            language=language,
            tts=tts,
            speak_mode=speak_mode,
            agent_target=agent_target,
            instruction_scope=scope,
            install_kokoro=install_kokoro,
            install_codex_hook=install_hook,
            start_runtime=boolean("start_runtime", True),
            test_voice=boolean("test_voice", False),
            project_path=project_path,
            command=command,
        )


def backend_options(
    env: SetupEnvironment,
    language: str,
    current: Mapping[str, Any],
) -> list[dict[str, Any]]:
    english = normalize_language(language) == "English"
    kokoro_supported = env.platform in {"Darwin", "Linux", "Windows"}
    kokoro_recommended = english and env.kokoro_ready
    system_recommended = (not kokoro_recommended) and env.system_tts_ready
    command_ready = bool(current.get("command"))
    return [
        {
            "id": "kokoro",
            "label": "Kokoro local",
            "available": english and kokoro_supported,
            "ready": env.kokoro_ready,
            "recommended": kokoro_recommended,
            "requires_install": english and not env.kokoro_ready,
            "detail": env.kokoro_detail
            if english
            else "Use a matching custom model for non-English speech.",
        },
        {
            "id": "system",
            "label": "System voice",
            "available": env.system_tts_ready,
            "ready": env.system_tts_ready,
            "recommended": system_recommended,
            "requires_install": False,
            "detail": env.system_tts_detail,
        },
        {
            "id": "macos",
            "label": "macOS say",
            "available": env.platform == "Darwin" and env.macos_say_ready,
            "ready": env.macos_say_ready,
            "recommended": False,
            "requires_install": False,
            "detail": "Explicit macOS voice and rate controls.",
        },
        {
            "id": "command",
            "label": "Advanced custom TTS",
            "available": command_ready,
            "ready": command_ready,
            "recommended": not kokoro_recommended
            and not system_recommended
            and command_ready,
            "requires_install": False,
            "detail": "Uses the existing reviewed custom command."
            if command_ready
            else "Configure a custom command first.",
        },
    ]


def build_inspection(
    env: SetupEnvironment,
    current: Mapping[str, Any],
    language: str = "English",
) -> dict[str, Any]:
    selected_language = normalize_language(language)
    return {
        "version": SETUP_SCHEMA_VERSION,
        "environment": asdict(env),
        "current": deepcopy(dict(current)),
        "language": selected_language,
        "backend_options": backend_options(env, selected_language, current),
        "ui_options": deepcopy(UI_OPTIONS),
        "needs_setup": not env.config_exists,
    }


def config_for_preset(preset: str, current: dict[str, Any]) -> dict[str, Any]:
    configs = {
        "kokoro": DEFAULT_KOKORO_CONFIG,
        "macos": DEFAULT_MACOS_CONFIG,
        "system": DEFAULT_SYSTEM_CONFIG,
        "command": DEFAULT_COMMAND_CONFIG,
    }
    if preset not in configs:
        raise ValueError(f"Unknown preset: {preset}")

    cfg = {**configs[preset], **current, "tts": preset}
    for key in BACKEND_CAPABILITIES[preset]["unsupported"]:
        cfg.pop(key, None)
    if preset == "macos":
        cfg.setdefault("macos_voice", DEFAULT_MACOS_CONFIG["macos_voice"])
        cfg.setdefault("macos_rate", DEFAULT_MACOS_CONFIG["macos_rate"])
    elif preset == "system":
        cfg.setdefault("system_voice", DEFAULT_SYSTEM_CONFIG["system_voice"])
        cfg.setdefault("system_rate", DEFAULT_SYSTEM_CONFIG["system_rate"])
    elif preset == "command":
        cfg.setdefault("command", DEFAULT_COMMAND_CONFIG["command"])
        cfg.setdefault("command_mode", DEFAULT_COMMAND_CONFIG["command_mode"])
    return cfg


def build_config(plan: SetupPlan, current: Mapping[str, Any]) -> dict[str, Any]:
    cfg = config_for_preset(plan.tts, dict(current))
    cfg["line_language"] = plan.language
    cfg["speak_mode"] = plan.speak_mode
    cfg["speech_enabled"] = plan.speak_mode != "off"
    if plan.tts == "kokoro" and plan.language == "English":
        cfg["lang"] = "en-gb"
    if plan.tts == "command" and plan.command:
        cfg["command"] = plan.command
    return cfg


def instruction_guidance(plan: SetupPlan) -> dict[str, str | None]:
    target_files = {
        "agents": "AGENTS.md",
        "codex": "AGENTS.md",
        "claude": "CLAUDE.md",
        "gemini": "GEMINI.md",
    }
    filename = target_files[plan.agent_target]
    location = plan.project_path or "the current project"
    return {
        "target": plan.agent_target,
        "scope": plan.instruction_scope,
        "filename": filename,
        "destination": location,
        "command": (
            f'jarvis-line instructions print {plan.agent_target} '
            f'--language "{plan.language}"'
        ),
    }
