import json

import pytest

from scripts import validate_sbom


def write_sbom(path, packages):
    path.write_text(
        json.dumps({"spdxVersion": "SPDX-2.3", "packages": packages}),
        encoding="utf-8",
    )


def test_validate_sbom_requires_project_name_and_version(tmp_path):
    path = tmp_path / "release.spdx.json"
    write_sbom(
        path,
        [
            {"name": "release-root", "versionInfo": None},
            {"name": "jarvis-line", "versionInfo": "0.4.0"},
        ],
    )

    match = validate_sbom.validate_sbom(path, "jarvis-line", "0.4.0")

    assert match["name"] == "jarvis-line"
    assert match["versionInfo"] == "0.4.0"


def test_validate_sbom_normalizes_python_distribution_names(tmp_path):
    path = tmp_path / "release.spdx.json"
    write_sbom(path, [{"name": "jarvis_line", "versionInfo": "0.4.0"}])

    assert validate_sbom.validate_sbom(path, "jarvis-line", "0.4.0")["name"] == "jarvis_line"


def test_validate_sbom_rejects_structurally_valid_but_empty_catalog(tmp_path):
    path = tmp_path / "release.spdx.json"
    write_sbom(path, [{"name": "./dist", "versionInfo": None}])

    with pytest.raises(ValueError, match="jarvis-line 0.4.0"):
        validate_sbom.validate_sbom(path, "jarvis-line", "0.4.0")


def test_project_identity_reads_release_metadata(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "jarvis-line"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )

    assert validate_sbom.project_identity(pyproject) == ("jarvis-line", "0.4.0")
