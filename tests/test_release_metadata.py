import re
from pathlib import Path

from scripts import check_version_consistency


ROOT = Path(__file__).resolve().parents[1]


def test_repository_versions_are_consistent():
    versions = check_version_consistency.read_versions(ROOT)

    assert versions.package == "0.8.1"
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


def test_workflows_pin_actions_to_reviewed_commits():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release_workflow = (ROOT / ".github/workflows/release-artifacts.yml").read_text(encoding="utf-8")
    security_workflow = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    workflows = ci_workflow + release_workflow + security_workflow

    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflows
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflows
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflows
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in workflows
    assert "anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610" in workflows
    assert all(
        re.fullmatch(r"[0-9a-f]{40}", reference)
        for reference in re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", workflows)
    )


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


def test_v1_readiness_files_and_preview_labels_are_present():
    assert (ROOT / "PRIVACY.md").is_file()
    assert (ROOT / "docs/SUPPORT-MATRIX.md").is_file()
    assert (ROOT / ".github/dependabot.yml").is_file()
    assert (ROOT / ".github/workflows/security.yml").is_file()

    package = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    app_source = (
        ROOT / "apps/macos/JarvisLine/Sources/JarvisLineApp.swift"
    ).read_text(encoding="utf-8")
    assert "Development Status :: 4 - Beta" in package
    assert 'versionChip("Preview")' in app_source


def test_clean_install_and_sbom_checks_are_configured():
    install_script = ROOT / "scripts/verify_clean_install.py"
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release_workflow = (ROOT / ".github/workflows/release-artifacts.yml").read_text(
        encoding="utf-8"
    )

    assert install_script.is_file()
    assert "verify_clean_install.py" in ci_workflow
    assert "jarvis-line.spdx.json" in release_workflow
    assert "anchore/sbom-action@" in release_workflow
    assert "dependency-graph/sbom" not in release_workflow
    assert "syft-version: v1.42.3" in release_workflow
    assert "path: ./build/sbom-wheel" in ci_workflow
    assert "path: ./build/sbom-wheel" in release_workflow
    assert "validate_sbom.py" in ci_workflow
    assert "validate_sbom.py" in release_workflow


def test_ci_avoids_duplicate_feature_push_and_pull_request_matrices():
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "push:\n    branches: [develop, main]" in ci_workflow
    assert "pull_request:" in ci_workflow
    assert "cancel-in-progress: true" in ci_workflow


def test_security_audit_checks_optional_dependencies_without_pypi_project_lookup():
    security_workflow = (ROOT / ".github/workflows/security.yml").read_text(
        encoding="utf-8"
    )

    package = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'security = ["pip-audit==2.10.1"]' in package
    assert 'pip install -e ".[kokoro,security,test]"' in security_workflow
    assert "pip_audit --local --skip-editable" in security_workflow
    assert "--strict" not in security_workflow


def test_kokoro_documentation_uses_shared_jarvis_home():
    recipe = (ROOT / "docs/recipes/kokoro.md").read_text(encoding="utf-8")
    support_matrix = (ROOT / "docs/SUPPORT-MATRIX.md").read_text(encoding="utf-8")
    assert "~/.jarvis-line/tts" in recipe
    assert "~/.codex/tts" not in recipe
    assert "jarvis-line kokoro verify\njarvis-line kokoro status" in recipe
    assert "PowerShell integration is implemented and smoke-tested" not in support_matrix


def test_guided_setup_documentation_is_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = (ROOT / "docs/COMMANDS.md").read_text(encoding="utf-8")
    app_readme = (ROOT / "apps/macos/JarvisLine/README.md").read_text(
        encoding="utf-8"
    )

    assert "jarvis-line setup" in readme
    assert "jarvis-line setup --default" in readme
    assert "setup inspect --language" in commands
    assert "setup apply --stdin --json" in commands
    assert "Setup Assistant" in app_readme
    assert "never edits agent Markdown" in app_readme


def test_attention_documentation_is_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = (ROOT / "docs/COMMANDS.md").read_text(encoding="utf-8")
    configuration = (ROOT / "docs/CONFIGURATION.md").read_text(encoding="utf-8")
    protocol = (ROOT / "docs/EVENT-PROTOCOL.md").read_text(encoding="utf-8")
    support_matrix = (ROOT / "docs/SUPPORT-MATRIX.md").read_text(encoding="utf-8")
    benchmark = (ROOT / "scripts/benchmark_attention_hook.py").read_text(
        encoding="utf-8"
    )

    assert "Attention alerts" in readme
    assert "request_user_input" in readme
    assert "attention_enabled" in commands
    assert "attention_enabled" in configuration
    assert "--attention-type input_required" in protocol
    assert "PermissionRequest" in support_matrix
    assert "RUNS = 30" in benchmark
    assert "P95_LIMIT_MS = 150.0" in benchmark
