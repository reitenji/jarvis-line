from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis_line import soak
from scripts import soak_runtime


FORBIDDEN_KEYS = {
    "command",
    "content",
    "environment",
    "line",
    "session_key",
    "session_path",
    "text",
}


def assert_private(value):
    if isinstance(value, dict):
        assert FORBIDDEN_KEYS.isdisjoint(value)
        for item in value.values():
            assert_private(item)
    elif isinstance(value, list):
        for item in value:
            assert_private(item)


def test_quick_soak_is_deterministic_private_and_passes(tmp_path):
    first = soak.run_soak(
        soak.SoakConfig.for_mode("quick", seed=7, root=tmp_path / "first")
    )
    second = soak.run_soak(
        soak.SoakConfig.for_mode("quick", seed=7, root=tmp_path / "second")
    )

    assert first["ok"] is True
    assert first["version"] == 1
    assert first["metrics"] == second["metrics"]
    assert first["invariants"] == second["invariants"]
    assert first["failures"] == []
    assert all(first["invariants"].values())
    assert_private(first)
    assert "privacy-probe-secret" not in json.dumps(first)


def test_soak_exercises_queue_recovery_and_runtime_limits(tmp_path):
    report = soak.run_soak(
        soak.SoakConfig.for_mode("quick", seed=11, root=tmp_path)
    )

    assert report["metrics"]["max_queue_depth"] == 8
    assert report["metrics"]["expired_rejected"] > 0
    assert report["metrics"]["stale_rejected"] > 0
    assert report["metrics"]["cancelled"] > 0
    assert report["metrics"]["active_prune_checks"] == 1
    assert report["metrics"]["expired_playbacks"] == 0
    assert report["metrics"]["max_parallel_playbacks"] == 1
    assert report["invariants"]["queue_bounded"] is True
    assert report["invariants"]["finals_resolved"] is True
    assert report["invariants"]["active_prune_preserved"] is True
    assert report["invariants"]["runtime_limits_observed"] is True
    assert report["invariants"]["restart_no_replay"] is True


def test_soak_rotates_private_trace_and_serializes_lock_writers(tmp_path):
    report = soak.run_soak(
        soak.SoakConfig.for_mode("quick", seed=3, root=tmp_path)
    )

    assert report["metrics"]["trace_rotations"] > 0
    assert report["metrics"]["lock_mutations"] > 0
    assert report["invariants"]["trace_rotated"] is True
    assert report["invariants"]["trace_private"] is True
    assert report["invariants"]["lock_serialized"] is True

    trace_path = tmp_path / "runtime" / "trace.jsonl"
    events = [json.loads(raw) for raw in trace_path.read_text().splitlines()]
    assert events
    assert_private(events)
    assert "privacy-probe-secret" not in trace_path.read_text()


def test_soak_stays_inside_root_and_leaves_no_workers(tmp_path):
    before_threads = {thread.ident for thread in threading.enumerate()}
    report = soak.run_soak(
        soak.SoakConfig.for_mode("quick", seed=5, root=tmp_path)
    )
    after_threads = {thread.ident for thread in threading.enumerate()}

    assert after_threads == before_threads
    assert report["metrics"]["child_processes_started"] == 0
    assert report["metrics"]["leftover_threads"] == 0
    assert report["invariants"]["isolated_files"] is True
    assert report["invariants"]["no_child_processes"] is True
    assert report["invariants"]["no_leftover_threads"] is True
    assert not list(tmp_path.rglob("*.tmp"))
    assert not [path for path in tmp_path.rglob("*.d") if path.is_dir()]


def test_invalid_soak_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported soak mode"):
        soak.SoakConfig.for_mode("forever", seed=1, root=tmp_path)


def test_soak_script_writes_atomic_json_report(tmp_path, capsys):
    output = tmp_path / "report.json"

    exit_code = soak_runtime.main(
        [
            "--mode",
            "quick",
            "--seed",
            "13",
            "--json",
            "--output",
            str(output),
        ]
    )

    printed = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text())
    assert exit_code == 0
    assert printed["ok"] is True
    assert written == printed
    assert not list(tmp_path.glob(".report.json.*.tmp"))


def test_write_report_replaces_existing_file(tmp_path):
    output = tmp_path / "report.json"
    output.write_text("stale", encoding="utf-8")
    report = {
        "version": 1,
        "mode": "quick",
        "seed": 1,
        "elapsed_ms": 0,
        "metrics": {},
        "invariants": {},
        "failures": [],
        "ok": True,
    }

    soak_runtime.write_report(output, report)

    assert json.loads(output.read_text()) == report


def test_default_soak_root_is_removed_after_run():
    config = soak.SoakConfig.for_mode("quick", seed=17)
    root = Path(config.root)

    report = soak.run_soak(config)

    assert report["ok"] is True, report
    assert not root.exists()


def test_manual_config_cannot_claim_cleanup_ownership(tmp_path):
    root = tmp_path / "manual"
    root.mkdir()
    sentinel = root / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    config = replace(
        soak.SoakConfig.for_mode("quick", seed=19, root=root),
        cleanup_root=True,
    )

    report = soak.run_soak(config)

    assert report["ok"] is True
    assert sentinel.read_text(encoding="utf-8") == "keep"
