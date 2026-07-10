from pathlib import Path

from scripts import check_version_consistency


ROOT = Path(__file__).resolve().parents[1]


def test_repository_versions_are_consistent():
    versions = check_version_consistency.read_versions(ROOT)

    assert versions.package == "0.3.1"
    assert versions.module == versions.package
    assert versions.app == versions.package
    assert versions.bundle_build.isdigit()
    assert check_version_consistency.version_errors(versions) == []


def test_version_errors_report_each_mismatch():
    versions = check_version_consistency.Versions(
        package="0.3.0",
        module="0.2.2",
        app="0.2.1",
        bundle_build="five",
    )

    assert check_version_consistency.version_errors(versions) == [
        "Python module version 0.2.2 does not match package version 0.3.0.",
        "macOS app version 0.2.1 does not match package version 0.3.0.",
        "macOS bundle build must be numeric, got five.",
    ]


def test_workflows_use_current_artifact_action_majors():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release_workflow = (ROOT / ".github/workflows/release-artifacts.yml").read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in ci_workflow
    assert "actions/upload-artifact@v7" in release_workflow
    assert "actions/download-artifact@v8" in release_workflow
    assert "actions/upload-artifact@v4" not in ci_workflow + release_workflow
    assert "actions/download-artifact@v4" not in release_workflow
