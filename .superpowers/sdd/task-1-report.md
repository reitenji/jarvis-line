# Task 1 Report: Shared Cleanup Configuration Contract

## Scope

Implemented the shared Python and Swift cleanup configuration contract on
`feature/storage-cleanup`.

- Python exposes `cleanup_enabled: bool` with default `True`.
- Python exposes `cleanup_interval_hours: int` with default `24` and controlled
  options `[24, 168]` in both field metadata and UI options.
- Every backend declares both cleanup keys as supported through the shared
  common-key set.
- Swift exposes `cleanupEnabled` and `cleanupIntervalHours`, defaults them to
  `true` and `24`, persists both raw config keys, includes them in local raw
  defaults, and validates the interval against the contract or `[24, 168]`
  fallback.
- Cleanup-only changes are classified as `SettingsApplyImpact.saveOnly`.

## TDD Evidence

### Python

1. Added cleanup contract assertions to
   `tests/test_config_contract.py::test_contract_contains_defaults_fields_and_backends`.
2. RED verified with:

   ```text
   .venv/bin/python -m pytest -q tests/test_config_contract.py::test_contract_contains_defaults_fields_and_backends
   FAILED: KeyError: 'cleanup_enabled'
   ```

3. Added the minimal Python defaults, common config keys, metadata, and UI
   options.
4. GREEN verified twice with:

   ```text
   .venv/bin/python -m pytest -q tests/test_config_contract.py
   6 passed
   ```

### Swift

1. Added `cleanupDefaultsAreBoundedAndPersist` to
   `JarvisConfigContractTests.swift` and `cleanupOnlyChangesDoNotRestartRuntime`
   to `SettingsStateTests.swift` before Swift implementation.
2. Attempted RED verification with:

   ```text
   swift test --package-path apps/macos/JarvisLine
   ```

3. Added the bounded Swift defaults, properties, initializer wiring,
   persistence, raw defaults, validation, and save-only normalization.
4. Attempted focused GREEN verification with:

   ```text
   swift test --package-path apps/macos/JarvisLine --filter 'cleanup'
   ```

## Local Swift Verification Limitation

Both Swift test commands failed before compiling the package manifest because
the active Command Line Tools SDK and Swift compiler do not match:

```text
SDK: Apple Swift version 6.3.2 effective-5.10
Compiler: Apple Swift version 6.3.3 effective-5.10
error: failed to build module 'Swift'; this SDK is not supported by the compiler
```

The sandbox also prevents SwiftPM from writing its normal user module-cache
path. The compiler/SDK mismatch remains after that warning and is the blocking
infrastructure failure. `xcodebuild -version` confirms that the active
developer directory is `/Library/Developer/CommandLineTools`, not a full Xcode
installation.

The release packaging gate was also attempted:

```text
scripts/verify-macos-artifacts.sh
```

It stopped at the same SwiftPM manifest error before application packaging.
Run the Swift test filter and release packaging verification in CI or on a
machine with a matching Xcode/SDK toolchain.

## Self-Review

- `git diff --check` passed.
- The implementation uses the exact defaults, option values, validation copy,
  and save-only normalization required by the task brief.
- The source diff is limited to the six owned implementation/test files; this
  report is the separately required task artifact.
