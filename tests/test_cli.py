import argparse

import pytest

from jarvis_line import cli


def test_validate_rejects_macos_kokoro_fields():
    warnings = cli.validate_config({"tts": "macos", "speed": 1.2, "lang": "en-gb"})

    assert "speed is ignored by macos" in warnings
    assert "lang is ignored by macos" in warnings


def test_validate_rejects_system_kokoro_fields():
    warnings = cli.validate_config({"tts": "system", "speed": 1.2, "lang": "en-gb"})

    assert "speed is ignored by system" in warnings
    assert "lang is ignored by system" in warnings


def test_system_voice_settings_are_supported():
    warnings = cli.validate_config({"tts": "system", "system_voice": None, "system_rate": None})

    assert "system_voice is ignored by system" not in warnings
    assert "system_rate is ignored by system" not in warnings


def test_setup_default_warns_and_falls_back_to_system(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    watcher = tmp_path / "watcher.py"
    worker = tmp_path / "audio_worker.py"
    watcher.write_text("")
    worker.write_text("")
    monkeypatch.setattr(cli, "WATCHER_PATH", watcher)
    monkeypatch.setattr(cli, "WORKER_PATH", worker)
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (False, "kokoro model missing"))
    monkeypatch.setattr(cli, "system_tts_ready", lambda: (True, "say"))
    monkeypatch.setattr(cli, "watcher_command", lambda: ["python", "-m", "jarvis_line.watcher", "--launch"])

    class Proc:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Proc())

    assert cli.setup_default(argparse.Namespace(test=False)) == 0
    cfg = cli.load_json(tmp_path / "config.json", {})
    out = capsys.readouterr().out

    assert cfg["tts"] == "system"
    assert "[WARN] Kokoro is not ready" in out
    assert "Selected TTS: system" in out


def test_init_project_runs_setup_without_agent_hook_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")

    calls = []

    def fake_setup(args):
        calls.append(("setup", args.test))
        cli.save_json(cli.CONFIG_PATH, {"tts": "system"})
        return 0

    monkeypatch.setattr(cli, "setup_default", fake_setup)

    rc = cli.init_project(argparse.Namespace(
        language="English",
        target="agents",
        path=None,
        apply_tts=False,
        codex=False,
        no_instructions=False,
        write_instructions=False,
        test=True,
    ))

    assert rc == 0
    assert calls == [("setup", True)]
    assert not (tmp_path / "hooks.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    assert 'jarvis-line instructions print agents --language "English"' in capsys.readouterr().out


def test_init_project_installs_codex_hook_when_requested(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli, "setup_default", lambda args: cli.save_json(cli.CONFIG_PATH, {"tts": "system"}) or 0)

    rc = cli.init_project(argparse.Namespace(
        language="English",
        target="agents",
        path=None,
        apply_tts=False,
        codex=True,
        no_instructions=True,
        write_instructions=False,
        test=False,
    ))

    assert rc == 0
    assert "SessionStart" in cli.load_json(tmp_path / "hooks.json", {})["hooks"]


def test_init_project_can_write_instructions_when_explicit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli, "setup_default", lambda args: cli.save_json(cli.CONFIG_PATH, {"tts": "system"}) or 0)

    rc = cli.init_project(argparse.Namespace(
        language="English",
        target="agents",
        path=None,
        apply_tts=False,
        codex=False,
        no_instructions=False,
        write_instructions=True,
        test=False,
    ))

    assert rc == 0
    assert "Jarvis Line" in (tmp_path / "AGENTS.md").read_text()


def test_command_allows_custom_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"tts": "command", "command": "echo {text}"})

    rc = cli.config_set(argparse.Namespace(key="custom_voice_id", value="abc"))

    assert rc == 0
    assert cli.load_json(tmp_path / "config.json", {})["custom_voice_id"] == "abc"


def test_config_defaults_and_schema(capsys):
    def as_posix(value):
        return str(value).replace("\\", "/")

    assert as_posix(cli.DEFAULT_KOKORO_CONFIG["model_path"]).endswith(".jarvis-line/tts/kokoro-models/kokoro-v1.0.onnx")
    assert as_posix(cli.DEFAULT_KOKORO_CONFIG["voices_path"]).endswith(".jarvis-line/tts/kokoro-models/voices-v1.0.bin")
    assert as_posix(cli.DEFAULT_KOKORO_CONFIG["temp_dir"]).endswith(".jarvis-line/tts/generated")

    assert cli.config_defaults(argparse.Namespace(preset="system")) == 0
    defaults = capsys.readouterr().out
    assert '"tts": "system"' in defaults
    assert "system_voice" in defaults

    assert cli.config_schema(argparse.Namespace(preset="kokoro")) == 0
    schema = capsys.readouterr().out
    assert "Local Kokoro ONNX voice" in schema
    assert '"speed"' in schema


def test_update_check_reports_newer_version(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_index_url": "https://example.invalid/json"})
    monkeypatch.setattr(cli, "fetch_latest_version", lambda url: "9.9.9")

    rc = cli.update_check(argparse.Namespace(source=None, index_url=None, repo=None))
    out = capsys.readouterr().out

    assert rc == 10
    assert "Update available" in out
    assert cli.load_json(tmp_path / "config.json", {})["last_update_check_ts"] > 0


def test_update_check_from_git_reports_latest_tag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {
        "update_source": "git",
        "update_git_repo": "ssh://git@github.com-personal/me/jarvis-line.git",
    })
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: "0.1.0b9")

    rc = cli.update_check(argparse.Namespace(source=None, index_url=None, repo=None))
    out = capsys.readouterr().out

    assert rc == 10
    assert "Latest version: 0.1.0b9" in out
    assert "Update available" in out


def test_update_check_from_git_uses_default_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_source": "git"})
    seen = []
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: seen.append(repo) or cli.__version__)

    rc = cli.update_check(argparse.Namespace(source=None, index_url=None, repo=None))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Jarvis Line is up to date." in out
    assert seen == [cli.DEFAULT_GIT_REPO]


def test_fetch_latest_git_version_uses_semver_tags(monkeypatch):
    class Proc:
        returncode = 0
        stdout = "\n".join([
            "aaa\trefs/tags/v0.1.0b2",
            "bbb\trefs/tags/v0.1.0b4",
            "ccc\trefs/tags/not-a-version",
            "ddd\trefs/tags/v0.1.0",
        ])

    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or Proc())

    assert cli.fetch_latest_git_version("ssh://example/repo.git") == "0.1.0"
    assert calls[0][0][0] == ["git", "ls-remote", "--tags", "--refs", "--", "ssh://example/repo.git"]


def test_fetch_latest_git_version_rejects_option_like_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.fetch_latest_git_version("--upload-pack=/tmp/pwn.sh") is None
    assert calls == []


def test_update_apply_from_git_installs_latest_tag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {
        "update_source": "git",
        "update_git_repo": "ssh://git@github.com-personal/me/jarvis-line.git",
        "update_git_ref": "latest",
    })
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: "9.9.9")
    calls = []

    class Proc:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd: calls.append(cmd) or Proc())

    rc = cli.update_apply(argparse.Namespace(source=None, pre=False, package=None, index_url=None, repo=None, ref=None))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Latest version: 9.9.9" in out
    assert calls[0][-1] == "git+ssh://git@github.com-personal/me/jarvis-line.git@v9.9.9"


def test_update_apply_from_git_skips_when_current(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_source": "git", "update_git_ref": "v0.1.0b1"})
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: cli.__version__)
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd: calls.append(cmd))

    rc = cli.update_apply(argparse.Namespace(source=None, pre=False, package=None, index_url=None, repo=None, ref=None))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Jarvis Line is up to date." in out
    assert calls == []


def test_update_apply_from_git_allows_explicit_ref(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_source": "git"})
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: cli.__version__)
    calls = []

    class Proc:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd: calls.append(cmd) or Proc())

    rc = cli.update_apply(argparse.Namespace(source=None, pre=False, package=None, index_url=None, repo=None, ref="v9.9.9"))

    assert rc == 0
    assert calls[0][-1] == f"git+{cli.DEFAULT_GIT_REPO}@v9.9.9"


def test_update_configure(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {})

    assert cli.update_configure(argparse.Namespace(
        enabled="false",
        interval_hours=12,
        index_url="https://example.com/pkg.json",
    )) == 0
    cfg = cli.load_json(tmp_path / "config.json", {})

    assert cfg["update_check_enabled"] is False
    assert cfg["update_check_interval_hours"] == 12
    assert cfg["update_index_url"] == "https://example.com/pkg.json"


def test_update_install_from_git_resolves_latest_ref(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_source": "git"})
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: "9.9.9")
    calls = []

    class Proc:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd: calls.append(cmd) or Proc())

    rc = cli.update_install(argparse.Namespace(source=None, pre=False, package=None, repo=None, ref=None))

    assert rc == 0
    assert calls[0][-1] == f"git+{cli.DEFAULT_GIT_REPO}@v9.9.9"


def test_update_install_from_git_builds_pip_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_source": "git", "update_git_repo": "ssh://git@github.com-personal/me/jarvis-line.git", "update_git_ref": "main"})
    calls = []

    class Proc:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd: calls.append(cmd) or Proc())

    assert cli.update_install(argparse.Namespace(source=None, pre=False, package=None, repo=None, ref=None)) == 0
    assert calls[0][-1] == "git+ssh://git@github.com-personal/me/jarvis-line.git@main"


def test_update_install_from_git_rejects_option_like_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_source": "git", "update_git_repo": "--upload-pack=/tmp/pwn.sh", "update_git_ref": "main"})
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd: calls.append(cmd))

    assert cli.update_install(argparse.Namespace(source=None, pre=False, package=None, repo=None, ref=None)) == 1
    assert "does not start with '-'" in capsys.readouterr().out
    assert calls == []


def test_top_level_help_is_product_friendly(capsys):
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "Voice notifications for AI coding agents" in out
    assert "Quick start:" in out
    assert 'jarvis-line init --codex --language "English"' in out
    assert "support-report" in out


def test_help_command_prints_top_level_help(capsys):
    parser = cli.build_parser()
    args = parser.parse_args(["help"])

    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "jarvis-line --help" in out
    assert "Common commands:" in out


def test_find_runtime_pids_matches_packaged_audio_worker(monkeypatch):
    monkeypatch.setattr(cli, "CODEX_HOME", cli.Path("/Users/me/.codex"))
    monkeypatch.setattr(cli, "KOKORO_VENV", cli.Path("/Users/me/.jarvis-line/tts/kokoro-venv"))
    monkeypatch.setattr(cli, "process_lines", lambda: [
        "101 /usr/bin/python /Users/me/.jarvis-line/tts/kokoro-venv/lib/python3.11/site-packages/jarvis_line/audio_worker.py",
        "102 /usr/bin/python /Users/me/.gemini/hooks/jarvis_line_watcher.py --watch",
    ])

    assert cli.find_runtime_pids("audio_worker") == [101]


def test_profiles_and_prefix_helpers(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "CONFIG_PROFILES_PATH", tmp_path / "profiles.json")
    cli.save_json(tmp_path / "config.json", {"tts": "system", "line_prefixes": ["Jarvis line:"]})

    assert cli.prefix_add(argparse.Namespace(prefix="Friday line:")) == 0
    assert "Friday line:" in cli.load_json(tmp_path / "config.json", {})["line_prefixes"]
    assert cli.prefix_remove(argparse.Namespace(prefix="Friday line:")) == 0
    assert "Friday line:" not in cli.load_json(tmp_path / "config.json", {})["line_prefixes"]

    assert cli.profile_save(argparse.Namespace(name="work")) == 0
    cli.save_json(tmp_path / "config.json", {"tts": "command", "command": "echo {text}"})
    assert cli.profile_use(argparse.Namespace(name="work")) == 0
    assert cli.load_json(tmp_path / "config.json", {})["tts"] == "system"


def test_instruction_replace_and_doctor(tmp_path, capsys):
    path = tmp_path / "AGENTS.md"
    path.write_text("hello\n\n## Jarvis Line\nold\n\n## Other\nkeep\n")

    assert cli.instructions_install(argparse.Namespace(
        target="agents",
        language="English",
        path=str(path),
        sync_config=False,
        apply_tts=False,
        replace=True,
        style="minimal",
    )) == 0
    text = path.read_text()

    assert "old" not in text
    assert "## Other" in text
    assert cli.instructions_doctor(argparse.Namespace(target="agents", path=str(path))) == 0


def test_status_smoke(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(cli, "LATEST_PATH", tmp_path / "latest.json")
    cli.save_json(tmp_path / "config.json", {"tts": "kokoro"})
    cli.save_json(tmp_path / "state.json", {})
    cli.save_json(tmp_path / "queue.json", {"jobs": []})
    cli.save_json(tmp_path / "latest.json", {"sessions": {}})

    assert cli.status(argparse.Namespace()) == 0
    assert "Jarvis Line status" in capsys.readouterr().out


def test_install_uninstall_codex_uses_package_command(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli, "KOKORO_PY", tmp_path / "python")
    cli.save_json(tmp_path / "hooks.json", {"hooks": {}})

    assert cli.install_codex(argparse.Namespace()) == 0
    hooks = cli.load_json(tmp_path / "hooks.json", {})
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "jarvis_line.watcher" in command

    assert cli.uninstall_codex(argparse.Namespace()) == 0
    hooks = cli.load_json(tmp_path / "hooks.json", {})
    assert "SessionStart" not in hooks["hooks"]


def test_migrate_config_writes_next_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "jarvis_line_config.json")
    monkeypatch.setattr(cli, "LEGACY_CONFIG_PATH", tmp_path / "kokoro_tts_config.json")
    cli.save_json(tmp_path / "kokoro_tts_config.json", {"tts": "kokoro", "speed": 1.1})

    assert cli.migrate_config(argparse.Namespace(remove_legacy=False)) == 0
    migrated = cli.load_json(tmp_path / "jarvis_line_config.json", {})
    assert migrated["speed"] == 1.1
    assert migrated["config_version"] == 1


def test_kokoro_configure_writes_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    model = tmp_path / "model.onnx"
    voices = tmp_path / "voices.bin"

    assert cli.kokoro_configure(argparse.Namespace(
        model_path=str(model),
        voices_path=str(voices),
        voice="bm_george",
        lang="en-gb",
    )) == 0
    cfg = cli.load_json(tmp_path / "config.json", {})

    assert cfg["tts"] == "kokoro"
    assert cfg["model_path"] == str(model)
    assert cfg["voices_path"] == str(voices)
    assert cfg["voice"] == "bm_george"


def test_kokoro_ready_uses_configured_model_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "KOKORO_PY", tmp_path / "python")
    model = tmp_path / "custom-model.onnx"
    voices = tmp_path / "custom-voices.bin"
    cli.save_json(tmp_path / "config.json", {"model_path": str(model), "voices_path": str(voices)})
    cli.KOKORO_PY.write_text("")
    model.write_text("")

    ready, reason = cli.kokoro_ready()

    assert ready is False
    assert reason == "kokoro voices missing"


def test_instruction_snippet_language_modes():
    english = cli.instruction_snippet("agents", "English")
    legacy_english = cli.instruction_snippet("agents", "en")
    turkish = cli.instruction_snippet("agents", "Turkish")
    german = cli.instruction_snippet("agents", "German")

    assert "must be written in English" in english
    assert "must be written in English" in legacy_english
    assert "must be written in Turkish" in turkish
    assert "must be written in German" in german
    assert "Jarvis line:" in english
    assert "Include exactly one `Jarvis line: ...` line in every final response." in english
    assert "optional `Jarvis line: ...` line in commentary" in english
    assert "Before sending any final response" in english


def test_instruction_parser_accepts_custom_language_name():
    parser = cli.build_parser()
    args = parser.parse_args(["instructions", "print", "agents", "--language", "Brazilian Portuguese"])

    assert args.language == "Brazilian Portuguese"


@pytest.mark.parametrize("language", ["en", "tr", "user"])
def test_instruction_parser_rejects_language_shortcuts(language, capsys):
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["instructions", "print", "agents", "--language", language])

    assert exc.value.code == 2
    assert "Use a full language name" in capsys.readouterr().err


def test_instructions_install_is_idempotent(tmp_path):
    path = tmp_path / "AGENTS.md"

    assert cli.instructions_install(argparse.Namespace(target="agents", language="English", path=str(path))) == 0
    first = path.read_text()
    assert cli.instructions_install(argparse.Namespace(target="agents", language="English", path=str(path))) == 0

    assert path.read_text() == first


def test_redaction_masks_secret_and_home(monkeypatch):
    redacted = cli.redact_dict({
        "api_key": "secret",
        "path": str(cli.Path.home() / "x"),
        "message": "Jarvis line: token sk-proj-abcdef1234567890",
    })

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["path"].startswith("~")
    assert "sk-proj-abcdef1234567890" not in redacted["message"]
    assert "[REDACTED]" in redacted["message"]


def test_support_report_writes_issue_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "LEGACY_CONFIG_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(cli, "LATEST_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(cli, "WATCHER_LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(cli, "AUDIO_WORKER_LOG_PATH", tmp_path / "worker.log")
    cli.save_json(cli.CONFIG_PATH, {"tts": "command", "api_key": "secret", "command": "echo {text}"})
    cli.save_json(cli.STATE_PATH, {})
    cli.save_json(cli.QUEUE_PATH, {"jobs": [{
        "message_id": "m1",
        "session_key": str(tmp_path / "session"),
        "phase": "final",
        "enqueued_ts_ms": 1,
        "jarvis_line": "Jarvis line: deploy token sk-proj-queueSECRET1234567890",
    }]})
    cli.save_json(cli.LATEST_PATH, {"sessions": {str(tmp_path / "session"): {
        "latest": {"phase": "final"},
        "latest_final": {
            "message_id": "m1",
            "jarvis_line": "Jarvis line: password latestSECRET123456",
        },
    }}})
    cli.WATCHER_LOG_PATH.write_text("1 queued-audio token=SENSITIVEVALUE line=Jarvis token sk-proj-logSECRET1234567890\n")
    cli.AUDIO_WORKER_LOG_PATH.write_text("1 worker-start password=SENSITIVEVALUE line=secret workerSECRET123456\n")
    output = tmp_path / "issue.md"

    assert cli.support_report(argparse.Namespace(output=str(output), full=False, max_log_bytes=5_000_000, since=None)) == 0
    text = output.read_text()

    assert "## Jarvis Line Support Report" in text
    assert "```json" in text
    assert "```text" in text
    assert '"api_key": "[REDACTED]"' in text
    assert "SENSITIVEVALUE" not in text
    assert "sk-proj-queueSECRET1234567890" not in text
    assert "latestSECRET123456" not in text
    assert "sk-proj-logSECRET1234567890" not in text
    assert "workerSECRET123456" not in text
    assert "[REDACTED]" in text

def test_support_report_uses_unambiguous_fences_for_log_backticks(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "LEGACY_CONFIG_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(cli, "LATEST_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(cli, "WATCHER_LOG_PATH", tmp_path / "watcher.log")
    monkeypatch.setattr(cli, "AUDIO_WORKER_LOG_PATH", tmp_path / "worker.log")
    cli.save_json(cli.CONFIG_PATH, {"tts": "system"})
    cli.save_json(cli.STATE_PATH, {})
    cli.save_json(cli.QUEUE_PATH, {"jobs": []})
    cli.save_json(cli.LATEST_PATH, {"sessions": {}})
    cli.WATCHER_LOG_PATH.write_text("1 notify-turn-complete file=/tmp/session\n```\n### injected\n```x.jsonl\n")
    cli.AUDIO_WORKER_LOG_PATH.write_text("")
    output = tmp_path / "issue.md"

    assert cli.support_report(argparse.Namespace(output=str(output), full=False, max_log_bytes=5_000_000, since=None)) == 0
    text = output.read_text()

    assert "\n### Watcher Log\n````text\n1 notify-turn-complete file=/tmp/session\n```\n### injected\n```x.jsonl\n````\n" in text


def test_filter_lines_since_accepts_fractional_timestamps(monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: 200.0)

    lines = [
        "139.999 old fractional",
        "140 old integer",
        "140.001 recent fractional",
        "unparseable line should remain",
    ]

    assert cli.filter_lines_since(lines, 60) == [
        "140 old integer",
        "140.001 recent fractional",
        "unparseable line should remain",
    ]


def test_filter_lines_since_accepts_fractional_timestamps(monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: 200.0)

    lines = [
        "139.999 old fractional",
        "140 old integer",
        "140.001 recent fractional",
        "unparseable line should remain",
    ]

    assert cli.filter_lines_since(lines, 60) == [
        "140 old integer",
        "140.001 recent fractional",
        "unparseable line should remain",
    ]


def test_support_bundle_command_is_not_available():
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["support-bundle"])

    assert exc.value.code == 2


def test_language_sync_warns_for_turkish_kokoro(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"tts": "kokoro", "lang": "en-gb"})

    cli.sync_language_config("Turkish", apply_tts=False)
    cfg = cli.load_json(tmp_path / "config.json", {})

    assert cfg["line_language"] == "Turkish"
    assert any("does not support Turkish" in warning for warning in cli.validate_config(cfg))


def test_language_sync_can_apply_tts_for_turkish(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"tts": "kokoro", "lang": "en-gb", "command": "echo {text}"})

    cli.sync_language_config("Turkish", apply_tts=True)
    cfg = cli.load_json(tmp_path / "config.json", {})

    assert cfg["line_language"] == "Turkish"
    assert cfg["tts"] == "command"
