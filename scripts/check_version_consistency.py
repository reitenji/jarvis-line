#!/usr/bin/env python3
from __future__ import annotations

import ast
import plistlib
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Versions:
    package: str
    module: str
    app: str
    bundle_build: str


def _module_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError(f"__version__ is missing from {path}")


def read_versions(root: Path = ROOT) -> Versions:
    with (root / "pyproject.toml").open("rb") as project_file:
        package_version = str(tomllib.load(project_file)["project"]["version"])
    module_version = _module_version(root / "src/jarvis_line/__init__.py")
    with (root / "apps/macos/JarvisLine/Resources/Info.plist").open("rb") as plist_file:
        info = plistlib.load(plist_file)
    return Versions(
        package=package_version,
        module=module_version,
        app=str(info.get("CFBundleShortVersionString") or ""),
        bundle_build=str(info.get("CFBundleVersion") or ""),
    )


def version_errors(versions: Versions) -> list[str]:
    errors = []
    if versions.module != versions.package:
        errors.append(
            f"Python module version {versions.module} does not match package version {versions.package}."
        )
    if versions.app != versions.package:
        errors.append(
            f"macOS app version {versions.app} does not match package version {versions.package}."
        )
    if not versions.bundle_build.isdigit():
        errors.append(f"macOS bundle build must be numeric, got {versions.bundle_build}.")
    return errors


def main() -> int:
    versions = read_versions()
    errors = version_errors(versions)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    print(
        f"[OK] version {versions.package} "
        f"(Python module, package metadata, macOS app build {versions.bundle_build})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
