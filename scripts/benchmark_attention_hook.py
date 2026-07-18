#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = 30
P95_LIMIT_MS = 150.0


def benchmark_environment(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONNOUSERSITE": "1",
        }
    )
    return env


def prepare_home(home: Path) -> None:
    hooks = home / ".codex" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "jarvis_line_config.json").write_text(
        json.dumps(
            {
                "attention_enabled": True,
                "speech_enabled": True,
                "speak_mode": "final_only",
                "line_language": "English",
                "debug_content_logging": False,
            }
        ),
        encoding="utf-8",
    )
    (hooks / ".jarvis_line_state.json").write_text(
        json.dumps({"__runtime__": {"stopped": True}}),
        encoding="utf-8",
    )


def percentile_95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def main() -> int:
    payload = json.dumps(
        {
            "session_id": "benchmark-session",
            "hook_event_name": "PermissionRequest",
            "tool_name": "exec_command",
            "tool_input": {
                "command": "curl https://api.example.test/items?token=benchmark-secret"
            },
        }
    ).encode("utf-8")
    command = [sys.executable, "-m", "jarvis_line.codex_hook"]
    elapsed_ms: list[float] = []

    with tempfile.TemporaryDirectory(prefix="jarvis-line-attention-benchmark-") as temp:
        home = Path(temp)
        prepare_home(home)
        env = benchmark_environment(home)
        for index in range(RUNS):
            started = time.perf_counter_ns()
            proc = subprocess.run(
                command,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                env=env,
                check=False,
            )
            elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000)
            if proc.returncode != 0 or proc.stdout or proc.stderr:
                print(
                    "[FAIL] attention hook run "
                    f"{index + 1} returned code={proc.returncode} "
                    f"stdout_bytes={len(proc.stdout)} stderr_bytes={len(proc.stderr)}"
                )
                return 1

        state = json.loads(
            (home / ".codex" / "hooks" / ".jarvis_line_state.json").read_text(
                encoding="utf-8"
            )
        )
        if "__audio_worker__" in state:
            print("[FAIL] attention hook benchmark launched an audio worker")
            return 1

    median_ms = statistics.median(elapsed_ms)
    p95_ms = percentile_95(elapsed_ms)
    passed = p95_ms < P95_LIMIT_MS
    print(
        f"attention hook benchmark: runs={RUNS} median_ms={median_ms:.2f} "
        f"p95_ms={p95_ms:.2f} limit_ms={P95_LIMIT_MS:.0f}"
    )
    print("[PASS] hook latency is within the local target" if passed else "[FAIL] hook latency exceeds the local target")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
