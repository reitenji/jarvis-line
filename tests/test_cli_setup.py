import argparse
import io
import json
import sys

import pytest

from jarvis_line import cli, setup_flow


def ready_environment(**overrides):
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


def kokoro_codex_plan(**overrides):
    values = {
        "version": 1,
        "language": "English",
        "tts": "kokoro",
        "speak_mode": "final_only",
        "agent_target": "codex",
        "instruction_scope": "project",
        "project_path": "/tmp/project",
        "install_kokoro": True,
        "install_codex_hook": True,
        "start_runtime": True,
    }
    values.update(overrides)
    return setup_flow.SetupPlan.from_mapping(values)


def patch_setup_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "jarvis_line_config.json")
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")


def test_setup_inspect_prints_parseable_versioned_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli, "load_effective_config", lambda default=None: {"tts": "system"})

    assert cli.setup_inspect(argparse.Namespace(json_output=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["config_exists"] is False
    assert payload["current"] == {"tts": "system"}


def test_setup_apply_rejects_oversized_stdin_before_mutation(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("x" * 65_537))
    writes = []
    monkeypatch.setattr(cli, "save_json", lambda *_args: writes.append(True))

    assert cli.setup_apply(argparse.Namespace(stdin=True, json_output=True)) == 2

    assert writes == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "64 KiB" in payload["error"]


def test_save_json_leaves_original_and_cleans_temp_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(cli.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        cli.save_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob(".config.json.*.tmp")) == []


def test_apply_writes_config_once_after_preflight(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(cli, "run_setup_kokoro_install", lambda: calls.append("kokoro") or 0)
    monkeypatch.setattr(cli, "save_json", lambda path, data: calls.append(("write", path, data["tts"])))
    monkeypatch.setattr(cli, "install_codex", lambda _args: calls.append("hook") or 0)
    monkeypatch.setattr(cli, "launch_runtime", lambda _args, selected: calls.append(("runtime", selected)) or 0)
    monkeypatch.setattr(cli, "setup_doctor_json", lambda: {"selected_tts": "kokoro"})

    result = cli.apply_setup_plan(kokoro_codex_plan(), json_mode=True)

    assert result["ok"] is True
    assert calls == [
        "kokoro",
        ("write", cli.CONFIG_PATH, "kokoro"),
        "hook",
        ("runtime", "kokoro"),
    ]


def test_apply_creates_config_backup_once_before_atomic_write(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    cli.CONFIG_PATH.write_text('{"tts": "system"}\n', encoding="utf-8")
    backup = tmp_path / "jarvis_line_config.json.setup.bak"
    monkeypatch.setattr(cli, "setup_doctor_json", lambda: {})

    first = cli.apply_setup_plan(kokoro_codex_plan(install_kokoro=False, install_codex_hook=False, start_runtime=False), json_mode=True)

    assert first["ok"] is True
    assert json.loads(backup.read_text(encoding="utf-8")) == {"tts": "system"}
    backup.write_text('{"preserve": true}\n', encoding="utf-8")
    second = cli.apply_setup_plan(kokoro_codex_plan(install_kokoro=False, install_codex_hook=False, start_runtime=False), json_mode=True)

    assert second["ok"] is True
    assert json.loads(backup.read_text(encoding="utf-8")) == {"preserve": True}


def test_setup_apply_keeps_json_stdout_clean_when_helpers_print(monkeypatch, tmp_path, capsys):
    patch_setup_paths(monkeypatch, tmp_path)
    plan = kokoro_codex_plan(install_kokoro=False, install_codex_hook=True, start_runtime=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "version": plan.version,
        "language": plan.language,
        "tts": plan.tts,
        "speak_mode": plan.speak_mode,
        "agent_target": plan.agent_target,
        "instruction_scope": plan.instruction_scope,
        "project_path": plan.project_path,
        "install_kokoro": plan.install_kokoro,
        "install_codex_hook": plan.install_codex_hook,
        "start_runtime": plan.start_runtime,
    })))
    monkeypatch.setattr(cli, "install_codex", lambda _args: print("hook noise") or 0)
    monkeypatch.setattr(cli, "setup_doctor_json", lambda: print("doctor noise") or {})

    assert cli.setup_apply(argparse.Namespace(stdin=True, json_output=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["version"] == 1


def test_setup_parser_routes_machine_commands_and_preserves_default():
    parser = cli.build_parser()

    inspect = parser.parse_args(["setup", "inspect", "--json"])
    apply = parser.parse_args(["setup", "apply", "--stdin", "--json"])
    default = parser.parse_args(["setup", "--default"])

    assert inspect.func is cli.setup_command
    assert inspect.setup_command == "inspect"
    assert apply.func is cli.setup_command
    assert apply.setup_command == "apply"
    assert default.func is cli.setup_command
    assert default.default is True
