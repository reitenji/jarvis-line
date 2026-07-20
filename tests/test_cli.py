import argparse
import contextlib
import hashlib
import json
import types

import pytest

from jarvis_line import cleanup, cli


def reliability_result_snapshot():
    return {
        "version": 1,
        "generated_at_ms": 200_000,
        "health": "healthy",
        "runtime": {},
        "queue": {},
        "tts": {},
        "deliveries": [],
        "recommendations": [],
    }


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
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
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


def test_setup_default_uses_system_for_turkish_even_when_kokoro_is_ready(monkeypatch):
    current = {"tts": "kokoro", "line_language": "Turkish", "custom_setting": True}
    saved = []
    launched = []
    loads = []
    monkeypatch.setattr(cli, "load_effective_config", lambda default=None: loads.append(default) or current)
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cli, "system_tts_ready", lambda: (True, "say"))
    monkeypatch.setattr(cli, "save_json", lambda path, cfg: saved.append((path, cfg)))
    monkeypatch.setattr(cli, "launch_runtime", lambda _args, selected: launched.append(selected) or 0)

    assert cli.setup_default(argparse.Namespace(test=False)) == 0

    assert loads == [{}]
    assert saved[0][1]["tts"] == "system"
    assert saved[0][1]["line_language"] == "Turkish"
    assert saved[0][1]["custom_setting"] is True
    assert launched == ["system"]


def test_setup_default_leaves_turkish_unchanged_when_system_tts_is_unavailable(monkeypatch, capsys):
    current = {"tts": "kokoro", "line_language": "Turkish"}
    monkeypatch.setattr(cli, "load_effective_config", lambda default=None: current)
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cli, "system_tts_ready", lambda: (False, "say missing"))
    monkeypatch.setattr(cli, "save_json", lambda *_args: pytest.fail("must not save"))
    monkeypatch.setattr(cli, "launch_runtime", lambda *_args: pytest.fail("must not launch"))

    assert cli.setup_default(argparse.Namespace(test=False)) == 1

    assert "System TTS is not ready for Turkish: say missing" in capsys.readouterr().out


def test_setup_default_keeps_english_kokoro_behavior(monkeypatch):
    current = {"tts": "system", "line_language": "English", "custom_setting": True}
    saved = []
    launched = []
    monkeypatch.setattr(cli, "load_effective_config", lambda default=None: current)
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cli, "system_tts_ready", lambda: pytest.fail("must not check system TTS"))
    monkeypatch.setattr(cli, "save_json", lambda path, cfg: saved.append((path, cfg)))
    monkeypatch.setattr(cli, "launch_runtime", lambda _args, selected: launched.append(selected) or 0)

    assert cli.setup_default(argparse.Namespace(test=False)) == 0

    assert saved[0][1]["tts"] == "kokoro"
    assert saved[0][1]["line_language"] == "English"
    assert saved[0][1]["custom_setting"] is True
    assert launched == ["kokoro"]


def test_setup_default_falls_back_to_english_for_invalid_configured_language(monkeypatch):
    saved = []
    launched = []
    monkeypatch.setattr(cli, "load_effective_config", lambda default=None: {"line_language": "tr"})
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cli, "system_tts_ready", lambda: pytest.fail("must not check system TTS"))
    monkeypatch.setattr(cli, "save_json", lambda path, cfg: saved.append((path, cfg)))
    monkeypatch.setattr(cli, "launch_runtime", lambda _args, selected: launched.append(selected) or 0)

    assert cli.setup_default(argparse.Namespace(test=False)) == 0

    assert saved[0][1]["tts"] == "kokoro"
    assert saved[0][1]["line_language"] == "English"
    assert launched == ["kokoro"]


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
    monkeypatch.setattr(cli, "enable_codex_hooks_feature", lambda: True)
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
    assert cli.DEFAULT_KOKORO_CONFIG["audio_worker_idle_exit_seconds"] == 60
    assert cli.DEFAULT_KOKORO_CONFIG["audio_worker_max_rss_mb"] == 512

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
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: "0.8.1")

    rc = cli.update_check(argparse.Namespace(source=None, index_url=None, repo=None))
    out = capsys.readouterr().out

    assert rc == 10
    assert "Latest version: 0.8.1" in out
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
    assert calls[0][-1] == "git+ssh://git@github.com-personal/me/jarvis-line.git@refs/tags/v9.9.9"


def test_update_apply_from_git_ignores_configured_ref_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(tmp_path / "config.json", {"update_source": "git", "update_git_ref": "v0.1.0b1"})
    monkeypatch.setattr(cli, "fetch_latest_git_version", lambda repo: cli.__version__)
    calls = []

    class Proc:
        returncode = 0

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd: calls.append(cmd) or Proc())

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
    assert calls[0][-1] == f"git+{cli.DEFAULT_GIT_REPO}@refs/tags/v9.9.9"


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
    monkeypatch.setattr(cli, "PACKAGE_DIR", cli.Path("/Users/me/projects/jarvis-line/src/jarvis_line"))
    monkeypatch.setattr(cli, "process_lines", lambda: [
        "101 /usr/bin/python /Users/me/.jarvis-line/tts/kokoro-venv/lib/python3.11/site-packages/jarvis_line/audio_worker.py",
        "102 /usr/bin/python /Users/me/projects/jarvis-line/src/jarvis_line/audio_worker.py",
        "103 /usr/bin/python /tmp/not-ours/jarvis_line/audio_worker.py",
        "102 /usr/bin/python /Users/me/.gemini/hooks/jarvis_line_watcher.py --watch",
    ])

    assert cli.find_runtime_pids("audio_worker") == [101, 102]


def test_runtime_stop_marks_runtime_stopped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
    cli.save_json(tmp_path / "state.json", {
        "__watcher__": {"pid": 201},
        "__audio_worker__": {"pid": 202},
    })
    monkeypatch.setattr(cli, "find_runtime_pids", lambda kind: [])
    killed = []
    monkeypatch.setattr(cli, "terminate_pid", lambda pid: killed.append(pid))

    assert cli.runtime_stop(argparse.Namespace()) == 0

    state = cli.load_json(tmp_path / "state.json", {})
    assert state["__runtime__"]["stopped"] is True
    assert sorted(killed) == [201, 202]
    assert "Stopped Jarvis Line runtime." in capsys.readouterr().out


def test_diagnostics_snapshot_command_outputs_versioned_json(monkeypatch, capsys):
    snapshot = reliability_result_snapshot()
    monkeypatch.setattr(cli, "reliability_snapshot", lambda: snapshot)

    rc = cli.diagnostics_snapshot_command(argparse.Namespace(json_output=True))

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == snapshot


def test_prune_expired_recovery_preserves_active_jobs(tmp_path, monkeypatch, capsys):
    now_ms = 1_000_000
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(cli, "QUEUE_PATH", queue_path)
    monkeypatch.setattr(cli, "RUNTIME_LOCK_PATH", tmp_path / "runtime.lock")
    monkeypatch.setattr(cli.time, "time", lambda: now_ms / 1000)
    monkeypatch.setattr(cli, "reliability_snapshot", reliability_result_snapshot)
    cli.save_json(
        queue_path,
        {
            "last_session_key": "session-b",
            "jobs": [
                {
                    "message_id": "expired",
                    "enqueued_ts_ms": now_ms - 1,
                    "expires_ts_ms": now_ms,
                },
                {
                    "message_id": "active",
                    "enqueued_ts_ms": now_ms,
                    "expires_ts_ms": now_ms + 10_000,
                },
            ],
        },
    )

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="prune-expired", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    queue = cli.load_json(queue_path, {})
    assert rc == 0
    assert payload["ok"] is True
    assert payload["changed"] is True
    assert payload["summary"] == "Removed 1 expired or stale queue entry."
    assert [job["message_id"] for job in queue["jobs"]] == ["active"]
    assert queue["last_session_key"] == "session-b"


def test_prune_expired_recovery_preserves_unknown_queue_entries(
    tmp_path, monkeypatch, capsys
):
    now_ms = 1_000_000
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(cli, "QUEUE_PATH", queue_path)
    monkeypatch.setattr(cli, "RUNTIME_LOCK_PATH", tmp_path / "runtime.lock")
    monkeypatch.setattr(cli.time, "time", lambda: now_ms / 1000)
    monkeypatch.setattr(cli, "reliability_snapshot", reliability_result_snapshot)
    cli.save_json(
        queue_path,
        {
            "jobs": [
                "unexpected-entry",
                {
                    "message_id": "expired",
                    "enqueued_ts_ms": now_ms - 1,
                    "expires_ts_ms": now_ms,
                },
                {"message_id": "active", "enqueued_ts_ms": now_ms},
            ]
        },
    )

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="prune-expired", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["changed"] is True
    assert cli.load_json(queue_path, {})["jobs"] == [
        "unexpected-entry",
        {"message_id": "active", "enqueued_ts_ms": now_ms},
    ]


def test_prune_expired_recovery_reports_busy_without_mutation(tmp_path, monkeypatch, capsys):
    queue_path = tmp_path / "queue.json"
    cli.save_json(queue_path, {"jobs": [{"message_id": "active", "enqueued_ts_ms": 10}]})
    monkeypatch.setattr(cli, "QUEUE_PATH", queue_path)
    monkeypatch.setattr(cli, "reliability_snapshot", reliability_result_snapshot)

    @contextlib.contextmanager
    def busy_lock(_path):
        yield False

    monkeypatch.setattr(cli.audio_worker, "try_file_lock", busy_lock)

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="prune-expired", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["changed"] is False
    assert payload["summary"] == "The runtime queue is busy; try again."
    assert cli.load_json(queue_path, {})["jobs"][0]["message_id"] == "active"


def test_restart_recovery_delegates_to_existing_runtime_path(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        cli,
        "runtime_restart",
        lambda args: calls.append(args.test) or 0,
    )
    monkeypatch.setattr(cli, "reliability_snapshot", reliability_result_snapshot)

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="restart-runtime", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert calls == [False]
    assert payload["ok"] is True
    assert payload["changed"] is True
    assert payload["summary"] == "Restarted the voice runtime."


def test_successful_recovery_keeps_action_result_when_snapshot_refresh_fails(
    monkeypatch, capsys
):
    monkeypatch.setattr(cli, "runtime_restart", lambda _args: 0)

    def fail_snapshot():
        raise OSError("unavailable")

    monkeypatch.setattr(cli, "reliability_snapshot", fail_snapshot)

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="restart-runtime", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["changed"] is True
    assert payload["summary"] == (
        "Restarted the voice runtime. Runtime status refresh is unavailable."
    )
    assert payload["snapshot"]["version"] == 1
    assert payload["snapshot"]["generated_at_ms"] == 0


def test_tts_recovery_uses_fixed_private_test_sentence(monkeypatch, capsys):
    calls = []

    def fake_tts_test(args, quiet=False):
        calls.append((args.text, quiet))
        return 0

    monkeypatch.setattr(cli, "tts_test", fake_tts_test)
    monkeypatch.setattr(cli, "reliability_snapshot", reliability_result_snapshot)

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="test-tts", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert calls == [("Jarvis line test is ready.", True)]
    assert payload["ok"] is True
    assert payload["changed"] is False
    assert payload["summary"] == "Played the fixed voice test."


def test_failed_tts_recovery_returns_json_failure(monkeypatch, capsys):
    monkeypatch.setattr(cli, "tts_test", lambda _args, quiet=False: 1)
    monkeypatch.setattr(cli, "reliability_snapshot", reliability_result_snapshot)

    rc = cli.diagnostics_recover_command(
        argparse.Namespace(action="test-tts", json_output=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["changed"] is False
    assert payload["summary"] == "The selected voice test failed."


def test_diagnostics_parser_routes_snapshot_and_recovery():
    parser = cli.build_parser()

    snapshot = parser.parse_args(["diagnostics", "snapshot", "--json"])
    recovery = parser.parse_args(
        ["diagnostics", "recover", "prune-expired", "--json"]
    )

    assert snapshot.func is cli.diagnostics_snapshot_command
    assert snapshot.json_output is True
    assert recovery.func is cli.diagnostics_recover_command
    assert recovery.action == "prune-expired"
    assert recovery.json_output is True


def test_diagnostics_parser_rejects_unknown_recovery_action():
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["diagnostics", "recover", "clear-everything"])

    assert exc.value.code == 2


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
    out = capsys.readouterr().out
    assert "Jarvis Line status" in out
    assert "audio_worker_rss_mb:" in out
    assert "audio_worker_idle_exit_seconds: 60" in out
    assert "audio_worker_max_rss_mb: 512" in out


def test_doctor_allows_idle_audio_worker_when_queue_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cli, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(cli, "LATEST_PATH", tmp_path / "latest.json")
    watcher = tmp_path / "watcher.py"
    worker = tmp_path / "audio_worker.py"
    watcher.write_text("")
    worker.write_text("")
    monkeypatch.setattr(cli, "WATCHER_PATH", watcher)
    monkeypatch.setattr(cli, "WORKER_PATH", worker)
    cli.save_json(cli.CONFIG_PATH, {"tts": "system", "audio_worker_idle_exit_seconds": 60})
    cli.save_json(cli.HOOKS_JSON, {"hooks": {}})
    cli.save_json(cli.STATE_PATH, {
        "__watcher__": {"pid": 101},
        "__audio_worker__": {"pid": 202},
    })
    cli.save_json(cli.QUEUE_PATH, {"jobs": []})
    cli.save_json(cli.LATEST_PATH, {"sessions": {}})
    monkeypatch.setattr(cli, "kokoro_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cli, "system_tts_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cli, "pid_alive", lambda pid: pid == 101)
    monkeypatch.setattr(cli, "maybe_print_update_notice", lambda cfg: None)

    assert cli.doctor(argparse.Namespace(fix=False, json_output=False)) == 0
    out = capsys.readouterr().out

    assert "[OK] audio worker process - idle/stopped pid=202 queue_jobs=0" in out
    assert "[WARN] Jarvis Line Codex hook" in out
    assert "Jarvis Line is healthy." in out


def test_has_codex_session_start_hook_ignores_unrelated_hooks():
    hooks = {
        "hooks": {
            "SessionStart": [{"hooks": [{"command": "echo unrelated"}]}],
            "PermissionRequest": [{"hooks": [{"command": "python -m jarvis_line.codex_hook"}]}],
        }
    }

    assert not cli.has_codex_session_start_hook(hooks)
    hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "python -m jarvis_line.watcher --launch"
    assert cli.has_codex_session_start_hook(hooks)


def test_pid_alive_rejects_zombie_process(monkeypatch):
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cli.subprocess, "check_output", lambda *args, **kwargs: "Z")

    assert cli.pid_alive(123) is False


def test_install_uninstall_codex_uses_package_command(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli, "KOKORO_PY", tmp_path / "python")
    monkeypatch.setattr(cli, "enable_codex_hooks_feature", lambda: True)
    cli.save_json(tmp_path / "hooks.json", {"hooks": {}})

    assert cli.install_codex(argparse.Namespace()) == 0
    hooks = cli.load_json(tmp_path / "hooks.json", {})
    session_command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    permission_command = hooks["hooks"]["PermissionRequest"][0]["hooks"][0]["command"]
    assert "jarvis_line.watcher" in session_command
    assert "jarvis_line.codex_hook" in permission_command

    assert cli.install_codex(argparse.Namespace()) == 0
    hooks = cli.load_json(tmp_path / "hooks.json", {})
    assert len(hooks["hooks"]["SessionStart"]) == 1
    assert len(hooks["hooks"]["PermissionRequest"]) == 1

    assert cli.uninstall_codex(argparse.Namespace()) == 0
    hooks = cli.load_json(tmp_path / "hooks.json", {})
    assert "SessionStart" not in hooks["hooks"]
    assert "PermissionRequest" not in hooks["hooks"]


def test_install_codex_preserves_unrelated_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli, "enable_codex_hooks_feature", lambda: True)
    unrelated = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "other-tool", "timeout": 9}],
    }
    cli.save_json(
        tmp_path / "hooks.json",
        {"hooks": {"PermissionRequest": [unrelated], "PostToolUse": [unrelated]}},
    )

    assert cli.install_codex(argparse.Namespace()) == 0

    hooks = cli.load_json(tmp_path / "hooks.json", {})["hooks"]
    assert unrelated in hooks["PermissionRequest"]
    assert hooks["PostToolUse"] == [unrelated]
    assert len(hooks["PermissionRequest"]) == 2


def test_install_codex_does_not_mutate_hooks_when_feature_enable_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli, "enable_codex_hooks_feature", lambda: False)
    original = {"hooks": {"PostToolUse": []}}
    cli.save_json(tmp_path / "hooks.json", original)

    assert cli.install_codex(argparse.Namespace()) == 1
    assert cli.load_json(tmp_path / "hooks.json", {}) == original


def test_install_codex_validates_hooks_before_enabling_feature(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    cli.save_json(tmp_path / "hooks.json", {"hooks": "invalid"})
    calls = []
    monkeypatch.setattr(
        cli,
        "enable_codex_hooks_feature",
        lambda: calls.append("enable") or True,
    )

    assert cli.install_codex(argparse.Namespace()) == 1
    assert calls == []


def test_enable_codex_hooks_feature_uses_target_codex_home(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/usr/local/bin/codex")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli.enable_codex_hooks_feature() is True
    assert calls[0][0] == [
        "/usr/local/bin/codex",
        "features",
        "enable",
        "hooks",
    ]
    assert calls[0][1]["env"]["CODEX_HOME"] == str(tmp_path)


def test_enable_codex_hooks_feature_disables_existing_legacy_flag(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli, "HOOKS_JSON", tmp_path / "hooks.json")
    (tmp_path / "config.toml").write_text(
        "[features]\ncodex_hooks = true\nother = true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/usr/local/bin/codex")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli.enable_codex_hooks_feature() is True
    assert commands == [
        ["/usr/local/bin/codex", "features", "enable", "hooks"],
        ["/usr/local/bin/codex", "features", "disable", "codex_hooks"],
    ]


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


def test_kokoro_parser_requires_explicit_license_acceptance_for_download():
    parser = cli.build_parser()

    args = parser.parse_args(["kokoro", "download", "--accept-license", "--force"])

    assert args.accept_license is True
    assert args.force is True
    assert args.func is cli.kokoro_download


def test_kokoro_download_refuses_without_license_acceptance(capsys):
    result = cli.kokoro_download(argparse.Namespace(accept_license=False, force=False))

    assert result == 2
    assert "--accept-license" in capsys.readouterr().err


def test_kokoro_download_uses_managed_destinations_and_activates_them(tmp_path, monkeypatch):
    model = tmp_path / "managed" / "model.onnx"
    voices = tmp_path / "managed" / "voices.bin"
    custom_model = tmp_path / "custom" / "model.onnx"
    custom_voices = tmp_path / "custom" / "voices.bin"
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "KOKORO_MODEL", model)
    monkeypatch.setattr(cli, "KOKORO_VOICES", voices)
    cli.save_json(
        cli.CONFIG_PATH,
        {"model_path": str(custom_model), "voices_path": str(custom_voices)},
    )
    calls = []

    def fake_download(spec, destination, *, force):
        calls.append((spec.name, destination, force))
        return "downloaded"

    monkeypatch.setattr(cli.kokoro_assets, "download_verified_asset", fake_download)

    assert cli.kokoro_download(argparse.Namespace(accept_license=True, force=True)) == 0
    assert calls == [
        ("kokoro-v1.0.onnx", model, True),
        ("voices-v1.0.bin", voices, True),
    ]
    config = cli.load_json(cli.CONFIG_PATH, {})
    assert config["model_path"] == str(model)
    assert config["voices_path"] == str(voices)


def test_kokoro_download_does_not_change_config_after_failed_verification(tmp_path, monkeypatch):
    custom_model = tmp_path / "custom-model.onnx"
    custom_voices = tmp_path / "custom-voices.bin"
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli, "KOKORO_MODEL", tmp_path / "managed-model.onnx")
    monkeypatch.setattr(cli, "KOKORO_VOICES", tmp_path / "managed-voices.bin")
    original = {"model_path": str(custom_model), "voices_path": str(custom_voices)}
    cli.save_json(cli.CONFIG_PATH, original)

    def fail_download(spec, destination, *, force):
        raise ValueError("verification failed")

    monkeypatch.setattr(cli.kokoro_assets, "download_verified_asset", fail_download)

    assert cli.kokoro_download(argparse.Namespace(accept_license=True, force=True)) == 1
    assert cli.load_json(cli.CONFIG_PATH, {}) == original


def test_kokoro_verify_checks_configured_files_against_official_manifest(tmp_path, monkeypatch):
    model = tmp_path / "model.onnx"
    voices = tmp_path / "voices.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    cli.save_json(cli.CONFIG_PATH, {"model_path": str(model), "voices_path": str(voices)})
    monkeypatch.setattr(
        cli.kokoro_assets,
        "OFFICIAL_ASSETS",
        {
            "model": cli.kokoro_assets.AssetSpec(
                "model.onnx",
                "https://example.invalid/model.onnx",
                len(b"model"),
                hashlib.sha256(b"model").hexdigest(),
            ),
            "voices": cli.kokoro_assets.AssetSpec(
                "voices.bin",
                "https://example.invalid/voices.bin",
                len(b"voices"),
                hashlib.sha256(b"voices").hexdigest(),
            ),
        },
    )

    assert cli.kokoro_verify(argparse.Namespace()) == 0

    voices.write_bytes(b"modified")
    assert cli.kokoro_verify(argparse.Namespace()) == 1


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
    assert "meaningful commentary/progress updates" in english
    assert "Do not include more than one `Jarvis line: ...` line in a single commentary/progress message." in english
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


def test_instructions_install_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "AGENTS.md"
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")

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


def cleanup_report(
    *,
    mode="status",
    eligible_files=4,
    eligible_bytes=48 * 1024 * 1024,
    removed_files=0,
    removed_bytes=0,
    skipped_files=2,
    errors=None,
    already_running=False,
    last_success_at=1_700_000_000,
):
    report = cleanup.CleanupReport(
        mode=mode,
        errors=list(errors or []),
        already_running=already_running,
        last_success_at=last_success_at,
    )
    category = report.categories["generated_audio"]
    category.eligible_files = eligible_files
    category.eligible_bytes = eligible_bytes
    category.removed_files = removed_files
    category.removed_bytes = removed_bytes
    category.skipped_files = skipped_files
    category.error_count = len(report.errors)
    return report


def test_cleanup_parser_registers_status_and_run_json_commands():
    parser = cli.build_parser()

    status_args = parser.parse_args(["cleanup", "status", "--json"])
    run_args = parser.parse_args(["cleanup", "run"])

    assert status_args.func is cli.cleanup_command
    assert status_args.cleanup_command == "status"
    assert status_args.json_output is True
    assert run_args.func is cli.cleanup_command
    assert run_args.cleanup_command == "run"
    assert run_args.json_output is False


def test_cleanup_status_json_uses_stable_public_report(monkeypatch, capsys):
    report = cleanup_report()
    monkeypatch.setattr(cli.cleanup, "inspect", lambda: report)

    args = cli.build_parser().parse_args(["cleanup", "status", "--json"])

    assert args.func(args) == 0
    assert json.loads(capsys.readouterr().out) == report.to_dict()


def test_cleanup_status_human_output_reports_exact_totals(monkeypatch, capsys):
    report = cleanup_report()
    monkeypatch.setattr(cli.cleanup, "inspect", lambda: report)

    args = cli.build_parser().parse_args(["cleanup", "status"])

    assert args.func(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Jarvis Line cleanup status",
        "Eligible: 4 files",
        "Reclaimable: 48.0 MB",
        "Skipped: 2 files",
        "Errors: 0",
        "Last successful cleanup: 2023-11-14T22:13:20Z",
    ]


def test_cleanup_run_human_output_reports_removed_totals(monkeypatch, capsys):
    report = cleanup_report(
        mode="run",
        eligible_files=5,
        eligible_bytes=52 * 1024 * 1024,
        removed_files=3,
        removed_bytes=48 * 1024 * 1024,
        skipped_files=2,
    )
    monkeypatch.setattr(cli.cleanup, "run", lambda: report)

    args = cli.build_parser().parse_args(["cleanup", "run"])

    assert args.func(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Jarvis Line cleanup run",
        "Eligible: 5 files",
        "Reclaimable: 52.0 MB",
        "Removed: 3 files",
        "Reclaimed: 48.0 MB",
        "Skipped: 2 files",
        "Errors: 0",
        "Last successful cleanup: 2023-11-14T22:13:20Z",
    ]


def test_cleanup_partial_errors_return_one_and_print_safe_details(monkeypatch, capsys):
    report = cleanup_report(
        mode="run",
        errors=[{"category": "generated_audio", "name": "kokoro_failed.wav"}],
    )
    monkeypatch.setattr(cli.cleanup, "run", lambda: report)

    args = cli.build_parser().parse_args(["cleanup", "run"])

    assert args.func(args) == 1
    output = capsys.readouterr().out
    assert "Errors: 1" in output
    assert "Error: generated_audio/kokoro_failed.wav" in output
    assert "/Users/" not in output


def test_cleanup_already_running_is_safe_no_op(monkeypatch, capsys):
    report = cleanup_report(mode="run", already_running=True)
    monkeypatch.setattr(cli.cleanup, "run", lambda: report)

    args = cli.build_parser().parse_args(["cleanup", "run"])

    assert args.func(args) == 0
    assert "Cleanup already running; no action taken." in capsys.readouterr().out


def test_cleanup_human_output_handles_out_of_range_success_time(monkeypatch, capsys):
    report = cleanup_report(last_success_at=10**100)
    monkeypatch.setattr(cli.cleanup, "inspect", lambda: report)

    args = cli.build_parser().parse_args(["cleanup", "status"])

    assert args.func(args) == 0
    assert "Last successful cleanup: unknown" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("cleanup_enabled", "1"),
        ("cleanup_enabled", "yes"),
        ("cleanup_interval_hours", "23"),
        ("cleanup_interval_hours", "169"),
        ("cleanup_interval_hours", "24.0"),
        ("cleanup_interval_hours", "true"),
    ],
)
def test_config_set_rejects_invalid_cleanup_values_before_saving(
    key, value, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "load_effective_config", lambda: {"tts": "system"})
    monkeypatch.setattr(cli, "save_json", lambda *_args: pytest.fail("must not save"))

    assert cli.config_set(argparse.Namespace(key=key, value=value)) == 1
    assert f"Invalid value for {key}" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("cleanup_enabled", "true", True),
        ("cleanup_enabled", "false", False),
        ("cleanup_interval_hours", "24", 24),
        ("cleanup_interval_hours", "168", 168),
    ],
)
def test_config_set_accepts_bounded_cleanup_values(
    key, value, expected, monkeypatch
):
    saved = []
    monkeypatch.setattr(cli, "load_effective_config", lambda: {"tts": "system"})
    monkeypatch.setattr(cli, "save_json", lambda _path, cfg: saved.append(dict(cfg)))

    assert cli.config_set(argparse.Namespace(key=key, value=value)) == 0
    assert saved == [{"tts": "system", key: expected}]
