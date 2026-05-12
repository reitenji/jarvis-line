from pathlib import Path
import argparse
import tempfile

from jarvis_line import audio_worker, cli, watcher


def main() -> int:
    watcher.runtime_config = lambda: {
        "line_prefixes": ["Jarvis line:", "Friday line:"],
        "max_spoken_chars": 12,
        "speak_mode": "final_only",
    }
    assert watcher.extract_jarvis_line("Done\nFriday line: Hello from Friday") == "Hello from…"
    assert watcher.speak_mode_allows("final_answer") is True
    assert watcher.speak_mode_allows("commentary") is False

    output_path = Path(tempfile.gettempdir()) / "out.wav"
    assert audio_worker.format_command_parts(
        ["tts", "{text_json}", "{output}"],
        "hello",
        output_path,
    ) == ["tts", '"hello"', str(output_path)]

    assert "speed is ignored by macos" in cli.validate_config({"tts": "macos", "speed": 1.2})
    assert "speed is ignored by system" in cli.validate_config({"tts": "system", "speed": 1.2})
    assert not cli.validate_config({"tts": "system", "system_voice": None, "system_rate": None})

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        cli.CONFIG_PATH = root / "config.json"
        cli.LEGACY_CONFIG_PATH = root / "kokoro_tts_config.json"
        cli.HOOKS_JSON = root / "hooks.json"
        cli.save_json(cli.CONFIG_PATH, {"tts": "command", "command": "echo {text}"})
        assert cli.config_set(argparse.Namespace(key="custom_voice_id", value="abc")) == 0
        assert cli.load_json(cli.CONFIG_PATH, {})["custom_voice_id"] == "abc"
        cli.save_json(cli.HOOKS_JSON, {"hooks": {}})
        assert cli.install_codex(argparse.Namespace()) == 0
        assert "SessionStart" in cli.load_json(cli.HOOKS_JSON, {})["hooks"]
        assert cli.uninstall_codex(argparse.Namespace()) == 0
        assert cli.migrate_config(argparse.Namespace(remove_legacy=False)) == 0
        assert cli.kokoro_configure(argparse.Namespace(
            model_path=str(root / "model.onnx"),
            voices_path=str(root / "voices.bin"),
            voice="bm_george",
            lang="en-gb",
        )) == 0
        assert cli.load_json(cli.CONFIG_PATH, {})["tts"] == "kokoro"
        assert cli.config_defaults(argparse.Namespace(preset="kokoro")) == 0
        assert cli.config_schema(argparse.Namespace(preset="system")) == 0
        instruction_path = root / "AGENTS.md"
        assert cli.instructions_install(argparse.Namespace(target="agents", language="English", path=str(instruction_path))) == 0
        assert "Jarvis line:" in instruction_path.read_text()
        original_setup_default = cli.setup_default
        cli.setup_default = lambda args: 0
        init_path = root / "INIT_AGENTS.md"
        assert cli.init_project(argparse.Namespace(
            language="English",
            target="agents",
            path=str(init_path),
            apply_tts=False,
            codex=False,
            no_instructions=False,
            write_instructions=False,
            test=False,
        )) == 0
        cli.setup_default = original_setup_default
        assert not init_path.exists()
        cli.sync_language_config("tr", apply_tts=True)
        assert cli.load_json(cli.CONFIG_PATH, {})["tts"] == "command"
        report = root / "support.md"
        assert cli.support_report(argparse.Namespace(output=str(report), full=False, max_log_bytes=5_000_000, since=None)) == 0
        assert report.exists()

    print("smoke_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
