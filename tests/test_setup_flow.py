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


def test_plan_rejects_unknown_fields_and_short_language_codes():
    with pytest.raises(setup_flow.SetupContractError, match="unknown field"):
        setup_flow.SetupPlan.from_mapping(
            {**valid_plan(), "instruction_path": "/tmp/AGENTS.md"}
        )
    with pytest.raises(setup_flow.SetupContractError, match="full language name"):
        setup_flow.SetupPlan.from_mapping({**valid_plan(), "language": "tr"})
