#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value or "")).lower()


def project_identity(pyproject_path: Path) -> tuple[str, str]:
    with Path(pyproject_path).open("rb") as handle:
        project = tomllib.load(handle)["project"]
    return str(project["name"]), str(project["version"])


def validate_sbom(path: Path, expected_name: str, expected_version: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    spdx_version = str(data.get("spdxVersion") or "")
    if not spdx_version.startswith("SPDX-"):
        raise ValueError("SBOM does not declare an SPDX version")

    normalized_name = normalize_distribution_name(expected_name)
    packages = data.get("packages")
    if not isinstance(packages, list):
        raise ValueError("SBOM does not contain a package catalog")
    for package in packages:
        if not isinstance(package, dict):
            continue
        if (
            normalize_distribution_name(package.get("name")) == normalized_name
            and str(package.get("versionInfo") or "") == expected_version
        ):
            return package

    observed = ", ".join(
        f"{package.get('name')} {package.get('versionInfo')}"
        for package in packages[:10]
        if isinstance(package, dict)
    )
    raise ValueError(
        f"SBOM does not catalog {expected_name} {expected_version}; "
        f"observed: {observed or 'no packages'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that an SPDX SBOM catalogs the current Jarvis Line package."
    )
    parser.add_argument("sbom", type=Path)
    parser.add_argument("--pyproject", type=Path, default=ROOT / "pyproject.toml")
    args = parser.parse_args()

    try:
        name, version = project_identity(args.pyproject)
        validate_sbom(args.sbom, name, version)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"SBOM validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"SBOM verified: {name} {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
