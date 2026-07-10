import pytest

from jarvis_line import setup_flow


def environment(**overrides):
    values = {
        "platform": "Darwin",
        "config_exists": False,
        "kokoro_ready": True,
        "kokoro_detail": "ready",
        "system_tts_ready": True,
        "system_tts_detail": "say",
        "macos_say_ready": True,
    }
    values.update(overrides)
    return setup_flow.SetupEnvironment(**values)


def valid_plan():
    return {
        "version": 1,
        "language": "English",
        "tts": "kokoro",
        "speak_mode": "final_only",
        "agent_target": "codex",
        "instruction_scope": "project",
    }


def test_inspection_recommends_ready_kokoro_for_english():
    inspection = setup_flow.build_inspection(environment(), {}, language="English")
    options = {item["id"]: item for item in inspection["backend_options"]}

    assert inspection["version"] == 1
    assert options["kokoro"]["recommended"] is True
    assert options["system"]["available"] is True


def test_inspection_recommends_system_for_turkish():
    inspection = setup_flow.build_inspection(environment(), {}, language="Turkish")
    options = {item["id"]: item for item in inspection["backend_options"]}

    assert options["system"]["recommended"] is True
    assert options["kokoro"]["available"] is False


@pytest.mark.parametrize("language", ["en", "tr"])
def test_inspection_apis_reject_short_language_codes(language):
    with pytest.raises(setup_flow.SetupContractError, match="full language name"):
        setup_flow.build_inspection(environment(), {}, language=language)
    with pytest.raises(setup_flow.SetupContractError, match="full language name"):
        setup_flow.backend_options(environment(), language, {})


@pytest.mark.parametrize(
    ("language", "expected"),
    [("english", "English"), ("TURKISH", "Turkish")],
)
def test_inspection_accepts_case_normalized_full_language_names(language, expected):
    inspection = setup_flow.build_inspection(environment(), {}, language=language)

    assert inspection["language"] == expected


@pytest.mark.parametrize(
    ("agent_target", "expected_destination"),
    [
        ("agents", "~/.codex/AGENTS.md"),
        ("codex", "~/.codex/AGENTS.md"),
        ("claude", "~/.claude/CLAUDE.md"),
        ("gemini", "~/.gemini/GEMINI.md"),
    ],
)
def test_instruction_guidance_names_global_user_destination(
    agent_target, expected_destination
):
    plan = setup_flow.SetupPlan.from_mapping(
        {
            **valid_plan(),
            "agent_target": agent_target,
            "instruction_scope": "global",
        }
    )

    guidance = setup_flow.instruction_guidance(plan)

    assert guidance["destination"] == expected_destination
    assert guidance["destination"] != "the current project"


def test_plan_rejects_unknown_fields_and_short_language_codes():
    with pytest.raises(setup_flow.SetupContractError, match="unknown field"):
        setup_flow.SetupPlan.from_mapping(
            {**valid_plan(), "instruction_path": "/tmp/AGENTS.md"}
        )
    with pytest.raises(setup_flow.SetupContractError, match="full language name"):
        setup_flow.SetupPlan.from_mapping({**valid_plan(), "language": "tr"})


def test_prompt_choice_retries_invalid_numbered_input():
    answers = iter(["99", "x", "2"])
    output = []

    chosen = setup_flow.prompt_choice(
        "Voice",
        [("kokoro", "Kokoro"), ("system", "System")],
        default="kokoro",
        input_fn=lambda _prompt: next(answers),
        output_fn=output.append,
    )

    assert chosen == "system"
    assert sum("Choose a number" in line for line in output) == 2


def test_prompt_language_requires_a_full_name_for_other_language():
    answers = iter(["7", "tr", "Turkish"])
    output = []

    language = setup_flow.prompt_language(
        default="English",
        input_fn=lambda _prompt: next(answers),
        output_fn=output.append,
    )

    assert language == "Turkish"
    assert any("full language name" in line for line in output)


def test_collect_setup_plan_uses_project_scope_as_guidance_only(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_flow.Path, "cwd", classmethod(lambda _cls: tmp_path))
    answers = iter(["1", "1", "1", "1", "1", "n", "y", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {},
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.instruction_scope == "project"
    assert plan.project_path == str(tmp_path)
    assert not list(tmp_path.glob("*.md"))


def test_collect_setup_plan_hides_advanced_command_without_existing_command():
    output = []
    answers = iter(["1", "1", "1", "1", "1", "n", "y", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {},
        input_fn=lambda _prompt: next(answers),
        output_fn=output.append,
    )

    assert plan.tts == "kokoro"
    assert all("Advanced custom TTS" not in line for line in output)
    assert any("tts use command" in line for line in output)


def test_collect_setup_plan_reuses_an_existing_advanced_command():
    answers = iter(["1", "4", "1", "1", "1", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {"command": ["custom-tts", "{text}"]},
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.tts == "command"
    assert plan.command == ["custom-tts", "{text}"]


def test_collect_setup_plan_forces_voice_test_when_requested():
    answers = iter(["1", "1", "1", "1", "1", "n", "y"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {},
        force_test=True,
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.test_voice is True
