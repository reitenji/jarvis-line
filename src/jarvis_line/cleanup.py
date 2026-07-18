from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


AUTO_AUDIO_AGE_SECONDS = 24 * 60 * 60
MANUAL_AUDIO_AGE_SECONDS = 10 * 60
TEMP_AGE_SECONDS = 60 * 60
ROTATED_LOG_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_ERROR_DETAILS = 50
MAX_LOCK_OWNER_BYTES = 4096
MAX_STATE_BYTES = 4096
GENERATED_PREFIXES = ("kokoro_", "jarvis_line_")
LOCK_OWNER_NAME = "owner.json"
LOCK_QUARANTINE_SUFFIX = ".cleanup-quarantine"
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
    operation_error_count: int = 0
    already_running: bool = False

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
        return self.operation_error_count + sum(
            category.error_count for category in self.categories.values()
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible_files": self.eligible_files,
            "eligible_bytes": self.eligible_bytes,
            "removed_files": self.removed_files,
            "removed_bytes": self.removed_bytes,
            "skipped_files": self.skipped_files,
            "error_count": self.error_count,
            "already_running": self.already_running,
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


@dataclass(frozen=True)
class _LockOwner:
    pid: int
    created_ts: int
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _AcquiredCleanupLock:
    directory: _Candidate
    owner: _LockOwner


def _record_error(report: CleanupReport, category: str, name: str) -> None:
    report.categories[category].error_count += 1
    if len(report.errors) < MAX_ERROR_DETAILS:
        report.errors.append({"category": category, "name": Path(name).name})


def _refused_report() -> CleanupReport:
    report = CleanupReport(operation_error_count=1)
    report.errors.append({"category": "cleanup", "name": "unmanaged_paths"})
    return report


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


def _same_directory_object(candidate: _Candidate, info: os.stat_result) -> bool:
    return (
        candidate.is_directory
        and stat.S_ISDIR(info.st_mode)
        and info.st_dev == candidate.device
        and info.st_ino == candidate.inode
    )


def _same_owner_identity(owner: _LockOwner, info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_dev == owner.device
        and info.st_ino == owner.inode
        and info.st_size == owner.size
        and info.st_mtime_ns == owner.mtime_ns
    )


def _validated_scandir(
    path: Path,
    report: CleanupReport,
    categories: str | tuple[str, ...],
):
    category_names = (categories,) if isinstance(categories, str) else categories

    def record_root_error() -> None:
        for category_name in category_names:
            _record_error(report, category_name, path.name)

    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        record_root_error()
        return None

    if not stat.S_ISDIR(info.st_mode):
        record_root_error()
        return None

    root = _candidate_from_stat(path, category_names[0], info, is_directory=True)
    try:
        entries = os.scandir(path)
    except FileNotFoundError:
        return None
    except OSError:
        record_root_error()
        return None

    try:
        current = path.lstat()
    except FileNotFoundError:
        entries.close()
        return None
    except OSError:
        entries.close()
        record_root_error()
        return None
    if not _same_identity(root, current):
        entries.close()
        record_root_error()
        return None
    return entries


def _read_lock_owner(candidate: _Candidate) -> _LockOwner | None:
    current_directory = candidate.path.lstat()
    if not _same_identity(candidate, current_directory):
        return None

    with os.scandir(candidate.path) as entries:
        owner_entry = next(entries, None)
        if (
            owner_entry is None
            or owner_entry.name != LOCK_OWNER_NAME
            or next(entries, None) is not None
        ):
            return None
        owner_info = owner_entry.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(owner_info.st_mode)
            or owner_info.st_size > MAX_LOCK_OWNER_BYTES
        ):
            return None

    if not _same_identity(candidate, candidate.path.lstat()):
        return None

    owner_path = candidate.path / LOCK_OWNER_NAME
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(owner_path, flags)
    try:
        opened_info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_info.st_mode)
            or opened_info.st_dev != owner_info.st_dev
            or opened_info.st_ino != owner_info.st_ino
            or opened_info.st_size != owner_info.st_size
            or opened_info.st_mtime_ns != owner_info.st_mtime_ns
        ):
            return None
        payload = os.read(descriptor, MAX_LOCK_OWNER_BYTES + 1)
    finally:
        os.close(descriptor)

    if len(payload) > MAX_LOCK_OWNER_BYTES:
        return None
    try:
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or set(record) != {"pid", "created_ts"}:
        return None
    pid = record["pid"]
    created_ts = record["created_ts"]
    if type(pid) is not int or pid <= 0 or type(created_ts) is not int:
        return None
    return _LockOwner(
        pid=pid,
        created_ts=created_ts,
        device=opened_info.st_dev,
        inode=opened_info.st_ino,
        size=opened_info.st_size,
        mtime_ns=opened_info.st_mtime_ns,
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _pid_is_dead(pid: int) -> bool:
    return not _pid_alive(pid)


def _directory_is_empty(path: Path) -> bool:
    with os.scandir(path) as entries:
        return next(entries, None) is None


def _lock_quarantine_path(path: Path) -> Path:
    return path.with_name(f"{path.name}{LOCK_QUARANTINE_SUFFIX}")


def _candidate_at_path(candidate: _Candidate, path: Path) -> _Candidate:
    return _Candidate(
        path=path,
        category=candidate.category,
        device=candidate.device,
        inode=candidate.inode,
        size=candidate.size,
        mtime_ns=candidate.mtime_ns,
        is_directory=candidate.is_directory,
    )


def _restore_claim(claimed: _Candidate, original_path: Path) -> bool:
    try:
        current_claim = claimed.path.lstat()
    except OSError:
        return False
    if not _same_directory_object(claimed, current_claim):
        return False

    try:
        original_path.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    else:
        return False

    try:
        claimed.path.rename(original_path)
    except OSError:
        return False
    return True


def _restore_lock_owner(path: Path, owner: _LockOwner) -> bool:
    payload = json.dumps(
        {"pid": owner.pid, "created_ts": owner.created_ts},
        separators=(",", ":"),
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path / LOCK_OWNER_NAME, flags, 0o600)
    except OSError:
        return False
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return True


def _rollback_lock_claim(
    claimed: _Candidate,
    original_path: Path,
    owner: _LockOwner,
    *,
    owner_removed: bool,
) -> bool:
    try:
        current_claim = claimed.path.lstat()
    except OSError:
        return False
    if not _same_directory_object(claimed, current_claim):
        return False
    if owner_removed and not _restore_lock_owner(claimed.path, owner):
        return False
    return _restore_claim(claimed, original_path)


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


def _process_lock_candidate(
    candidate: _Candidate,
    owner: _LockOwner,
    report: CleanupReport,
    *,
    delete: bool,
) -> None:
    category = report.categories[candidate.category]
    category.eligible_files += 1
    if not delete:
        return

    try:
        current_owner = _read_lock_owner(candidate)
    except FileNotFoundError:
        category.skipped_files += 1
        return
    except OSError:
        _record_error(report, candidate.category, candidate.path.name)
        return
    if current_owner != owner or not _pid_is_dead(owner.pid):
        category.skipped_files += 1
        return

    quarantine_path = _lock_quarantine_path(candidate.path)
    try:
        quarantine_path.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        _record_error(report, candidate.category, candidate.path.name)
        return
    else:
        category.skipped_files += 1
        return

    try:
        final_owner = _read_lock_owner(candidate)
        current_directory = candidate.path.lstat()
        current_owner_info = (candidate.path / LOCK_OWNER_NAME).lstat()
    except FileNotFoundError:
        category.skipped_files += 1
        return
    except OSError:
        _record_error(report, candidate.category, candidate.path.name)
        return
    if (
        final_owner != owner
        or not _same_identity(candidate, current_directory)
        or not _same_owner_identity(owner, current_owner_info)
    ):
        category.skipped_files += 1
        return

    try:
        candidate.path.rename(quarantine_path)
    except FileNotFoundError:
        category.skipped_files += 1
        return
    except OSError:
        _record_error(report, candidate.category, candidate.path.name)
        return

    claimed = _candidate_at_path(candidate, quarantine_path)
    try:
        claimed_owner = _read_lock_owner(claimed)
    except (FileNotFoundError, OSError):
        _restore_claim(claimed, candidate.path)
        category.skipped_files += 1
        return
    if claimed_owner != owner or not _pid_is_dead(owner.pid):
        _restore_claim(claimed, candidate.path)
        category.skipped_files += 1
        return

    owner_removed = False
    try:
        (claimed.path / LOCK_OWNER_NAME).unlink()
        owner_removed = True
        current_directory = claimed.path.lstat()
        if not _same_directory_object(claimed, current_directory):
            raise FileNotFoundError
        if not _directory_is_empty(claimed.path):
            _rollback_lock_claim(
                claimed,
                candidate.path,
                owner,
                owner_removed=True,
            )
            category.skipped_files += 1
            return
        current_directory = claimed.path.lstat()
        if not _same_directory_object(claimed, current_directory):
            raise FileNotFoundError
        claimed.path.rmdir()
    except FileNotFoundError:
        _rollback_lock_claim(
            claimed,
            candidate.path,
            owner,
            owner_removed=owner_removed,
        )
        category.skipped_files += 1
        return
    except OSError:
        _rollback_lock_claim(
            claimed,
            candidate.path,
            owner,
            owner_removed=owner_removed,
        )
        _record_error(report, candidate.category, candidate.path.name)
        return

    category.removed_files += 1


def _scan_generated_audio(
    paths: CleanupPaths,
    report: CleanupReport,
    *,
    now: float,
    minimum_age: int,
    delete: bool,
) -> None:
    category_name = "generated_audio"
    entries = _validated_scandir(paths.generated_audio_dir, report, category_name)
    if entries is None:
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
        name.startswith(f"{target}.")
        if target.startswith(".")
        else name.startswith(f".{target}.")
        for target in ATOMIC_TARGET_NAMES
    )


def _scan_hooks(
    paths: CleanupPaths,
    report: CleanupReport,
    *,
    now: float,
    delete: bool,
) -> None:
    entries = _validated_scandir(
        paths.hooks_dir,
        report,
        ("rotated_logs", "runtime_temp", "stale_locks"),
    )
    if entries is None:
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
                candidate = _candidate_from_stat(
                    path,
                    category_name,
                    info,
                    is_directory=True,
                )
                try:
                    owner = _read_lock_owner(candidate)
                    if owner is None:
                        continue
                except FileNotFoundError:
                    report.categories[category_name].skipped_files += 1
                    continue
                except OSError:
                    _record_error(report, category_name, entry.name)
                    continue
                if now - owner.created_ts <= minimum_age or not _pid_is_dead(
                    owner.pid
                ):
                    continue
                _process_lock_candidate(
                    candidate,
                    owner,
                    report,
                    delete=delete,
                )
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


def _bool(value: object, default: bool) -> bool:
    return value if type(value) is bool else default


def _interval_hours(value: object) -> int:
    return value if type(value) is int and value in (24, 168) else 24


def _read_state(path: Path) -> dict[str, int]:
    state = {"last_attempt_ts": 0, "last_success_ts": 0}
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
            return state
        payload = os.read(descriptor, MAX_STATE_BYTES + 1)
        record = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return state
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if not isinstance(record, dict):
        return state
    for key in state:
        value = record.get(key)
        if type(value) is int and value >= 0:
            state[key] = value
    return state


def _write_state(path: Path, state: Mapping[str, int]) -> None:
    bounded = {
        "last_attempt_ts": int(state.get("last_attempt_ts", 0)),
        "last_success_ts": int(state.get("last_success_ts", 0)),
    }
    payload = json.dumps(bounded, separators=(",", ":")) + "\n"
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_name = temporary.name
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _operation_error_report(name: str) -> CleanupReport:
    report = CleanupReport(operation_error_count=1)
    report.errors.append({"category": "cleanup", "name": Path(name).name})
    return report


def _record_operation_error(report: CleanupReport, name: str) -> None:
    report.operation_error_count += 1
    if len(report.errors) < MAX_ERROR_DETAILS:
        report.errors.append({"category": "cleanup", "name": Path(name).name})


def _cleanup_lock_candidate(path: Path) -> _Candidate | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        return None
    return _candidate_from_stat(path, "cleanup", info, is_directory=True)


def _remove_claimed_cleanup_lock(
    claimed: _Candidate,
    expected_owner: _LockOwner | None,
) -> bool:
    try:
        if not _same_directory_object(claimed, claimed.path.lstat()):
            return False
        with os.scandir(claimed.path) as entries:
            entry = next(entries, None)
            if entry is None:
                claimed.path.rmdir()
                return True
            if entry.name != LOCK_OWNER_NAME or next(entries, None) is not None:
                return False
            owner_info = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(owner_info.st_mode):
            return False
        if expected_owner is not None and not _same_owner_identity(
            expected_owner, owner_info
        ):
            return False
        if not _same_directory_object(claimed, claimed.path.lstat()):
            return False
        owner_path = claimed.path / LOCK_OWNER_NAME
        if not _same_identity(
            _candidate_from_stat(owner_path, "cleanup", owner_info),
            owner_path.lstat(),
        ):
            return False
        owner_path.unlink()
        if not _same_directory_object(claimed, claimed.path.lstat()):
            return False
        if not _directory_is_empty(claimed.path):
            return False
        claimed.path.rmdir()
        return True
    except OSError:
        return False


def _recover_cleanup_lock(candidate: _Candidate, *, now: float) -> bool:
    age_seconds = now - (candidate.mtime_ns / 1_000_000_000)
    if age_seconds <= TEMP_AGE_SECONDS:
        return False
    try:
        owner = _read_lock_owner(candidate)
    except OSError:
        return False
    if owner is not None and _pid_alive(owner.pid):
        return False

    quarantine_path = _lock_quarantine_path(candidate.path)
    try:
        quarantine_path.lstat()
        return False
    except FileNotFoundError:
        pass
    except OSError:
        return False

    try:
        if not _same_identity(candidate, candidate.path.lstat()):
            return False
        current_owner = _read_lock_owner(candidate)
        if owner is None:
            if current_owner is not None:
                return False
        elif current_owner is None or not _same_owner_identity(
            owner, (candidate.path / LOCK_OWNER_NAME).lstat()
        ):
            return False
        elif _pid_alive(current_owner.pid):
            return False
        os.rename(candidate.path, quarantine_path)
    except OSError:
        return False

    claimed = _candidate_at_path(candidate, quarantine_path)
    try:
        if not _same_directory_object(claimed, claimed.path.lstat()):
            return False
        claimed_owner = _read_lock_owner(claimed)
        if owner is None:
            if claimed_owner is not None:
                _restore_claim(claimed, candidate.path)
                return False
        elif claimed_owner is None or not _same_owner_identity(
            owner, (claimed.path / LOCK_OWNER_NAME).lstat()
        ):
            _restore_claim(claimed, candidate.path)
            return False
        elif _pid_alive(claimed_owner.pid):
            _restore_claim(claimed, candidate.path)
            return False
    except OSError:
        _restore_claim(claimed, candidate.path)
        return False

    if _remove_claimed_cleanup_lock(claimed, owner):
        return True
    _restore_claim(claimed, candidate.path)
    return False


def _release_cleanup_lock(acquired: _AcquiredCleanupLock) -> None:
    directory = acquired.directory
    owner_path = directory.path / LOCK_OWNER_NAME
    try:
        if not _same_directory_object(directory, directory.path.lstat()):
            return
        if not _same_owner_identity(acquired.owner, owner_path.lstat()):
            return
        owner_path.unlink()
        if not _same_directory_object(directory, directory.path.lstat()):
            return
        if _directory_is_empty(directory.path):
            directory.path.rmdir()
    except OSError:
        return


def _acquire_cleanup_lock(paths: CleanupPaths, *, now: float) -> _AcquiredCleanupLock | None:
    try:
        try:
            hooks_info = paths.hooks_dir.lstat()
        except FileNotFoundError:
            paths.hooks_dir.mkdir(parents=True, exist_ok=True)
            hooks_info = paths.hooks_dir.lstat()
        if not stat.S_ISDIR(hooks_info.st_mode):
            raise OSError("invalid hooks root")
        hooks_root = _candidate_from_stat(
            paths.hooks_dir,
            "cleanup",
            hooks_info,
            is_directory=True,
        )

        for _attempt in range(2):
            try:
                paths.lock_dir.mkdir()
            except FileExistsError:
                candidate = _cleanup_lock_candidate(paths.lock_dir)
                if candidate is None or not _recover_cleanup_lock(candidate, now=now):
                    return None
                continue

            directory = _cleanup_lock_candidate(paths.lock_dir)
            if directory is None:
                raise OSError("invalid cleanup lock")
            owner_path = paths.lock_dir / LOCK_OWNER_NAME
            owner_path.write_text(
                json.dumps({"pid": os.getpid(), "created_ts": int(now)}),
                encoding="utf-8",
            )
            os.chmod(owner_path, 0o600)
            directory = _cleanup_lock_candidate(paths.lock_dir)
            if directory is None:
                raise OSError("invalid cleanup lock")
            owner = _read_lock_owner(directory)
            if owner is None:
                raise OSError("invalid cleanup lock owner")
            acquired = _AcquiredCleanupLock(directory=directory, owner=owner)
            if not _same_directory_object(hooks_root, paths.hooks_dir.lstat()):
                _release_cleanup_lock(acquired)
                raise OSError("changed hooks root")
            return acquired
    except OSError:
        candidate = _cleanup_lock_candidate(paths.lock_dir)
        if candidate is not None:
            try:
                owner = _read_lock_owner(candidate)
            except OSError:
                owner = None
            if owner is not None and owner.pid == os.getpid():
                _release_cleanup_lock(
                    _AcquiredCleanupLock(directory=candidate, owner=owner)
                )
        raise
    return None


def _is_due(state: Mapping[str, int], *, now: float, interval_seconds: int) -> bool:
    last_attempt = state.get("last_attempt_ts", 0)
    return last_attempt <= 0 or now - last_attempt >= interval_seconds


def _run_with_lock(
    paths: CleanupPaths,
    *,
    now: float,
    automatic: bool,
    update_state: bool,
    interval_seconds: int = 0,
) -> CleanupReport | None:
    try:
        acquired = _acquire_cleanup_lock(paths, now=now)
    except OSError:
        return _operation_error_report(paths.lock_dir.name)
    if acquired is None:
        return CleanupReport(already_running=True)

    try:
        state = _read_state(paths.state_path)
        if update_state:
            if not _is_due(state, now=now, interval_seconds=interval_seconds):
                return None
            state["last_attempt_ts"] = int(now)
            try:
                _write_state(paths.state_path, state)
            except OSError:
                return _operation_error_report(paths.state_path.name)

        audio_age = AUTO_AUDIO_AGE_SECONDS if automatic else MANUAL_AUDIO_AGE_SECONDS
        report = _execute(
            paths,
            now=now,
            audio_age=audio_age,
            delete=True,
        )
        if update_state and report.error_count == 0:
            state["last_success_ts"] = int(now)
            try:
                _write_state(paths.state_path, state)
            except OSError:
                _record_operation_error(report, paths.state_path.name)
        return report
    finally:
        _release_cleanup_lock(acquired)


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
    managed_paths = CleanupPaths.default()
    if paths is not None and paths != managed_paths:
        return _refused_report()
    selected_paths = managed_paths
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
    managed_paths = CleanupPaths.default()
    if paths is not None and paths != managed_paths:
        return _refused_report()
    selected_paths = managed_paths
    selected_now = time.time() if now is None else now
    report = _run_with_lock(
        selected_paths,
        now=selected_now,
        automatic=automatic,
        update_state=False,
    )
    assert report is not None
    return report


def run_if_due(
    config: Mapping[str, object],
    paths: CleanupPaths | None = None,
    now: float | None = None,
) -> CleanupReport | None:
    if not _bool(config.get("cleanup_enabled"), True):
        return None
    managed_paths = CleanupPaths.default()
    if paths is not None and paths != managed_paths:
        return _refused_report()
    selected_paths = managed_paths
    selected_now = time.time() if now is None else now
    interval_seconds = _interval_hours(
        config.get("cleanup_interval_hours")
    ) * 60 * 60
    state = _read_state(selected_paths.state_path)
    if not _is_due(state, now=selected_now, interval_seconds=interval_seconds):
        return None
    return _run_with_lock(
        selected_paths,
        now=selected_now,
        automatic=True,
        update_state=True,
        interval_seconds=interval_seconds,
    )
