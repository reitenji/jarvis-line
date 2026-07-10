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


def healthy_doctor():
    return {
        "ok": True,
        "selected_backend_ok": True,
        "runtime_ok": True,
        "result": {
            "selected_tts": "kokoro",
            "kokoro": {"ok": True},
            "watcher": {"ok": True},
            "audio_worker": {"ok": True},
        },
    }


def test_setup_inspect_prints_parseable_versioned_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli, "load_effective_config", lambda default=None: {"tts": "system"})

    assert cli.setup_inspect(argparse.Namespace(json_output=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["config_exists"] is False
    assert payload["current"] == {"tts": "system"}


def test_setup_apply_rejects_multibyte_oversized_stdin_before_mutation(monkeypatch, capsys):
    text = "€" * ((setup_flow.MAX_SETUP_PLAN_BYTES // len("€".encode("utf-8"))) + 1)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8"))
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
    monkeypatch.setattr(cli, "setup_doctor_json", healthy_doctor)

    result = cli.apply_setup_plan(kokoro_codex_plan(), json_mode=True)

    assert result["ok"] is True
    assert calls == [
        "kokoro",
        ("write", cli.CONFIG_PATH, "kokoro"),
        "hook",
        ("runtime", "kokoro"),
    ]


def test_run_setup_kokoro_install_downloads_managed_assets_before_dependencies(monkeypatch):
    calls = []

    def download(spec, destination, *, force):
        calls.append(("download", spec.name, destination, force))
        return "downloaded"

    monkeypatch.setattr(cli.kokoro_assets, "download_verified_asset", download)
    monkeypatch.setattr(
        cli,
        "kokoro_install_deps",
        lambda _args, quiet: calls.append(("dependencies", quiet)) or 0,
    )
    monkeypatch.setattr(cli, "managed_kokoro_ready", lambda: (True, "ready"), raising=False)

    assert cli.run_setup_kokoro_install() == 0

    assert calls == [
        ("download", "kokoro-v1.0.onnx", cli.KOKORO_MODEL, False),
        ("download", "voices-v1.0.bin", cli.KOKORO_VOICES, False),
        ("dependencies", True),
    ]


def test_apply_stops_before_config_write_when_managed_kokoro_is_not_ready(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    writes = []
    monkeypatch.setattr(cli.kokoro_assets, "download_verified_asset", lambda *_args, **_kwargs: "downloaded")
    monkeypatch.setattr(cli, "kokoro_install_deps", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "managed_kokoro_ready", lambda: (False, "imports missing"), raising=False)
    monkeypatch.setattr(cli, "save_json", lambda *_args: writes.append(True))

    result = cli.apply_setup_plan(kokoro_codex_plan(), json_mode=True)

    assert result["ok"] is False
    assert result["error"] == "Kokoro preflight failed"
    assert writes == []


def test_apply_installed_kokoro_writes_managed_paths(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    written = []
    monkeypatch.setattr(cli, "load_effective_config", lambda _default=None: {
        "tts": "system",
        "model_path": "/custom/model.onnx",
        "voices_path": "/custom/voices.bin",
    })
    monkeypatch.setattr(cli, "run_setup_kokoro_install", lambda: 0)
    monkeypatch.setattr(cli, "save_json", lambda _path, config: written.append(config))
    monkeypatch.setattr(cli, "install_codex", lambda _args: 0)
    monkeypatch.setattr(cli, "launch_runtime", lambda _args, _selected: 0)
    monkeypatch.setattr(cli, "setup_doctor_json", healthy_doctor)

    result = cli.apply_setup_plan(kokoro_codex_plan(), json_mode=True)

    assert result["ok"] is True
    assert written[0]["model_path"] == str(cli.KOKORO_MODEL)
    assert written[0]["voices_path"] == str(cli.KOKORO_VOICES)


def test_apply_kokoro_without_install_requires_current_backend_readiness(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    writes = []
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (False, "model missing"))
    monkeypatch.setattr(cli, "save_json", lambda *_args: writes.append(True))

    result = cli.apply_setup_plan(
        kokoro_codex_plan(install_kokoro=False, install_codex_hook=False, start_runtime=False),
        json_mode=True,
    )

    assert result["ok"] is False
    assert result["error"] == "Kokoro preflight failed"
    assert writes == []


def test_apply_creates_config_backup_once_before_atomic_write(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    cli.CONFIG_PATH.write_text('{"tts": "system"}\n', encoding="utf-8")
    backup = tmp_path / "jarvis_line_config.json.setup.bak"
    monkeypatch.setattr(cli, "setup_doctor_json", healthy_doctor)

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
    monkeypatch.setattr(cli, "setup_doctor_json", lambda: print("doctor noise") or healthy_doctor())

    assert cli.setup_apply(argparse.Namespace(stdin=True, json_output=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["version"] == 1


def test_apply_runs_healthy_doctor_before_optional_voice_test(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cli, "setup_doctor_json", lambda: calls.append("doctor") or healthy_doctor())
    monkeypatch.setattr(
        cli,
        "tts_test",
        lambda _args, quiet: calls.append("voice") or 0,
    )

    result = cli.apply_setup_plan(
        kokoro_codex_plan(
            install_kokoro=False,
            install_codex_hook=False,
            start_runtime=False,
            test_voice=True,
        ),
        json_mode=True,
    )

    assert result["ok"] is True
    assert calls == ["doctor", "voice"]


def test_apply_skips_runtime_health_gate_when_runtime_start_is_not_requested(
    monkeypatch, tmp_path
):
    patch_setup_paths(monkeypatch, tmp_path)
    stopped_runtime_doctor = {
        "ok": False,
        "selected_backend_ok": True,
        "runtime_ok": False,
        "result": {
            "selected_tts": "system",
            "system_tts": {"ok": True},
            "watcher": {"ok": False},
            "audio_worker": {"ok": False},
        },
    }
    monkeypatch.setattr(cli, "setup_doctor_json", lambda: stopped_runtime_doctor)

    result = cli.apply_setup_plan(
        kokoro_codex_plan(
            tts="system",
            install_kokoro=False,
            install_codex_hook=False,
            start_runtime=False,
        ),
        json_mode=True,
    )

    doctor_step = next(step for step in result["steps"] if step["name"] == "doctor")
    assert result["ok"] is True
    assert doctor_step["ok"] is True
    assert doctor_step["status"] == "healthy-for-requested-scope"
    assert doctor_step["scope"] == "backend_and_config"
    assert doctor_step["result"]["runtime_ok"] is False


def test_setup_doctor_rejects_success_exit_when_selected_backend_is_unhealthy(monkeypatch):
    def doctor_with_unhealthy_backend(_args):
        print(json.dumps({
            "selected_tts": "kokoro",
            "kokoro": {"ok": False},
            "system_tts": {"ok": True},
            "watcher": {"ok": True},
            "audio_worker": {"ok": True},
        }))
        return 0

    monkeypatch.setattr(cli, "doctor", doctor_with_unhealthy_backend)

    result = cli.setup_doctor_json()

    assert result["ok"] is False
    assert result["selected_backend_ok"] is False
    assert result["runtime_ok"] is True


def test_setup_doctor_rejects_success_exit_when_runtime_is_unhealthy(monkeypatch):
    def doctor_with_unhealthy_runtime(_args):
        print(json.dumps({
            "selected_tts": "kokoro",
            "kokoro": {"ok": True},
            "watcher": {"ok": False},
            "audio_worker": {"ok": True},
        }))
        return 0

    monkeypatch.setattr(cli, "doctor", doctor_with_unhealthy_runtime)

    result = cli.setup_doctor_json()

    assert result["ok"] is False
    assert result["selected_backend_ok"] is True
    assert result["runtime_ok"] is False


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


def test_wizard_decline_leaves_files_and_runtime_unchanged(monkeypatch, tmp_path, capsys):
    patch_setup_paths(monkeypatch, tmp_path)
    original = {"tts": "system", "line_language": "English"}
    cli.save_json(cli.CONFIG_PATH, original)
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli.setup_flow, "collect_setup_plan", lambda *_args, **_kwargs: kokoro_codex_plan())
    monkeypatch.setattr(cli.setup_flow, "prompt_yes_no", lambda *_args, **_kwargs: False)
    applied = []
    monkeypatch.setattr(cli, "apply_setup_plan", lambda *_args, **_kwargs: applied.append(True))

    assert cli.setup_wizard(argparse.Namespace(test=False)) == 0

    assert cli.load_json(cli.CONFIG_PATH, {}) == original
    assert applied == []
    assert "No changes were made" in capsys.readouterr().out


def test_wizard_applies_the_collected_plan_through_existing_pipeline(monkeypatch, capsys):
    plan = kokoro_codex_plan(start_runtime=False)
    result = {"ok": True, "steps": [], "instruction": {}}
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli, "load_effective_config", lambda _default=None: {})
    monkeypatch.setattr(cli.setup_flow, "collect_setup_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(cli.setup_flow, "prompt_yes_no", lambda *_args, **_kwargs: True)
    calls = []
    monkeypatch.setattr(
        cli,
        "apply_setup_plan",
        lambda received, *, json_mode: calls.append((received, json_mode)) or result,
    )
    monkeypatch.setattr(cli, "print_setup_result", lambda received: calls.append((received, "printed")))

    assert cli.setup_wizard(argparse.Namespace(test=False)) == 0

    assert calls == [(plan, False), (result, "printed")]
    assert "Review setup" in capsys.readouterr().out


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_wizard_cancellation_before_confirmation_has_no_side_effects(monkeypatch, capsys, error):
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli.setup_flow, "collect_setup_plan", lambda *_args, **_kwargs: (_ for _ in ()).throw(error()))
    monkeypatch.setattr(cli, "apply_setup_plan", lambda *_args, **_kwargs: pytest.fail("must not apply"))

    assert cli.setup_wizard(argparse.Namespace(test=False)) == 130

    assert "No changes were made" in capsys.readouterr().err


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_wizard_reports_interruption_after_real_apply(monkeypatch, tmp_path, capsys, error):
    patch_setup_paths(monkeypatch, tmp_path)
    plan = kokoro_codex_plan(
        tts="system",
        install_kokoro=False,
        install_codex_hook=False,
        start_runtime=False,
    )
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli.setup_flow, "collect_setup_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(cli.setup_flow, "prompt_yes_no", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        cli,
        "setup_doctor_json",
        lambda: (_ for _ in ()).throw(error()),
    )

    assert cli.setup_wizard(argparse.Namespace(test=False)) == 130

    assert cli.load_json(cli.CONFIG_PATH, {})["tts"] == "system"
    stderr = capsys.readouterr().err
    assert "Setup interrupted" in stderr
    assert "Some approved setup steps may have applied" in stderr
    assert "jarvis-line doctor" in stderr
    assert "jarvis-line status" in stderr
    assert "No changes were made" not in stderr


def test_wizard_passes_test_flag_to_plan_collection(monkeypatch):
    plan = kokoro_codex_plan(start_runtime=False, test_voice=True)
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli, "load_effective_config", lambda _default=None: {})
    seen = []
    monkeypatch.setattr(
        cli.setup_flow,
        "collect_setup_plan",
        lambda *_args, **kwargs: seen.append(kwargs["force_test"]) or plan,
    )
    monkeypatch.setattr(cli.setup_flow, "prompt_yes_no", lambda *_args, **_kwargs: False)

    assert cli.setup_wizard(argparse.Namespace(test=True)) == 0

    assert seen == [True]
