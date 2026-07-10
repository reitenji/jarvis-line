# Task 1 Report: Python Setup Domain Contract

## Implementation Summary

Added the versioned Python setup domain contract in `src/jarvis_line/setup_flow.py`.
The module provides:

- `SetupEnvironment`, `SetupPlan`, and `SetupContractError`.
- Full-language validation and strict plan field, enum, boolean, path, and command validation.
- Deterministic English Kokoro and non-English system TTS recommendations.
- Versioned inspection output with copied current config and UI options.
- Preset-based config construction that preserves existing values and applies setup selections.
- Instruction destination guidance for the supported agent targets.

Added the three contract and recommendation tests required by the brief in `tests/test_setup_flow.py`.

## TDD Evidence

### RED

Command:

```text
.venv/bin/python -m pytest tests/test_setup_flow.py -q
```

Output:

```text
==================================== ERRORS ====================================
__________________ ERROR collecting tests/test_setup_flow.py ___________________
ImportError while importing test module '/Users/serkances/Documents/Codex/2026-05-11/su-anda-aktif-olan-hooklari-arastir/tests/test_setup_flow.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_setup_flow.py:3: in <module>
    from jarvis_line import setup_flow
E   ImportError: cannot import name 'setup_flow' from 'jarvis_line' (/Users/serkances/Documents/Codex/2026-05-11/su-anda-aktif-olan-hooklari-arastir/src/jarvis_line/__init__.py)
=========================== short test summary info ============================
ERROR tests/test_setup_flow.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s
```

Exit code: `2`.

### Focused GREEN

Command:

```text
.venv/bin/python -m pytest tests/test_setup_flow.py -q
```

Output:

```text
...                                                                      [100%]
3 passed in 0.01s
```

Exit code: `0`.

### Full Python Suite

Command:

```text
.venv/bin/python -m pytest -q
```

Output:

```text
........................................................................ [ 52%]
..................................................................       [100%]
138 passed in 1.54s
```

Exit code: `0`.

## Files Changed

- `src/jarvis_line/setup_flow.py`
- `tests/test_setup_flow.py`
- `.superpowers/sdd/task-1-report.md`

No files outside the declared ownership were modified.

## Commit

Commit command:

```text
git add src/jarvis_line/setup_flow.py tests/test_setup_flow.py .superpowers/sdd/task-1-report.md
git commit -m "feat: add versioned setup domain"
```

The resulting commit is reported in the task completion status.

## Self-Review

- The module is pure domain code: it does not invoke subprocesses, perform network access, write files, or mutate the caller's config mapping.
- `SetupPlan.from_mapping()` rejects unknown fields before interpreting values and enforces the exact schema version and allowed enum values.
- Short ASCII language codes such as `tr` are rejected by plan validation, while inspection normalizes the known display aliases used for recommendations.
- Backend recommendation behavior matches the brief: ready Kokoro is recommended for English, and system TTS is recommended for Turkish.
- Config construction delegates preset semantics to the existing `config_contract` constants and removes unsupported backend fields through the existing capability definitions.
- `git diff --check` and Python bytecode compilation both completed successfully before the full suite.

## Concerns

No blocking concerns remain for Task 1. Interactive prompt helpers and CLI integration are intentionally deferred to the later guided-CLI task. The brief names `instruction_guidance()` but does not define a serialized return schema, so this task supplies a small dictionary shape for later integration; later tasks should keep that shape or codify any required changes with tests.
