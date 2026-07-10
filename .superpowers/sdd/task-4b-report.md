# Task 4b Report

## Implemented

- Made `setup inspect --json` language-aware, preferring a valid configured
  `line_language` and otherwise English. Invalid explicit language input now
  returns versioned JSON and exit code 2.
- Kept backend recommendations in the Python CLI contract. Swift only forwards
  an optional requested language to `setup inspect`.
- Added pre-mutation backend preflight for language, platform, readiness, and
  reviewed custom-command checks. It runs before backups, config writes,
  Kokoro installation, hooks, runtime actions, or voice tests.
- Preserved the existing unavailable-English-Kokoro apply error contract while
  returning the new explicit non-English guided-Kokoro error.

## TDD Evidence

- RED: the six focused Python contract tests failed before implementation with
  missing `preflight_backend`, English inspect output, inspect side effects, and
  late apply mutation behavior.
- GREEN: focused tests passed after implementation: `6 passed`.

## Verification

- `PYTHONPATH=.:src .venv/bin/pytest -q`: `193 passed`.
- `swift build`: passed.
- `swiftc -parse Sources/SetupContract.swift Tests/JarvisLineTests/SetupContractTests.swift`: passed.
- `git diff --check`: pending final post-report check.

## Concern

- `swift test` cannot compile the pre-existing macOS test target because this
  local Swift toolchain cannot import `Testing` from
  `Tests/JarvisLineTests/JarvisConfigContractTests.swift`. The production
  target still builds and the changed source/test files parse successfully.
