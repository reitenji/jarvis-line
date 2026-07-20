from pathlib import Path
from types import SimpleNamespace

from jarvis_line import kokoro_say


def test_spawn_player_reports_macos_failure(monkeypatch):
    monkeypatch.setattr(kokoro_say.sys, "platform", "darwin")
    monkeypatch.setattr(
        kokoro_say.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    assert kokoro_say.spawn_player(Path("chime.wav"), 1.0) is False


def test_spawn_player_tries_next_linux_player_after_failure(monkeypatch):
    calls = []

    monkeypatch.setattr(kokoro_say.sys, "platform", "linux")
    monkeypatch.setattr(kokoro_say.shutil, "which", lambda name: f"/usr/bin/{name}")

    def run(command, **_kwargs):
        calls.append(command[0])
        return SimpleNamespace(returncode=0 if command[0] == "/usr/bin/aplay" else 1)

    monkeypatch.setattr(kokoro_say.subprocess, "run", run)

    assert kokoro_say.spawn_player(Path("chime.wav"), 1.0) is True
    assert calls == ["/usr/bin/paplay", "/usr/bin/aplay"]
