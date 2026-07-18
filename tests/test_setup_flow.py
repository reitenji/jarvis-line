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


def test_inspection_exposes_only_safe_current_setup_values():
    inspection = setup_flow.build_inspection(
        environment(),
        {
            "tts": "command",
            "line_language": "English",
            "speak_mode": "commentary_and_final",
            "attention_enabled": True,
            "command": 'curl -H "Authorization: Bearer secret" https://example.test',
            "command_env": {"API_KEY": "top-secret"},
            "command_cwd": "/Users/example/private-project",
            "model_path": "/Users/example/private-model.onnx",
        },
        language="English",
    )

    assert inspection["current"] == {
        "tts": "command",
        "line_language": "English",
        "speak_mode": "commentary_and_final",
        "attention_enabled": True,
    }
    assert "secret" not in str(inspection)
    assert "/Users/example" not in str(inspection)


def test_language_preview_does_not_overwrite_the_reported_current_language():
    inspection = setup_flow.build_inspection(
        environment(),
        {"tts": "system", "line_language": "English"},
        language="Turkish",
    )

    assert inspection["language"] == "Turkish"
    assert inspection["current"]["line_language"] == "English"


def test_attention_plan_defaults_off_and_requires_a_strict_boolean():
    plan = setup_flow.SetupPlan.from_mapping(valid_plan())

    assert plan.attention_enabled is False

    with pytest.raises(setup_flow.SetupContractError, match="attention_enabled"):
        setup_flow.SetupPlan.from_mapping(
            {**valid_plan(), "attention_enabled": "true"}
        )


def test_build_config_and_review_persist_enabled_attention():
    plan = setup_flow.SetupPlan.from_mapping(
        {**valid_plan(), "attention_enabled": True}
    )

    config = setup_flow.build_config(plan, {})
    review = "\n".join(setup_flow.review_lines(plan, environment()))

    assert config["attention_enabled"] is True
    assert "Attention alerts: enabled" in review


def test_collect_setup_plan_recommends_attention_for_codex():
    answers = iter(["1", "1", "1", "2", "1", "", "n", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {},
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.agent_target == "codex"
    assert plan.attention_enabled is True


def test_collect_setup_plan_keeps_attention_opt_in_for_generic_agent():
    answers = iter(["1", "1", "1", "1", "1", "", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {},
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.agent_target == "agents"
    assert plan.attention_enabled is False


def test_collect_setup_plan_does_not_opt_existing_codex_config_into_attention():
    answers = iter(["1", "1", "1", "2", "1", "", "n", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(config_exists=True),
        {},
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.agent_target == "codex"
    assert plan.attention_enabled is False


def test_backend_preflight_rejects_non_english_kokoro_even_when_ready():
    plan = setup_flow.SetupPlan.from_mapping(
        {**valid_plan(), "language": "Turkish", "install_kokoro": False}
    )

    with pytest.raises(setup_flow.SetupContractError, match="English"):
        setup_flow.preflight_backend(plan, environment(), {"model_path": "/custom/model.onnx"})


def test_backend_preflight_allows_unready_english_kokoro_when_install_is_approved():
    plan = setup_flow.SetupPlan.from_mapping(
        {
            **valid_plan(),
            "install_kokoro": True,
            "accept_kokoro_license": True,
        }
    )

    setup_flow.preflight_backend(
        plan,
        environment(kokoro_ready=False, kokoro_detail="model missing"),
        {},
    )


def test_plan_rejects_a_new_custom_command_from_the_setup_bridge():
    with pytest.raises(setup_flow.SetupContractError, match="unknown field"):
        setup_flow.SetupPlan.from_mapping(
            {
                **valid_plan(),
                "tts": "command",
                "command": ["custom-tts", "{text}"],
            }
        )


def test_backend_preflight_accepts_only_an_existing_reviewed_command():
    plan = setup_flow.SetupPlan.from_mapping(
        {**valid_plan(), "tts": "command"}
    )

    setup_flow.preflight_backend(
        plan,
        environment(),
        {"command": ["custom-tts", "{text}"]},
    )

    with pytest.raises(setup_flow.SetupContractError, match="reviewed command"):
        setup_flow.preflight_backend(plan, environment(), {})


def test_kokoro_install_requires_explicit_license_acceptance():
    with pytest.raises(setup_flow.SetupContractError, match="license acceptance"):
        setup_flow.SetupPlan.from_mapping(
            {**valid_plan(), "install_kokoro": True}
        )

    plan = setup_flow.SetupPlan.from_mapping(
        {
            **valid_plan(),
            "install_kokoro": True,
            "accept_kokoro_license": True,
        }
    )

    assert plan.install_kokoro is True
    assert plan.accept_kokoro_license is True


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
    answers = iter(["1", "4", "1", "1", "1", "n", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {"command": ["custom-tts", "{text}"]},
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.tts == "command"
    assert not hasattr(plan, "command")


def test_collect_setup_plan_discloses_backend_and_kokoro_install_details():
    output = []
    answers = iter(["1", "1", "1", "1", "1", "n", "y", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(kokoro_ready=False, kokoro_detail="model missing"),
        {},
        input_fn=lambda _prompt: next(answers),
        output_fn=output.append,
    )

    rendered = "\n".join(output)
    assert "Kokoro local" in rendered
    assert "model missing" in rendered
    assert "System voice (recommended)" in rendered
    assert "https://github.com/thewh1teagle/kokoro-onnx" in rendered
    assert "Apache-2.0" in rendered
    assert "approximately 350 MB" in rendered
    assert plan.install_kokoro is True
    assert plan.accept_kokoro_license is True


def test_review_lines_name_agent_and_non_english_voice_compatibility():
    plan = setup_flow.SetupPlan.from_mapping(
        {
            **valid_plan(),
            "language": "Turkish",
            "tts": "system",
            "agent_target": "claude",
        }
    )

    review = "\n".join(setup_flow.review_lines(plan, environment()))

    assert "Agent: Claude" in review
    assert "matching system voice" in review
    assert "custom TTS" in review


def test_collect_setup_plan_forces_voice_test_when_requested():
    answers = iter(["1", "1", "1", "1", "1", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {},
        force_test=True,
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.test_voice is True


def test_collect_setup_plan_falls_back_from_invalid_speak_mode():
    answers = iter(["1", "1", "", "1", "1", "n", "n", "n"])

    plan = setup_flow.collect_setup_plan(
        environment(),
        {"speak_mode": "legacy_mode"},
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert plan.speak_mode == "final_only"
