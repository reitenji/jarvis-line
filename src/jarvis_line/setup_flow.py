from __future__ import annotations

import unicodedata
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from jarvis_line import kokoro_assets
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
    "attention_enabled",
    "install_kokoro",
    "accept_kokoro_license",
    "install_codex_hook",
    "start_runtime",
    "test_voice",
    "project_path",
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
    attention_enabled: bool = False
    install_kokoro: bool = False
    accept_kokoro_license: bool = False
    install_codex_hook: bool = False
    start_runtime: bool = True
    test_voice: bool = False
    project_path: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SetupPlan":
        if not isinstance(value, Mapping):
            raise SetupContractError("setup plan must be an object")
        unknown = sorted(set(value) - PLAN_FIELDS)
        if unknown:
            raise SetupContractError(f"unknown field: {unknown[0]}")
        if value.get("version") != SETUP_SCHEMA_VERSION:
            raise SetupContractError("unsupported setup plan version")
        language = normalize_language(value.get("language"))

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
        attention_enabled = boolean("attention_enabled", False)
        install_kokoro = boolean("install_kokoro", False)
        accept_kokoro_license = boolean("accept_kokoro_license", False)
        install_hook = boolean("install_codex_hook", False)
        if install_kokoro and (tts != "kokoro" or language != "English"):
            raise SetupContractError(
                "verified Kokoro install requires English and the kokoro backend"
            )
        if install_kokoro and not accept_kokoro_license:
            raise SetupContractError(
                "Kokoro installation requires explicit license acceptance"
            )
        if accept_kokoro_license and not install_kokoro:
            raise SetupContractError(
                "Kokoro license acceptance requires an installation request"
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

        return cls(
            version=SETUP_SCHEMA_VERSION,
            language=language,
            tts=tts,
            speak_mode=speak_mode,
            agent_target=agent_target,
            instruction_scope=scope,
            attention_enabled=attention_enabled,
            install_kokoro=install_kokoro,
            accept_kokoro_license=accept_kokoro_license,
            install_codex_hook=install_hook,
            start_runtime=boolean("start_runtime", True),
            test_voice=boolean("test_voice", False),
            project_path=project_path,
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


def preflight_backend(
    plan: SetupPlan,
    env: SetupEnvironment,
    current: Mapping[str, Any],
) -> None:
    """Reject backend plans that cannot safely reach the config-write step."""
    language = normalize_language(plan.language)
    if plan.tts == "kokoro":
        if language != "English":
            raise SetupContractError("guided setup only supports English Kokoro")
        if env.platform not in {"Darwin", "Linux", "Windows"}:
            raise SetupContractError("Kokoro is unavailable on this platform")
        if not plan.install_kokoro and not env.kokoro_ready:
            raise SetupContractError("Kokoro is not ready: " + env.kokoro_detail)
        return
    if plan.tts == "system":
        if not env.system_tts_ready:
            raise SetupContractError("system TTS is not ready: " + env.system_tts_detail)
        return
    if plan.tts == "macos":
        if env.platform != "Darwin" or not env.macos_say_ready:
            raise SetupContractError("macOS say is not ready on this machine")
        return
    if plan.tts == "command" and not current.get("command"):
        raise SetupContractError("custom command TTS requires a reviewed command")


def build_inspection(
    env: SetupEnvironment,
    current: Mapping[str, Any],
    language: str = "English",
) -> dict[str, Any]:
    selected_language = normalize_language(language)
    current_tts = current.get("tts")
    if current_tts not in {"kokoro", "system", "macos", "command"}:
        current_tts = "system"
    current_speak_mode = current.get("speak_mode")
    if current_speak_mode not in {"final_only", "commentary_and_final", "off"}:
        current_speak_mode = "final_only"
    try:
        current_language = normalize_language(current.get("line_language"))
    except SetupContractError:
        current_language = selected_language
    return {
        "version": SETUP_SCHEMA_VERSION,
        "environment": asdict(env),
        "current": {
            "tts": current_tts,
            "line_language": current_language,
            "speak_mode": current_speak_mode,
            "attention_enabled": current.get("attention_enabled") is True,
        },
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
    cfg["attention_enabled"] = plan.attention_enabled
    if plan.tts == "kokoro" and plan.language == "English":
        cfg["lang"] = "en-gb"
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
    backend_choices = []
    for option in available_backends:
        recommendation = " (recommended)" if option["recommended"] else ""
        backend_choices.append(
            (
                str(option["id"]),
                f"{option['label']}{recommendation} - {option['detail']}",
            )
        )
    tts = prompt_choice(
        "Voice backend",
        backend_choices,
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
    attention_enabled = False
    if speak_mode != "off":
        attention_default = current.get("attention_enabled")
        if type(attention_default) is not bool:
            attention_default = agent_target == "codex" and not env.config_exists
        attention_enabled = prompt_yes_no(
            "Enable attention alerts for permission and input requests?",
            default=attention_default,
            input_fn=input_fn,
            output_fn=output_fn,
        )
    install_kokoro = False
    if tts == "kokoro" and not env.kokoro_ready:
        output_fn("Kokoro installation disclosure:")
        output_fn(f"  Source: {kokoro_assets.OFFICIAL_RELEASE_URL}")
        output_fn(f"  Model license: {kokoro_assets.MODEL_LICENSE}")
        output_fn("  Download size: approximately 350 MB")
        install_kokoro = prompt_yes_no(
            "Accept the model license and install verified Kokoro assets during Apply?",
            default=False,
            input_fn=input_fn,
            output_fn=output_fn,
        )
    install_codex_hook = agent_target == "codex" and prompt_yes_no(
        "Install the Codex SessionStart and PermissionRequest hooks?",
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
            "attention_enabled": attention_enabled,
            "install_kokoro": install_kokoro,
            "accept_kokoro_license": install_kokoro,
            "install_codex_hook": install_codex_hook,
            "start_runtime": start_runtime,
            "test_voice": test_voice,
            "project_path": project_path,
        }
    )


def review_lines(plan: SetupPlan, env: SetupEnvironment) -> list[str]:
    guidance = instruction_guidance(plan)
    agent_names = {
        "agents": "Generic AGENTS.md-compatible agent",
        "codex": "Codex",
        "claude": "Claude",
        "gemini": "Gemini",
    }
    backend_names = {
        "kokoro": "Kokoro local",
        "system": "System voice",
        "macos": "macOS say",
        "command": "Existing reviewed custom TTS",
    }
    lines = [
        "Review setup:",
        f"  Language: {plan.language}",
        f"  Voice backend: {backend_names[plan.tts]}",
        f"  Speech mode: {plan.speak_mode}",
        f"  Attention alerts: {'enabled' if plan.attention_enabled else 'disabled'}",
        f"  Agent: {agent_names[plan.agent_target]}",
        f"  Instruction guidance: {guidance['scope']} {guidance['filename']} at {guidance['destination']}",
        "  Instruction files are guidance only and will not be written.",
        f"  Start runtime: {'yes' if plan.start_runtime else 'no'}",
        f"  Voice test: {'yes' if plan.test_voice else 'no'}",
    ]
    if plan.tts == "kokoro" and not env.kokoro_ready:
        lines.append(f"  Install Kokoro assets: {'yes' if plan.install_kokoro else 'no'}")
    if normalize_language(plan.language) != "English":
        if plan.tts in {"system", "macos"}:
            lines.append(
                "  Language compatibility: select a matching system voice; "
                "use an existing reviewed custom TTS for another model or API."
            )
        elif plan.tts == "command":
            lines.append(
                "  Language compatibility: your existing custom TTS must support "
                f"{plan.language}."
            )
    if plan.agent_target == "codex":
        lines.append(f"  Install Codex hook: {'yes' if plan.install_codex_hook else 'no'}")
    return lines
