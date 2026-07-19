#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jarvis_line import soak  # noqa: E402


def write_report(path: Path, report: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            json.dump(report, output, ensure_ascii=True, indent=2, sort_keys=True)
            output.write("\n")
            temporary_name = output.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an isolated deterministic Jarvis Line runtime soak."
    )
    parser.add_argument("--mode", choices=("quick", "extended"), default="quick")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = soak.run_soak(soak.SoakConfig.for_mode(args.mode, args.seed))
    if args.output:
        write_report(args.output, report)
    if args.json_output:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        result = "PASS" if report["ok"] else "FAIL"
        print(
            f"[{result}] {report['mode']} soak: "
            f"sessions={report['metrics']['sessions']} "
            f"submissions={report['metrics']['submissions']} "
            f"elapsed_ms={report['elapsed_ms']}"
        )
        for failure in report["failures"]:
            print(f"[FAIL] {failure}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
