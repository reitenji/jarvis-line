#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], *, env: dict[str, str], cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, env=env, cwd=cwd)


def capture(command: list[str], *, env: dict[str, str], cwd: Path) -> str:
    print("+", " ".join(command), flush=True)
    return subprocess.check_output(command, text=True, env=env, cwd=cwd).strip()


def venv_paths(root: Path) -> tuple[Path, Path, Path]:
    if os.name == "nt":
        bin_dir = root / "Scripts"
        return bin_dir / "python.exe", bin_dir / "jarvis-line.exe", bin_dir
    bin_dir = root / "bin"
    return bin_dir / "python", bin_dir / "jarvis-line", bin_dir


def clean_environment(home: Path) -> dict[str, str]:
    home = home.resolve()
    allowed_keys = {
        "COMSPEC",
        "ComSpec",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "SystemRoot",
        "TERM",
        "TZ",
        "WINDIR",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed_keys}
    temp_dir = home / "tmp"
    app_data = home / "AppData" / "Roaming"
    local_app_data = home / "AppData" / "Local"
    for path in (temp_dir, app_data, local_app_data, home / ".cache", home / ".config"):
        path.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "APPDATA": str(app_data),
            "LOCALAPPDATA": str(local_app_data),
            "TMPDIR": str(temp_dir),
            "TMP": str(temp_dir),
            "TEMP": str(temp_dir),
            "PYTHONNOUSERSITE": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    if os.name == "nt":
        home_drive, home_path = os.path.splitdrive(str(home))
        env["HOMEDRIVE"] = home_drive
        env["HOMEPATH"] = home_path or "\\"
    return env


def verify_clean_install(dist_dir: Path) -> None:
    wheels = sorted(dist_dir.glob("jarvis_line-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected exactly one jarvis-line wheel in {dist_dir}, found {len(wheels)}.")
    wheel = wheels[0].resolve()

    with tempfile.TemporaryDirectory(prefix="jarvis-line-clean-install-") as temp:
        root = Path(temp)
        home = root / "home"
        venv = root / "venv"
        home.mkdir()
        env = clean_environment(home)

        run([sys.executable, "-m", "venv", str(venv)], env=env, cwd=home)
        python, console_script, bin_dir = venv_paths(venv)
        run(
            [
                str(python),
                "-m",
                "pip",
                "--disable-pip-version-check",
                "install",
                "--no-deps",
                str(wheel),
            ],
            env=env,
            cwd=home,
        )

        version = capture([str(console_script), "--version"], env=env, cwd=home)
        if not version.startswith("jarvis-line "):
            raise SystemExit(f"Unexpected version output: {version}")
        help_text = capture([str(console_script), "--help"], env=env, cwd=home)
        if "Voice notifications for AI coding agents" not in help_text:
            raise SystemExit("Installed console script did not return Jarvis Line help.")
        run([str(console_script), "config", "defaults", "system"], env=env, cwd=home)
        run(
            [str(console_script), "instructions", "print", "agents", "--language", "English"],
            env=env,
            cwd=home,
        )

        run(
            [
                str(python),
                "-m",
                "pip",
                "--disable-pip-version-check",
                "uninstall",
                "--yes",
                "jarvis-line",
            ],
            env=env,
            cwd=home,
        )
        run(
            [
                str(python),
                "-c",
                "import importlib.util; raise SystemExit(1 if importlib.util.find_spec('jarvis_line') else 0)",
            ],
            env=env,
            cwd=home,
        )
        leftovers = list(bin_dir.glob("jarvis-line*"))
        if leftovers:
            raise SystemExit(f"Console entry point remains after uninstall: {leftovers}")

    print(f"Clean install and uninstall verified: {wheel.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Jarvis Line wheel in an isolated home and venv.")
    parser.add_argument("dist_dir", type=Path, help="Directory containing exactly one built wheel.")
    args = parser.parse_args()
    verify_clean_install(args.dist_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
