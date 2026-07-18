import argparse
import json

from jarvis_line import cli, config_contract, kokoro_say


def test_contract_contains_defaults_fields_and_backends():
    contract = config_contract.contract_document()

    assert contract["version"] == 1
    assert contract["defaults"]["tts"] == "kokoro"
    assert contract["defaults"]["debug_content_logging"] is False
    assert contract["defaults"]["attention_enabled"] is False
    assert contract["defaults"]["cleanup_enabled"] is True
    assert contract["defaults"]["cleanup_interval_hours"] == 24
    assert contract["fields"]["attention_enabled"]["type"] == "boolean"
    assert contract["fields"]["cleanup_enabled"]["type"] == "boolean"
    assert contract["fields"]["cleanup_interval_hours"]["values"] == [24, 168]
    assert contract["fields"]["tts"]["values"] == ["command", "kokoro", "macos", "system"]
    assert contract["ui_options"]["tts"] == ["kokoro", "system", "macos", "command"]
    assert contract["ui_options"]["cleanup_interval_hours"] == [24, 168]
    assert 185 in contract["ui_options"]["system_rate"]
    assert "system" in contract["backends"]
    assert isinstance(contract["backends"]["system"]["supports"], list)
    for backend in contract["backends"].values():
        assert "cleanup_enabled" in backend["supports"]
        assert "cleanup_interval_hours" in backend["supports"]


def test_default_config_is_a_deep_copy():
    first = config_contract.default_config()
    first["line_prefixes"].append("Changed:")

    assert config_contract.default_config()["line_prefixes"] == ["Jarvis line:"]


def test_cli_contract_command_prints_json(capsys):
    assert cli.config_contract_command(argparse.Namespace()) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["defaults"]["audio_worker_max_rss_mb"] == 512


def test_config_contract_parser_routes_command():
    args = cli.build_parser().parse_args(["config", "contract"])

    assert args.func is cli.config_contract_command


def test_kokoro_load_config_merges_canonical_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(kokoro_say, "CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(kokoro_say, "LEGACY_CONFIG_PATH", tmp_path / "missing-legacy.json")

    config = kokoro_say.load_config()

    assert config["tts"] == "kokoro"
    assert config["debug_content_logging"] is False


def test_kokoro_load_config_preserves_user_values(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tts": "system", "volume": 0.4}))
    monkeypatch.setattr(kokoro_say, "CONFIG_PATH", path)
    monkeypatch.setattr(kokoro_say, "LEGACY_CONFIG_PATH", tmp_path / "missing-legacy.json")

    config = kokoro_say.load_config()

    assert config["tts"] == "system"
    assert config["volume"] == 0.4
    assert config["speak_mode"] == "final_only"
    assert config["attention_enabled"] is False
