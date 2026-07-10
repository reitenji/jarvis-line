# Contributing to Jarvis Line

Thanks for helping make Jarvis Line more reliable across agents, TTS engines, and operating systems.

## Choose the Right Channel

- Ask setup and usage questions in [Q&A Discussions](https://github.com/reitenji/jarvis-line/discussions/categories/q-a).
- Propose early feature ideas in [Ideas Discussions](https://github.com/reitenji/jarvis-line/discussions/categories/ideas).
- Report reproducible defects with the [bug report form](https://github.com/reitenji/jarvis-line/issues/new?template=bug_report.yml).
- Report documentation problems with the [documentation form](https://github.com/reitenji/jarvis-line/issues/new?template=documentation.yml).
- Report vulnerabilities privately through [GitHub Security Advisories](https://github.com/reitenji/jarvis-line/security/advisories/new).

## Development Setup

Fork the repository, then create a focused branch from the upstream `develop` branch:

```bash
git clone https://github.com/YOUR-USERNAME/jarvis-line.git
cd jarvis-line
git remote add upstream https://github.com/reitenji/jarvis-line.git
git fetch upstream
git switch -c feature/short-description upstream/develop
python3 -m pip install -e ".[test]"
```

Use `feature/*` for features and `fix/*` for bug fixes. Do not target `main` directly. Maintainers promote reviewed changes from `develop` to `main` for releases.

## Verification

Run the checks that apply to your change:

```bash
python3 -m compileall -q src/jarvis_line
PYTHONPATH=src python3 tests/run_smoke.py
python3 -m pytest -q
python3 scripts/check_version_consistency.py
python3 -m build --wheel --outdir build/clean-dist
python3 scripts/verify_clean_install.py build/clean-dist
```

On macOS, changes that affect the native manager app also require:

```bash
swift test --package-path apps/macos/JarvisLine
bash scripts/verify-macos-artifacts.sh
```

The Swift test target uses Apple's Swift Testing runtime. A Command Line Tools
only installation may compile the app without exposing that test module. In
that environment, run `swift build --package-path apps/macos/JarvisLine`, note
the limitation in the pull request, and let the full-Xcode macOS CI runner
execute the test suite.

For dependency or security-workflow changes, also validate the optional Kokoro
dependency graph in a clean virtual environment:

```bash
python3 -m pip install -e ".[kokoro,security,test]"
python3 -m pip_audit --local --skip-editable
```

CI repeats the Python checks on macOS, Linux, and Windows. Explain in the pull request when a platform-specific check cannot be run locally.

## Bug Reports and Privacy

Generate a small redacted report before opening a bug:

```bash
jarvis-line support-report --output ./jarvis-line-issue.md
```

Review the Markdown and paste only the useful sections into the issue form. Never upload ZIP support bundles, raw private logs, credentials, model files, or unrelated session content.

Read [PRIVACY.md](PRIVACY.md) before sharing diagnostics or configuring an
API-backed custom TTS command.

## Pull Requests

Keep each pull request focused on one behavior or documentation goal. Include:

- a clear problem statement and summary
- tests or reproducible verification evidence
- documentation for user-facing changes
- a link to the relevant issue or discussion when one exists

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
