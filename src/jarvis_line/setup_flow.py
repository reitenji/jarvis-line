from __future__ import annotations

import unicodedata
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
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
    text = validate_full_language(value)
    aliases = {
        "english": "English",
        "turkish": "Turkish",
    }
    return aliases.get(text.casefold(), text)


def validate_full_language(value: Any) -> str:
    raw = str(value or "")
    if any(unicodedata.category(char).startswith("C") for char in raw):
        raise SetupContractError("language name is invalid")
    text = raw.strip()
    if not text or (text.isascii() and text.isalpha() and len(text) <= 3):
        raise SetupContractError(
            'use a full language name, for example "English" or "Turkish"'
        )
    if len(text) > 80:
        raise SetupContractError("language name is invalid")
    allowed_punctuation = {" ", "-", "'", "\u2019", "(", ")"}
    if any(
        unicodedata.category(char)[0] not in {"L", "M"}
        and char not in allowed_punctuation
        for char in text
    ):
        raise SetupContractError("language name contains unsupported characters")
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
    global_destinations = {
        "agents": "~/.codex/AGENTS.md",
        "codex": "~/.codex/AGENTS.md",
        "claude": "~/.claude/CLAUDE.md",
        "gemini": "~/.gemini/GEMINI.md",
    }
    location = (
        global_destinations[plan.agent_target]
        if plan.instruction_scope == "global"
        else plan.project_path or "the current project"
    )
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


def prompt_choice(
    prompt: str,
    options: list[tuple[str, str]],
    *,
    default: str,
    input_fn=input,
    output_fn=print,
) -> str:
    """Select a value from a numbered, caller-controlled list."""
    option_ids = [option_id for option_id, _label in options]
    if not options or default not in option_ids:
        raise ValueError("prompt choices require a valid default")
    default_index = option_ids.index(default) + 1
    output_fn(prompt)
    for index, (_option_id, label) in enumerate(options, start=1):
        output_fn(f"  {index}. {label}")
    while True:
        choice = input_fn(f"Choose a number [{default_index}]: ").strip()
        if not choice:
            return default
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(options):
                return options[index - 1][0]
        output_fn(f"Choose a number from 1 to {len(options)}.")


def prompt_yes_no(
    prompt: str,
    *,
    default: bool,
    input_fn=input,
    output_fn=print,
) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        choice = input_fn(f"{prompt} [{suffix}]: ").strip().casefold()
        if not choice:
            return default
        if choice in {"y", "yes"}:
            return True
        if choice in {"n", "no"}:
            return False
        output_fn("Choose yes or no.")


def prompt_language(
    *,
    default: str,
    input_fn=input,
    output_fn=print,
) -> str:
    languages = list(UI_OPTIONS["line_language"])
    other_id = "__other_language__"
    default_id = default if default in languages else other_id
    choice = prompt_choice(
        "Jarvis line language",
        [(language, language) for language in languages]
        + [(other_id, "Other language...")],
        default=default_id,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    if choice != other_id:
        return normalize_language(choice)
    while True:
        try:
            return normalize_language(input_fn("Full language name: "))
        except SetupContractError as exc:
            output_fn(str(exc))


def _default_backend(options: list[dict[str, Any]], current: Mapping[str, Any]) -> str:
    current_tts = current.get("tts")
    available = {option["id"] for option in options if option["available"]}
    if current_tts in available:
        return str(current_tts)
    for option in options:
        if option["available"] and option["recommended"]:
            return str(option["id"])
    return next(str(option["id"]) for option in options if option["available"])


def collect_setup_plan(
    env: SetupEnvironment,
    current: Mapping[str, Any],
    *,
    force_test: bool = False,
    input_fn=input,
    output_fn=print,
) -> SetupPlan:
    """Collect a reviewed setup plan without writing config or starting services."""
    current = dict(current)
    language = prompt_language(
        default=normalize_language(current.get("line_language", "English")),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    inspected_backends = backend_options(env, language, current)
    available_backends = [option for option in inspected_backends if option["available"]]
    if not available_backends:
        raise SetupContractError("no TTS backend is available on this machine")
    if not any(option["id"] == "command" for option in available_backends):
        output_fn(
            "Custom command TTS is unavailable until configured; run "
            "`jarvis-line tts use command --command ...`."
        )
    tts = prompt_choice(
        "Voice backend",
        [(str(option["id"]), str(option["label"])) for option in available_backends],
        default=_default_backend(available_backends, current),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    speak_mode_options = [
        ("final_only", "Final responses only"),
        ("commentary_and_final", "Commentary and final responses"),
        ("off", "Do not speak"),
    ]
    current_speak_mode = str(current.get("speak_mode", "final_only"))
    if current_speak_mode not in {option_id for option_id, _label in speak_mode_options}:
        current_speak_mode = "final_only"
    speak_mode = prompt_choice(
        "When should Jarvis Line speak?",
        speak_mode_options,
        default=current_speak_mode,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    agent_target = prompt_choice(
        "Agent instruction target",
        [
            ("agents", "AGENTS.md-compatible agent"),
            ("codex", "Codex"),
            ("claude", "Claude"),
            ("gemini", "Gemini"),
        ],
        default="agents",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    instruction_scope = prompt_choice(
        "Instruction guidance scope",
        [("project", "Current project"), ("global", "Your global agent instructions")],
        default="project",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    project_path = str(Path.cwd()) if instruction_scope == "project" else None
    install_kokoro = tts == "kokoro" and not env.kokoro_ready and prompt_yes_no(
        "Install verified Kokoro assets before applying setup?",
        default=True,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    install_codex_hook = agent_target == "codex" and prompt_yes_no(
        "Install the Codex SessionStart hook?",
        default=True,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    start_runtime = prompt_yes_no(
        "Start the Jarvis Line runtime after setup?",
        default=True,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    test_voice = force_test or prompt_yes_no(
        "Play a short voice test after setup?",
        default=False,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return SetupPlan.from_mapping(
        {
            "version": SETUP_SCHEMA_VERSION,
            "language": language,
            "tts": tts,
            "speak_mode": speak_mode,
            "agent_target": agent_target,
            "instruction_scope": instruction_scope,
            "install_kokoro": install_kokoro,
            "install_codex_hook": install_codex_hook,
            "start_runtime": start_runtime,
            "test_voice": test_voice,
            "project_path": project_path,
            "command": current.get("command") if tts == "command" else None,
        }
    )


def review_lines(plan: SetupPlan, env: SetupEnvironment) -> list[str]:
    guidance = instruction_guidance(plan)
    lines = [
        "Review setup:",
        f"  Language: {plan.language}",
        f"  Voice backend: {plan.tts}",
        f"  Speech mode: {plan.speak_mode}",
        f"  Instruction guidance: {guidance['scope']} {guidance['filename']} at {guidance['destination']}",
        "  Instruction files are guidance only and will not be written.",
        f"  Start runtime: {'yes' if plan.start_runtime else 'no'}",
        f"  Voice test: {'yes' if plan.test_voice else 'no'}",
    ]
    if plan.tts == "kokoro" and not env.kokoro_ready:
        lines.append(f"  Install Kokoro assets: {'yes' if plan.install_kokoro else 'no'}")
    if plan.agent_target == "codex":
        lines.append(f"  Install Codex hook: {'yes' if plan.install_codex_hook else 'no'}")
    return lines
