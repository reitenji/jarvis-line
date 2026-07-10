from pathlib import Path

from scripts import check_version_consistency


ROOT = Path(__file__).resolve().parents[1]


def test_repository_versions_are_consistent():
    versions = check_version_consistency.read_versions(ROOT)

    assert versions.package == "0.2.2"
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
