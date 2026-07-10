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


def test_community_files_use_current_safe_support_flow():
    required_files = [
        ROOT / "CONTRIBUTING.md",
        ROOT / "CODE_OF_CONDUCT.md",
        ROOT / "SECURITY.md",
        ROOT / ".github/PULL_REQUEST_TEMPLATE.md",
        ROOT / ".github/ISSUE_TEMPLATE/config.yml",
        ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml",
        ROOT / ".github/ISSUE_TEMPLATE/documentation.yml",
    ]
    assert all(path.is_file() for path in required_files)

    bug_template = (ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text(
        encoding="utf-8"
    )
    issue_config = (ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(
        encoding="utf-8"
    )

    assert "jarvis-line support-report --output" in bug_template
    assert "support-bundle" not in bug_template
    assert ".zip" not in bug_template.lower()
    assert "blank_issues_enabled: false" in issue_config
    assert "/discussions/categories/q-a" in issue_config
    assert "/discussions/categories/ideas" in issue_config
    assert "/security/advisories/new" in issue_config
