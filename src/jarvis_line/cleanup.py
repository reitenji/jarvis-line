from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path


AUTO_AUDIO_AGE_SECONDS = 24 * 60 * 60
MANUAL_AUDIO_AGE_SECONDS = 10 * 60
TEMP_AGE_SECONDS = 60 * 60
ROTATED_LOG_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_ERROR_DETAILS = 50
GENERATED_PREFIXES = ("kokoro_", "jarvis_line_")
ROTATED_LOG_NAMES = (
    "jarvis_line_watcher.log.1",
    "jarvis_line_audio_worker.log.1",
)
ATOMIC_TARGET_NAMES = (
    "jarvis_line_config.json",
    "jarvis_line_audio_queue.json",
    "jarvis_line_latest_messages.json",
    ".jarvis_line_state.json",
    ".jarvis_line_cleanup_state.json",
    "jarvis_line_trace.jsonl",
)
STALE_LOCK_DIR_NAMES = (
    ".jarvis_line.lock.d",
    ".jarvis_line_audio.lock.d",
    ".jarvis_line_trace.lock.d",
)

CATEGORY_NAMES = (
    "generated_audio",
    "rotated_logs",
    "runtime_temp",
    "stale_locks",
)


@dataclass(frozen=True)
class CleanupPaths:
    hooks_dir: Path
    generated_audio_dir: Path
    state_path: Path
    lock_dir: Path
    watcher_log: Path
    worker_log: Path

    @classmethod
    def default(cls) -> "CleanupPaths":
        home = Path.home()
        hooks = home / ".codex" / "hooks"
        return cls(
            hooks_dir=hooks,
            generated_audio_dir=home / ".jarvis-line" / "tts" / "generated",
            state_path=hooks / ".jarvis_line_cleanup_state.json",
            lock_dir=hooks / ".jarvis_line_cleanup.lock.d",
            watcher_log=hooks / "jarvis_line_watcher.log",
            worker_log=hooks / "jarvis_line_audio_worker.log",
        )


@dataclass
class CategoryReport:
    eligible_files: int = 0
    eligible_bytes: int = 0
    removed_files: int = 0
    removed_bytes: int = 0
    skipped_files: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "eligible_files": self.eligible_files,
            "eligible_bytes": self.eligible_bytes,
            "removed_files": self.removed_files,
            "removed_bytes": self.removed_bytes,
            "skipped_files": self.skipped_files,
            "error_count": self.error_count,
        }


@dataclass
class CleanupReport:
    categories: dict[str, CategoryReport] = field(
        default_factory=lambda: {name: CategoryReport() for name in CATEGORY_NAMES}
    )
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def eligible_files(self) -> int:
        return sum(category.eligible_files for category in self.categories.values())

    @property
    def eligible_bytes(self) -> int:
        return sum(category.eligible_bytes for category in self.categories.values())

    @property
    def removed_files(self) -> int:
        return sum(category.removed_files for category in self.categories.values())

    @property
    def removed_bytes(self) -> int:
        return sum(category.removed_bytes for category in self.categories.values())

    @property
    def skipped_files(self) -> int:
        return sum(category.skipped_files for category in self.categories.values())

    @property
    def error_count(self) -> int:
        return sum(category.error_count for category in self.categories.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible_files": self.eligible_files,
            "eligible_bytes": self.eligible_bytes,
            "removed_files": self.removed_files,
            "removed_bytes": self.removed_bytes,
            "skipped_files": self.skipped_files,
            "error_count": self.error_count,
            "errors": [dict(error) for error in self.errors],
            "categories": {
                name: self.categories[name].to_dict() for name in CATEGORY_NAMES
            },
        }


@dataclass(frozen=True)
class _Candidate:
    path: Path
    category: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    is_directory: bool = False


def _record_error(report: CleanupReport, category: str, name: str) -> None:
    report.categories[category].error_count += 1
    if len(report.errors) < MAX_ERROR_DETAILS:
        report.errors.append({"category": category, "name": Path(name).name})


def _candidate_from_stat(
    path: Path,
    category: str,
    info: os.stat_result,
    *,
    is_directory: bool = False,
) -> _Candidate:
    return _Candidate(
        path=path,
        category=category,
        device=info.st_dev,
        inode=info.st_ino,
        size=0 if is_directory else info.st_size,
        mtime_ns=info.st_mtime_ns,
        is_directory=is_directory,
    )


def _same_identity(candidate: _Candidate, info: os.stat_result) -> bool:
    type_matches = (
        stat.S_ISDIR(info.st_mode)
        if candidate.is_directory
        else stat.S_ISREG(info.st_mode)
    )
    return (
        type_matches
        and info.st_dev == candidate.device
        and info.st_ino == candidate.inode
        and (candidate.is_directory or info.st_size == candidate.size)
        and info.st_mtime_ns == candidate.mtime_ns
    )


def _directory_is_empty(path: Path) -> bool:
    with os.scandir(path) as entries:
        return next(entries, None) is None


def _process_candidate(
    candidate: _Candidate,
    report: CleanupReport,
    *,
    delete: bool,
) -> None:
    category = report.categories[candidate.category]
    category.eligible_files += 1
    category.eligible_bytes += candidate.size
    if not delete:
        return

    try:
        current = candidate.path.lstat()
    except FileNotFoundError:
        category.skipped_files += 1
        return
    except OSError:
        _record_error(report, candidate.category, candidate.path.name)
        return

    if not _same_identity(candidate, current):
        category.skipped_files += 1
        return

    try:
        if candidate.is_directory:
            if not _directory_is_empty(candidate.path):
                category.skipped_files += 1
                return
            if not _same_identity(candidate, candidate.path.lstat()):
                category.skipped_files += 1
                return
            candidate.path.rmdir()
        else:
            candidate.path.unlink()
    except FileNotFoundError:
        category.skipped_files += 1
        return
    except OSError:
        _record_error(report, candidate.category, candidate.path.name)
        return

    category.removed_files += 1
    category.removed_bytes += candidate.size


def _scan_generated_audio(
    paths: CleanupPaths,
    report: CleanupReport,
    *,
    now: float,
    minimum_age: int,
    delete: bool,
) -> None:
    category_name = "generated_audio"
    try:
        entries = os.scandir(paths.generated_audio_dir)
    except FileNotFoundError:
        return
    except OSError:
        _record_error(report, category_name, paths.generated_audio_dir.name)
        return

    with entries:
        for entry in entries:
            if not entry.name.startswith(GENERATED_PREFIXES):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                report.categories[category_name].skipped_files += 1
                continue
            except OSError:
                _record_error(report, category_name, entry.name)
                continue
            if not stat.S_ISREG(info.st_mode):
                report.categories[category_name].skipped_files += 1
                continue
            if now - info.st_mtime <= minimum_age:
                continue
            _process_candidate(
                _candidate_from_stat(Path(entry.path), category_name, info),
                report,
                delete=delete,
            )


def _is_atomic_temporary(name: str) -> bool:
    return name.endswith(".tmp") and any(
        name.startswith(f".{target}.") for target in ATOMIC_TARGET_NAMES
    )


def _scan_hooks(
    paths: CleanupPaths,
    report: CleanupReport,
    *,
    now: float,
    delete: bool,
) -> None:
    try:
        entries = os.scandir(paths.hooks_dir)
    except FileNotFoundError:
        return
    except OSError:
        _record_error(report, "runtime_temp", paths.hooks_dir.name)
        return

    cleanup_lock = os.path.abspath(paths.lock_dir)
    with entries:
        for entry in entries:
            category_name: str
            minimum_age: int
            expect_directory = False
            if entry.name in ROTATED_LOG_NAMES:
                category_name = "rotated_logs"
                minimum_age = ROTATED_LOG_AGE_SECONDS
            elif _is_atomic_temporary(entry.name):
                category_name = "runtime_temp"
                minimum_age = TEMP_AGE_SECONDS
            elif entry.name in STALE_LOCK_DIR_NAMES:
                if os.path.abspath(entry.path) == cleanup_lock:
                    continue
                category_name = "stale_locks"
                minimum_age = TEMP_AGE_SECONDS
                expect_directory = True
            else:
                continue

            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                report.categories[category_name].skipped_files += 1
                continue
            except OSError:
                _record_error(report, category_name, entry.name)
                continue

            type_matches = (
                stat.S_ISDIR(info.st_mode)
                if expect_directory
                else stat.S_ISREG(info.st_mode)
            )
            if not type_matches:
                report.categories[category_name].skipped_files += 1
                continue
            if now - info.st_mtime <= minimum_age:
                continue

            path = Path(entry.path)
            if expect_directory:
                try:
                    if not _directory_is_empty(path):
                        continue
                except FileNotFoundError:
                    report.categories[category_name].skipped_files += 1
                    continue
                except OSError:
                    _record_error(report, category_name, entry.name)
                    continue

            _process_candidate(
                _candidate_from_stat(
                    path,
                    category_name,
                    info,
                    is_directory=expect_directory,
                ),
                report,
                delete=delete,
            )


def _execute(
    paths: CleanupPaths,
    *,
    now: float,
    audio_age: int,
    delete: bool,
) -> CleanupReport:
    report = CleanupReport()
    _scan_generated_audio(
        paths,
        report,
        now=now,
        minimum_age=audio_age,
        delete=delete,
    )
    _scan_hooks(paths, report, now=now, delete=delete)
    return report


def inspect(
    paths: CleanupPaths | None = None,
    now: float | None = None,
) -> CleanupReport:
    selected_paths = paths or CleanupPaths.default()
    selected_now = time.time() if now is None else now
    return _execute(
        selected_paths,
        now=selected_now,
        audio_age=MANUAL_AUDIO_AGE_SECONDS,
        delete=False,
    )


def run(
    paths: CleanupPaths | None = None,
    now: float | None = None,
    automatic: bool = False,
) -> CleanupReport:
    selected_paths = paths or CleanupPaths.default()
    selected_now = time.time() if now is None else now
    audio_age = AUTO_AUDIO_AGE_SECONDS if automatic else MANUAL_AUDIO_AGE_SECONDS
    return _execute(
        selected_paths,
        now=selected_now,
        audio_age=audio_age,
        delete=True,
    )
