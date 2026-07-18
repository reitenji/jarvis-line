import json
import os
from pathlib import Path

import pytest

from jarvis_line import cleanup


@pytest.fixture(autouse=True)
def managed_home(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup.Path, "home", classmethod(lambda _cls: tmp_path))


def paths_for(root: Path) -> cleanup.CleanupPaths:
    paths = cleanup.CleanupPaths.default()
    paths.hooks_dir.mkdir(parents=True)
    paths.generated_audio_dir.mkdir(parents=True)
    return paths


def quarantine_for(lock: Path) -> Path:
    return lock.with_name(f"{lock.name}.cleanup-quarantine")


def age(path: Path, seconds: int, now: float = 1_000_000) -> None:
    os.utime(path, (now - seconds, now - seconds))


def write_lock_owner(
    directory: Path,
    *,
    pid: int = 42,
    created_ts: int = 1_000_000 - cleanup.TEMP_AGE_SECONDS - 1,
) -> Path:
    owner = directory / "owner.json"
    owner.write_text(json.dumps({"pid": pid, "created_ts": created_ts}))
    return owner


def test_manual_run_removes_old_generated_audio_but_keeps_recent_and_unknown(tmp_path):
    paths = paths_for(tmp_path)
    old = paths.generated_audio_dir / "kokoro_1.wav"
    recent = paths.generated_audio_dir / "jarvis_line_2.wav"
    unknown = paths.generated_audio_dir / "voice-model.bin"
    for path in (old, recent, unknown):
        path.write_bytes(b"audio")
    age(old, 601)
    age(recent, 599)
    age(unknown, 86_400)

    report = cleanup.run(paths, now=1_000_000)

    assert not old.exists()
    assert recent.exists()
    assert unknown.exists()
    assert report.removed_files == 1
    assert report.removed_bytes == 5


def test_cleanup_never_follows_generated_audio_symlink(tmp_path):
    paths = paths_for(tmp_path)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"private")
    link = paths.generated_audio_dir / "kokoro_link.wav"
    link.symlink_to(outside)
    age(link, 86_400)

    report = cleanup.run(paths, now=1_000_000)

    assert outside.read_bytes() == b"private"
    assert link.is_symlink()
    assert report.skipped_files == 1


def test_cleanup_never_scans_a_symlinked_generated_audio_root(tmp_path):
    paths = paths_for(tmp_path)
    outside = tmp_path / "private-generated"
    outside.mkdir()
    external_audio = outside / "kokoro_external.wav"
    external_audio.write_bytes(b"private")
    age(external_audio, cleanup.MANUAL_AUDIO_AGE_SECONDS + 1)
    paths.generated_audio_dir.rmdir()
    paths.generated_audio_dir.symlink_to(outside, target_is_directory=True)

    report = cleanup.run(paths, now=1_000_000)

    assert external_audio.read_bytes() == b"private"
    assert report.categories["generated_audio"].eligible_files == 0
    assert report.categories["generated_audio"].removed_files == 0
    assert str(outside) not in str(report.to_dict())


def test_cleanup_never_scans_a_symlinked_hooks_root(tmp_path):
    paths = paths_for(tmp_path)
    outside = tmp_path / "private-hooks"
    outside.mkdir()
    external_temp = outside / ".jarvis_line_config.json.old.tmp"
    external_temp.write_bytes(b"private")
    age(external_temp, cleanup.TEMP_AGE_SECONDS + 1)
    paths.hooks_dir.rmdir()
    paths.hooks_dir.symlink_to(outside, target_is_directory=True)

    report = cleanup.run(paths, now=1_000_000)

    assert external_temp.read_bytes() == b"private"
    assert report.categories["runtime_temp"].eligible_files == 0
    assert report.categories["runtime_temp"].removed_files == 0
    assert str(outside) not in str(report.to_dict())


def test_automatic_run_uses_24_hour_audio_age(tmp_path):
    paths = paths_for(tmp_path)
    old = paths.generated_audio_dir / "kokoro_old.wav"
    recent = paths.generated_audio_dir / "jarvis_line_recent.wav"
    old.write_bytes(b"old")
    recent.write_bytes(b"recent")
    age(old, cleanup.AUTO_AUDIO_AGE_SECONDS + 1)
    age(recent, cleanup.AUTO_AUDIO_AGE_SECONDS - 1)

    report = cleanup.run(paths, now=1_000_000, automatic=True)

    assert not old.exists()
    assert recent.exists()
    assert report.removed_files == 1


def test_inspect_reports_eligible_audio_without_deleting(tmp_path):
    paths = paths_for(tmp_path)
    old = paths.generated_audio_dir / "kokoro_old.wav"
    old.write_bytes(b"audio")
    age(old, cleanup.MANUAL_AUDIO_AGE_SECONDS + 1)

    report = cleanup.inspect(paths, now=1_000_000)

    assert old.exists()
    assert report.eligible_files == 1
    assert report.eligible_bytes == 5
    assert report.removed_files == 0


@pytest.mark.parametrize("operation", [cleanup.inspect, cleanup.run])
def test_public_cleanup_rejects_arbitrary_external_roots(tmp_path, operation):
    managed = paths_for(tmp_path)
    external_hooks = tmp_path / "external-hooks"
    external_audio = tmp_path / "external-audio"
    external_hooks.mkdir()
    external_audio.mkdir()
    external = cleanup.CleanupPaths(
        hooks_dir=external_hooks,
        generated_audio_dir=external_audio,
        state_path=external_hooks / managed.state_path.name,
        lock_dir=external_hooks / managed.lock_dir.name,
        watcher_log=external_hooks / managed.watcher_log.name,
        worker_log=external_hooks / managed.worker_log.name,
    )
    candidate = external_audio / "kokoro_private.wav"
    candidate.write_bytes(b"private")
    age(candidate, cleanup.MANUAL_AUDIO_AGE_SECONDS + 1)

    report = operation(external, now=1_000_000)

    assert candidate.read_bytes() == b"private"
    assert report.eligible_files == 0
    assert report.removed_files == 0
    assert report.error_count == 1
    assert report.errors == [{"category": "cleanup", "name": "unmanaged_paths"}]
    assert report.mode == ("status" if operation is cleanup.inspect else "run")
    assert str(external_hooks) not in str(report.to_dict())
    assert str(external_audio) not in str(report.to_dict())


def test_run_removes_only_exact_old_diagnostics_and_atomic_temp_allowlists(tmp_path):
    paths = paths_for(tmp_path)
    rotated = paths.watcher_log.with_suffix(".log.1")
    temporary = paths.hooks_dir / ".jarvis_line_audio_queue.json.1.2.tmp"
    state_temporary = paths.hooks_dir / ".jarvis_line_cleanup_state.json.old.tmp"
    current_log = paths.watcher_log
    current_queue = paths.hooks_dir / "jarvis_line_audio_queue.json"
    current_state = paths.state_path
    unexpected_temp = paths.hooks_dir / "tmp123"
    near_match_log = paths.hooks_dir / "jarvis_line_watcher.log.2"
    near_match_temp = paths.hooks_dir / ".unknown.json.1.2.tmp"
    for path in (
        rotated,
        temporary,
        state_temporary,
        current_log,
        current_queue,
        current_state,
        unexpected_temp,
        near_match_log,
        near_match_temp,
    ):
        path.write_bytes(path.name.encode())
        age(path, cleanup.ROTATED_LOG_AGE_SECONDS + 1)

    report = cleanup.run(paths, now=1_000_000)

    assert not rotated.exists()
    assert not temporary.exists()
    assert not state_temporary.exists()
    assert current_log.exists()
    assert current_queue.exists()
    assert current_state.exists()
    assert unexpected_temp.exists()
    assert near_match_log.exists()
    assert near_match_temp.exists()
    assert report.removed_files == 3
    assert report.categories["rotated_logs"].removed_files == 1
    assert report.categories["runtime_temp"].removed_files == 2


def test_runtime_temp_requires_one_hour_age(tmp_path):
    paths = paths_for(tmp_path)
    old = paths.hooks_dir / ".jarvis_line_config.json.old.tmp"
    recent = paths.hooks_dir / ".jarvis_line_latest_messages.json.new.tmp"
    old.write_bytes(b"old")
    recent.write_bytes(b"recent")
    age(old, cleanup.TEMP_AGE_SECONDS + 1)
    age(recent, cleanup.TEMP_AGE_SECONDS - 1)

    cleanup.run(paths, now=1_000_000)

    assert not old.exists()
    assert recent.exists()


def test_rotated_log_requires_seven_day_age(tmp_path):
    paths = paths_for(tmp_path)
    recent = paths.worker_log.with_suffix(".log.1")
    recent.write_bytes(b"recent")
    age(recent, cleanup.ROTATED_LOG_AGE_SECONDS - 1)

    cleanup.run(paths, now=1_000_000)

    assert recent.exists()


def test_cleanup_keeps_candidates_at_the_exact_age_threshold(tmp_path):
    paths = paths_for(tmp_path)
    manual_audio = paths.generated_audio_dir / "kokoro_manual.wav"
    temporary = paths.hooks_dir / ".jarvis_line_trace.jsonl.exact.tmp"
    rotated = paths.worker_log.with_suffix(".log.1")
    stale_lock = paths.hooks_dir / ".jarvis_line_audio.lock.d"
    stale_lock.mkdir()
    manual_cases = (
        (manual_audio, cleanup.MANUAL_AUDIO_AGE_SECONDS),
        (temporary, cleanup.TEMP_AGE_SECONDS),
        (rotated, cleanup.ROTATED_LOG_AGE_SECONDS),
        (stale_lock, cleanup.TEMP_AGE_SECONDS),
    )
    for path, seconds in manual_cases:
        if not path.is_dir():
            path.write_bytes(b"data")
        age(path, seconds)

    cleanup.run(paths, now=1_000_000)

    assert all(path.exists() for path, _seconds in manual_cases)

    automatic_audio = paths.generated_audio_dir / "kokoro_automatic.wav"
    automatic_audio.write_bytes(b"data")
    age(automatic_audio, cleanup.AUTO_AUDIO_AGE_SECONDS)
    cleanup.run(paths, now=1_000_000, automatic=True)

    assert automatic_audio.exists()


def test_lock_owner_read_tolerates_handle_timestamp_differences(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    paths.lock_dir.mkdir()
    write_lock_owner(paths.lock_dir, pid=123, created_ts=456)
    directory = cleanup._cleanup_lock_candidate(paths.lock_dir)
    assert directory is not None
    real_fstat = cleanup.os.fstat

    def windows_style_fstat(descriptor):
        info = real_fstat(descriptor)
        return type(
            "WindowsStyleStat",
            (),
            {
                "st_mode": info.st_mode,
                "st_dev": 0,
                "st_ino": 0,
                "st_size": info.st_size,
                "st_mtime_ns": info.st_mtime_ns + 1,
            },
        )()

    monkeypatch.setattr(cleanup.os, "fstat", windows_style_fstat)
    monkeypatch.setattr(cleanup, "_IS_WINDOWS", True, raising=False)

    owner = cleanup._read_lock_owner(directory)

    assert owner is not None
    assert owner.pid == 123
    assert owner.created_ts == 456


def test_run_removes_only_old_known_lock_with_a_dead_recorded_owner(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    stale = paths.hooks_dir / ".jarvis_line.lock.d"
    recent = paths.hooks_dir / ".jarvis_line_audio.lock.d"
    nonempty = paths.hooks_dir / ".jarvis_line_trace.lock.d"
    cleanup_lock = paths.lock_dir
    unknown = paths.hooks_dir / ".unknown.lock.d"
    for directory in (stale, recent, nonempty, cleanup_lock, unknown):
        directory.mkdir()
        write_lock_owner(directory)
    (nonempty / "unexpected").write_text("busy")
    age(stale, cleanup.TEMP_AGE_SECONDS + 1)
    age(recent, cleanup.TEMP_AGE_SECONDS - 1)
    age(nonempty, cleanup.TEMP_AGE_SECONDS + 1)
    age(cleanup_lock, cleanup.TEMP_AGE_SECONDS + 1)
    age(unknown, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )

    report = cleanup.run(paths, now=1_000_000)

    assert not stale.exists()
    assert recent.exists()
    assert nonempty.exists()
    assert not cleanup_lock.exists()
    assert unknown.exists()
    assert not quarantine_for(stale).exists()
    assert report.categories["stale_locks"].removed_files == 1


def test_cleanup_claims_dead_lock_before_removing_owner(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    quarantine = quarantine_for(lock)
    lock.mkdir()
    write_lock_owner(lock)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    original_unlink = Path.unlink
    owner_locations = []

    def unlink(path, *args, **kwargs):
        if path.parent == quarantine and path.name == "owner.json":
            owner_locations.append((path.parent, lock.exists()))
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)

    report = cleanup.run(paths, now=1_000_000)

    assert owner_locations == [(quarantine, False)]
    assert not lock.exists()
    assert not quarantine.exists()
    assert report.categories["stale_locks"].removed_files == 1


def test_cleanup_restores_claim_when_owner_identity_changes(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    quarantine = quarantine_for(lock)
    lock.mkdir()
    write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    original_rename = Path.rename
    changed = False

    def rename(path, target):
        nonlocal changed
        result = original_rename(path, target)
        if path == lock and Path(target) == quarantine:
            changed = True
            write_lock_owner(quarantine, pid=456)
        return result

    monkeypatch.setattr(Path, "rename", rename)

    report = cleanup.run(paths, now=1_000_000)

    assert changed is True
    assert json.loads((lock / "owner.json").read_text())["pid"] == 456
    assert not quarantine.exists()
    assert report.categories["stale_locks"].removed_files == 0
    assert report.categories["stale_locks"].skipped_files == 1


def test_cleanup_never_restores_a_replaced_quarantine_object(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    quarantine = quarantine_for(lock)
    displaced = paths.hooks_dir / ".displaced-dead-lock"
    lock.mkdir()
    write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    original_rename = Path.rename
    replaced = False

    def rename(path, target):
        nonlocal replaced
        result = original_rename(path, target)
        if path == lock and Path(target) == quarantine:
            replaced = True
            original_rename(quarantine, displaced)
            quarantine.mkdir()
            write_lock_owner(quarantine, pid=456)
        return result

    monkeypatch.setattr(Path, "rename", rename)

    report = cleanup.run(paths, now=1_000_000)

    assert replaced is True
    assert not lock.exists()
    assert json.loads((displaced / "owner.json").read_text())["pid"] == 123
    assert json.loads((quarantine / "owner.json").read_text())["pid"] == 456
    assert report.categories["stale_locks"].removed_files == 0
    assert report.categories["stale_locks"].skipped_files == 1


def test_cleanup_restores_owner_when_entry_appears_after_claim(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    quarantine = quarantine_for(lock)
    lock.mkdir()
    write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    original_unlink = Path.unlink
    injected = False

    def unlink(path, *args, **kwargs):
        nonlocal injected
        if path.name == "owner.json":
            injected = True
            (path.parent / "active-entry").write_text("busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)

    report = cleanup.run(paths, now=1_000_000)

    assert injected is True
    assert (lock / "owner.json").exists()
    assert (lock / "active-entry").read_text() == "busy"
    assert not quarantine.exists()
    assert report.categories["stale_locks"].removed_files == 0
    assert report.categories["stale_locks"].skipped_files == 1


def test_cleanup_does_not_restore_owner_into_replaced_quarantine(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    quarantine = quarantine_for(lock)
    displaced = paths.hooks_dir / ".displaced-ownerless-lock"
    lock.mkdir()
    write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    original_unlink = Path.unlink
    original_lstat = Path.lstat
    original_rename = Path.rename
    owner_removed = False
    replaced = False

    def unlink(path, *args, **kwargs):
        nonlocal owner_removed
        result = original_unlink(path, *args, **kwargs)
        if path.parent == quarantine and path.name == "owner.json":
            owner_removed = True
        return result

    def lstat(path):
        nonlocal replaced
        if path == quarantine and owner_removed and not replaced:
            replaced = True
            original_rename(quarantine, displaced)
            quarantine.mkdir()
            (quarantine / "unrelated").write_text("keep")
        return original_lstat(path)

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(Path, "lstat", lstat)

    report = cleanup.run(paths, now=1_000_000)

    assert replaced is True
    assert not (quarantine / "owner.json").exists()
    assert (quarantine / "unrelated").read_text() == "keep"
    assert not (displaced / "owner.json").exists()
    assert report.categories["stale_locks"].removed_files == 0
    assert report.categories["stale_locks"].skipped_files == 1


def test_existing_lock_quarantine_is_left_untouched(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    quarantine = quarantine_for(lock)
    lock.mkdir()
    write_lock_owner(lock)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    quarantine.mkdir()
    unrelated = quarantine / "unrelated"
    unrelated.write_text("keep")
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )

    report = cleanup.run(paths, now=1_000_000)

    assert (lock / "owner.json").exists()
    assert unrelated.read_text() == "keep"
    assert report.categories["stale_locks"].removed_files == 0
    assert report.categories["stale_locks"].skipped_files == 1


def test_cleanup_keeps_old_known_lock_with_live_owner(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    lock.mkdir()
    write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    checked = []
    monkeypatch.setattr(
        cleanup.os, "kill", lambda pid, signal: checked.append((pid, signal))
    )

    report = cleanup.run(paths, now=1_000_000)

    assert lock.exists()
    assert checked == [(123, 0)]
    assert report.categories["stale_locks"].eligible_files == 0


def test_cleanup_keeps_old_ownerless_known_lock(tmp_path):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    lock.mkdir()
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)

    report = cleanup.run(paths, now=1_000_000)

    assert lock.exists()
    assert report.categories["stale_locks"].eligible_files == 0


def test_cleanup_keeps_old_known_lock_with_malformed_owner(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    lock.mkdir()
    (lock / "owner.json").write_text(
        json.dumps({"pid": "123", "created_ts": 1_000_000})
    )
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: pytest.fail("malformed owner PID must not be checked"),
    )

    report = cleanup.run(paths, now=1_000_000)

    assert lock.exists()
    assert report.categories["stale_locks"].eligible_files == 0


@pytest.mark.parametrize("pid_check_error", [PermissionError, OSError])
def test_cleanup_conservatively_keeps_lock_when_pid_status_is_not_provably_dead(
    tmp_path, monkeypatch, pid_check_error
):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    lock.mkdir()
    write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(pid_check_error()),
    )

    report = cleanup.run(paths, now=1_000_000)

    assert lock.exists()
    assert report.categories["stale_locks"].eligible_files == 0


def test_cleanup_keeps_lock_with_recent_owner_record(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    lock.mkdir()
    write_lock_owner(lock, created_ts=1_000_000 - cleanup.TEMP_AGE_SECONDS + 1)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os,
        "kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )

    report = cleanup.run(paths, now=1_000_000)

    assert lock.exists()
    assert report.categories["stale_locks"].eligible_files == 0


def test_lock_owner_record_is_rechecked_before_deletion(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    lock.mkdir()
    owner = write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    checks = 0

    def pid_is_dead(_pid, _signal):
        nonlocal checks
        checks += 1
        if checks == 1:
            owner.write_text(
                json.dumps(
                    {
                        "pid": 456,
                        "created_ts": 1_000_000 - cleanup.TEMP_AGE_SECONDS - 1,
                    }
                )
            )
        raise ProcessLookupError

    monkeypatch.setattr(cleanup.os, "kill", pid_is_dead)

    report = cleanup.run(paths, now=1_000_000)

    assert lock.exists()
    assert json.loads(owner.read_text())["pid"] == 456
    assert report.categories["stale_locks"].removed_files == 0


def test_lock_directory_identity_is_rechecked_before_deletion(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    lock = paths.hooks_dir / ".jarvis_line.lock.d"
    displaced = paths.hooks_dir / ".displaced-lock"
    lock.mkdir()
    write_lock_owner(lock, pid=123)
    age(lock, cleanup.TEMP_AGE_SECONDS + 1)
    swapped = False

    def swap_lock_then_report_dead(_pid, _signal):
        nonlocal swapped
        if not swapped:
            swapped = True
            lock.rename(displaced)
            lock.mkdir()
            write_lock_owner(lock, pid=456)
            age(lock, cleanup.TEMP_AGE_SECONDS + 1)
        raise ProcessLookupError

    monkeypatch.setattr(cleanup.os, "kill", swap_lock_then_report_dead)

    report = cleanup.run(paths, now=1_000_000)

    assert swapped is True
    assert displaced.exists()
    assert json.loads((lock / "owner.json").read_text())["pid"] == 456
    assert report.categories["stale_locks"].removed_files == 0


def test_cleanup_keeps_allowlisted_symlinks_and_nested_candidates(tmp_path):
    paths = paths_for(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    temp_link = paths.hooks_dir / ".jarvis_line_config.json.link.tmp"
    temp_link.symlink_to(outside)
    lock_link = paths.hooks_dir / ".jarvis_line.lock.d"
    lock_link.symlink_to(tmp_path, target_is_directory=True)
    nested_audio_dir = paths.generated_audio_dir / "nested"
    nested_audio_dir.mkdir()
    nested_audio = nested_audio_dir / "kokoro_old.wav"
    nested_audio.write_bytes(b"audio")
    age(nested_audio, 86_400)
    nested_hooks_dir = paths.hooks_dir / "nested"
    nested_hooks_dir.mkdir()
    nested_temp = nested_hooks_dir / ".jarvis_line_config.json.old.tmp"
    nested_temp.write_bytes(b"temp")
    age(nested_temp, 86_400)

    cleanup.run(paths, now=1_000_000)

    assert outside.read_bytes() == b"private"
    assert temp_link.is_symlink()
    assert lock_link.is_symlink()
    assert nested_audio.exists()
    assert nested_temp.exists()


def test_unlink_error_is_redacted_and_does_not_stop_other_deletions(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    failed = paths.generated_audio_dir / "kokoro_fail.wav"
    removed = paths.generated_audio_dir / "kokoro_remove.wav"
    for path in (failed, removed):
        path.write_bytes(b"audio")
        age(path, 601)
    original_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == failed:
            raise OSError(f"private failure at {tmp_path}")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)

    report = cleanup.run(paths, now=1_000_000)

    assert failed.exists()
    assert not removed.exists()
    assert report.error_count == 1
    assert report.errors == [{"category": "generated_audio", "name": failed.name}]
    assert str(tmp_path) not in str(report.to_dict())


def test_error_details_are_bounded_but_error_count_is_complete(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    for index in range(cleanup.MAX_ERROR_DETAILS + 2):
        path = paths.generated_audio_dir / f"kokoro_{index}.wav"
        path.write_bytes(b"audio")
        age(path, 601)

    def fail_unlink(path, *args, **kwargs):
        raise OSError(f"private failure at {path}")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    report = cleanup.run(paths, now=1_000_000)

    assert report.error_count == cleanup.MAX_ERROR_DETAILS + 2
    assert len(report.errors) == cleanup.MAX_ERROR_DETAILS
    assert all(set(error) == {"category", "name"} for error in report.errors)
    assert str(tmp_path) not in str(report.to_dict())


def test_hooks_root_scan_failure_is_recorded_for_every_owned_category(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    original_scandir = cleanup.os.scandir

    def scandir(path):
        if Path(path) == paths.hooks_dir:
            raise PermissionError(f"private failure at {path}")
        return original_scandir(path)

    monkeypatch.setattr(cleanup.os, "scandir", scandir)

    report = cleanup.run(paths, now=1_000_000)

    assert report.error_count == 3
    assert report.categories["generated_audio"].error_count == 0
    assert report.categories["rotated_logs"].error_count == 1
    assert report.categories["runtime_temp"].error_count == 1
    assert report.categories["stale_locks"].error_count == 1
    assert report.errors == [
        {"category": "rotated_logs", "name": "hooks"},
        {"category": "runtime_temp", "name": "hooks"},
        {"category": "stale_locks", "name": "hooks"},
    ]
    assert str(tmp_path) not in str(report.to_dict())


def test_identity_is_rechecked_immediately_before_unlink(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    candidate = paths.generated_audio_dir / "kokoro_swap.wav"
    candidate.write_bytes(b"original")
    age(candidate, 601)
    original_lstat = Path.lstat
    swapped = False

    def lstat(path):
        nonlocal swapped
        if path == candidate and not swapped:
            swapped = True
            path.unlink()
            path.write_bytes(b"replacement")
            age(path, 601)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat)

    report = cleanup.run(paths, now=1_000_000)

    assert candidate.read_bytes() == b"replacement"
    assert report.removed_files == 0
    assert report.skipped_files == 1


def test_cleanup_report_to_dict_has_stable_totals_and_categories(tmp_path):
    paths = paths_for(tmp_path)

    report = cleanup.inspect(paths, now=1_000_000).to_dict()

    assert list(report) == [
        "mode",
        "eligible_files",
        "eligible_bytes",
        "removed_files",
        "removed_bytes",
        "skipped_files",
        "error_count",
        "errors",
        "already_running",
        "last_success_at",
        "categories",
    ]
    assert report["mode"] == "status"
    assert report["last_success_at"] is None
    assert list(report["categories"]) == [
        "generated_audio",
        "rotated_logs",
        "runtime_temp",
        "stale_locks",
    ]


def test_inspect_reads_last_success_without_updating_maintenance_state(tmp_path):
    paths = paths_for(tmp_path)
    paths.state_path.write_text(
        json.dumps({"last_attempt_ts": 123, "last_success_ts": 99})
    )
    original = paths.state_path.read_bytes()

    report = cleanup.inspect(paths, now=1_000_000)

    assert report.mode == "status"
    assert report.last_success_at == 99
    assert paths.state_path.read_bytes() == original


def test_manual_run_records_success_without_advancing_schedule(tmp_path):
    paths = paths_for(tmp_path)
    paths.state_path.write_text(
        json.dumps({"last_attempt_ts": 123, "last_success_ts": 99})
    )

    report = cleanup.run(paths, now=200_000)

    assert report.mode == "run"
    assert report.last_success_at == 200_000
    assert json.loads(paths.state_path.read_text()) == {
        "last_attempt_ts": 123,
        "last_success_ts": 200_000,
    }


def test_cleanup_paths_default_uses_only_known_storage_locations(monkeypatch, tmp_path):
    monkeypatch.setattr(cleanup.Path, "home", classmethod(lambda _cls: tmp_path))

    paths = cleanup.CleanupPaths.default()

    hooks = tmp_path / ".codex" / "hooks"
    assert paths == cleanup.CleanupPaths(
        hooks_dir=hooks,
        generated_audio_dir=tmp_path / ".jarvis-line" / "tts" / "generated",
        state_path=hooks / ".jarvis_line_cleanup_state.json",
        lock_dir=hooks / ".jarvis_line_cleanup.lock.d",
        watcher_log=hooks / "jarvis_line_watcher.log",
        worker_log=hooks / "jarvis_line_audio_worker.log",
    )


def test_run_if_due_respects_enabled_interval_and_records_success(tmp_path):
    paths = paths_for(tmp_path)
    audio = paths.generated_audio_dir / "kokoro_old.wav"
    audio.write_bytes(b"x")
    age(audio, cleanup.AUTO_AUDIO_AGE_SECONDS + 1, now=200_000)

    first = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 24},
        paths,
        now=200_000,
    )
    second = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 24},
        paths,
        now=200_100,
    )

    assert first is not None and first.removed_files == 1
    assert second is None
    assert json.loads(paths.state_path.read_text()) == {
        "last_attempt_ts": 200_000,
        "last_success_ts": 200_000,
    }


def test_run_if_due_disabled_does_not_create_state_or_lock(tmp_path):
    paths = paths_for(tmp_path)

    report = cleanup.run_if_due(
        {"cleanup_enabled": False, "cleanup_interval_hours": 24},
        paths,
        now=200_000,
    )

    assert report is None
    assert not paths.state_path.exists()
    assert not paths.lock_dir.exists()


def test_run_if_due_supports_weekly_interval(tmp_path):
    paths = paths_for(tmp_path)
    paths.state_path.write_text(
        json.dumps({"last_attempt_ts": 200_000, "last_success_ts": 100_000})
    )

    before_due = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 168},
        paths,
        now=200_000 + (168 * 60 * 60) - 1,
    )
    when_due = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 168},
        paths,
        now=200_000 + (168 * 60 * 60),
    )

    assert before_due is None
    assert when_due is not None


@pytest.mark.parametrize("invalid_interval", [None, 0, 12, 169, "168"])
def test_run_if_due_invalid_interval_falls_back_to_daily(tmp_path, invalid_interval):
    paths = paths_for(tmp_path)
    paths.state_path.write_text(
        json.dumps({"last_attempt_ts": 200_000, "last_success_ts": 100_000})
    )

    report = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": invalid_interval},
        paths,
        now=200_000 + (13 * 60 * 60),
    )

    assert report is None


def test_run_if_due_partial_error_advances_attempt_but_not_success(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    paths.state_path.write_text(
        json.dumps({"last_attempt_ts": 1, "last_success_ts": 123})
    )
    audio = paths.generated_audio_dir / "kokoro_old.wav"
    audio.write_bytes(b"x")
    age(audio, cleanup.AUTO_AUDIO_AGE_SECONDS + 1, now=200_000)
    real_unlink = Path.unlink

    def fail_audio_unlink(path, *args, **kwargs):
        if path == audio:
            raise PermissionError("denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_audio_unlink)

    report = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 24},
        paths,
        now=200_000,
    )

    assert report is not None and report.error_count == 1
    assert json.loads(paths.state_path.read_text()) == {
        "last_attempt_ts": 200_000,
        "last_success_ts": 123,
    }


def test_run_returns_already_running_without_waiting(tmp_path):
    paths = paths_for(tmp_path)
    paths.lock_dir.mkdir()
    write_lock_owner(paths.lock_dir, pid=os.getpid(), created_ts=200_000)

    report = cleanup.run(paths, now=200_001)

    assert report.already_running is True
    assert report.removed_files == 0
    assert paths.lock_dir.exists()


def test_run_treats_permission_error_checking_owner_as_alive(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    paths.lock_dir.mkdir()
    write_lock_owner(paths.lock_dir, pid=123, created_ts=100_000)
    age(paths.lock_dir, cleanup.TEMP_AGE_SECONDS + 1, now=200_000)

    def deny_signal(_pid, _signal):
        raise PermissionError

    monkeypatch.setattr(cleanup.os, "kill", deny_signal)

    report = cleanup.run(paths, now=200_000)

    assert report.already_running is True
    assert paths.lock_dir.exists()


def test_run_recovers_old_cleanup_lock_with_dead_owner(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    paths.lock_dir.mkdir()
    write_lock_owner(paths.lock_dir, pid=123, created_ts=100_000)
    age(paths.lock_dir, cleanup.TEMP_AGE_SECONDS + 1, now=200_000)

    def dead_owner(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(cleanup.os, "kill", dead_owner)

    report = cleanup.run(paths, now=200_000)

    assert report.already_running is False
    assert not paths.lock_dir.exists()


def test_run_recovers_old_cleanup_lock_without_valid_owner(tmp_path):
    paths = paths_for(tmp_path)
    paths.lock_dir.mkdir()
    (paths.lock_dir / "owner.json").write_text("not-json")
    age(paths.lock_dir, cleanup.TEMP_AGE_SECONDS + 1, now=200_000)

    report = cleanup.run(paths, now=200_000)

    assert report.already_running is False
    assert not paths.lock_dir.exists()


def test_run_keeps_recent_cleanup_lock_without_valid_owner(tmp_path):
    paths = paths_for(tmp_path)
    paths.lock_dir.mkdir()
    age(paths.lock_dir, cleanup.TEMP_AGE_SECONDS - 1, now=200_000)

    report = cleanup.run(paths, now=200_000)

    assert report.already_running is True
    assert paths.lock_dir.exists()


def test_run_does_not_release_replacement_cleanup_lock(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    displaced = paths.hooks_dir / ".displaced-cleanup-lock"
    real_execute = cleanup._execute

    def replace_lock(*args, **kwargs):
        paths.lock_dir.rename(displaced)
        paths.lock_dir.mkdir()
        write_lock_owner(paths.lock_dir, pid=987, created_ts=200_000)
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(cleanup, "_execute", replace_lock)

    report = cleanup.run(paths, now=200_000)

    assert report.already_running is False
    assert paths.lock_dir.exists()
    assert json.loads((paths.lock_dir / "owner.json").read_text())["pid"] == 987


def test_run_if_due_rechecks_state_after_acquiring_lock(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    paths.state_path.write_text(
        json.dumps({"last_attempt_ts": 1, "last_success_ts": 1})
    )
    audio = paths.generated_audio_dir / "kokoro_old.wav"
    audio.write_bytes(b"x")
    age(audio, cleanup.AUTO_AUDIO_AGE_SECONDS + 1, now=200_000)
    real_mkdir = Path.mkdir
    state_advanced = False

    def advance_state_before_lock(path, *args, **kwargs):
        nonlocal state_advanced
        if path == paths.lock_dir and not state_advanced:
            state_advanced = True
            paths.state_path.write_text(
                json.dumps({"last_attempt_ts": 200_000, "last_success_ts": 123})
            )
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", advance_state_before_lock)

    report = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 24},
        paths,
        now=200_001,
    )

    assert report is None
    assert audio.exists()
    assert json.loads(paths.state_path.read_text()) == {
        "last_attempt_ts": 200_000,
        "last_success_ts": 123,
    }
    assert not paths.lock_dir.exists()


def test_run_if_due_replaces_bounded_state_atomically(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    paths.state_path.write_text(
        json.dumps(
            {
                "last_attempt_ts": "invalid",
                "last_success_ts": None,
                "unexpected": "discard me",
            }
        )
    )
    real_replace = cleanup.os.replace
    replacements = []

    def record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(cleanup.os, "replace", record_replace)

    report = cleanup.run_if_due(
        {"cleanup_enabled": True, "cleanup_interval_hours": 24},
        paths,
        now=200_000.9,
    )

    assert report is not None and report.error_count == 0
    assert json.loads(paths.state_path.read_text()) == {
        "last_attempt_ts": 200_000,
        "last_success_ts": 200_000,
    }
    state_replacements = [item for item in replacements if item[1] == paths.state_path]
    assert len(state_replacements) == 2
    for temporary, destination in state_replacements:
        assert destination == paths.state_path
        assert temporary.name.startswith(".jarvis_line_cleanup_state.json.")
        assert temporary.name.endswith(".tmp")


@pytest.mark.parametrize("unexpected_kind", ["symlink", "file"])
def test_unknown_failed_owner_quarantine_does_not_block_immediate_retry(
    tmp_path, monkeypatch, unexpected_kind
):
    paths = paths_for(tmp_path)
    owner_path = paths.lock_dir / cleanup.LOCK_OWNER_NAME
    quarantine = quarantine_for(paths.lock_dir)
    external = tmp_path / "external-owner-target"
    external.write_bytes(b"private")
    real_open = cleanup.os.open
    injected = False

    def inject_owner(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal injected
        if Path(path) == owner_path and flags & os.O_CREAT and not injected:
            injected = True
            if unexpected_kind == "symlink":
                owner_path.symlink_to(external)
            else:
                owner_path.write_bytes(b"unexpected")
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(cleanup.os, "open", inject_owner)

    first = cleanup.run(paths, now=200_000)
    real_execute = cleanup._execute
    acquired_owners = []

    def record_fresh_active_lock(*args, **kwargs):
        candidate = cleanup._cleanup_lock_candidate(paths.lock_dir)
        acquired_owners.append(
            None if candidate is None else cleanup._read_lock_owner(candidate)
        )
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(cleanup, "_execute", record_fresh_active_lock)
    second = cleanup.run(paths, now=200_001)

    assert injected is True
    assert first.error_count == 1
    assert second.error_count == 0
    assert second.already_running is False
    assert len(acquired_owners) == 1
    assert acquired_owners[0] is not None
    assert acquired_owners[0].pid == os.getpid()
    assert acquired_owners[0].created_ts == 200_001
    assert external.read_bytes() == b"private"
    assert not paths.lock_dir.exists()
    assert quarantine.is_dir()
    quarantined_owner = quarantine / cleanup.LOCK_OWNER_NAME
    if unexpected_kind == "symlink":
        assert quarantined_owner.is_symlink()
    else:
        assert quarantined_owner.read_bytes() == b"unexpected"
    assert list(paths.hooks_dir.glob(f"{paths.lock_dir.name}*")) == [quarantine]


def test_quarantine_cleanup_failure_does_not_block_active_lock(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    quarantine = quarantine_for(paths.lock_dir)
    quarantine.mkdir()
    real_rmdir = Path.rmdir

    def fail_quarantine_rmdir(path, *args, **kwargs):
        if path == quarantine:
            raise PermissionError("injected quarantine cleanup failure")
        return real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "rmdir", fail_quarantine_rmdir)

    report = cleanup.run(paths, now=200_000)

    assert report.error_count == 0
    assert report.already_running is False
    assert quarantine.is_dir()
    assert not paths.lock_dir.exists()
    assert list(paths.hooks_dir.glob(f"{paths.lock_dir.name}*")) == [quarantine]


def test_failed_acquisition_with_occupied_quarantine_preserves_replacement_lock(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    quarantine = quarantine_for(paths.lock_dir)
    quarantine.mkdir()
    unknown = quarantine / "unknown"
    unknown.write_bytes(b"preserve exactly")
    real_read_owner = cleanup._read_lock_owner
    replaced = False

    def replace_before_failed_readback(candidate):
        nonlocal replaced
        if candidate.path == paths.lock_dir and not replaced:
            replaced = True
            (paths.lock_dir / cleanup.LOCK_OWNER_NAME).unlink()
            paths.lock_dir.rmdir()
            paths.lock_dir.mkdir()
            write_lock_owner(paths.lock_dir, pid=987, created_ts=200_000)
            return None
        return real_read_owner(candidate)

    monkeypatch.setattr(cleanup, "_read_lock_owner", replace_before_failed_readback)

    report = cleanup.run(paths, now=200_000)

    assert report.error_count == 1
    assert replaced is True
    assert unknown.read_bytes() == b"preserve exactly"
    assert json.loads((paths.lock_dir / "owner.json").read_text()) == {
        "pid": 987,
        "created_ts": 200_000,
    }
    assert set(paths.hooks_dir.glob(f"{paths.lock_dir.name}*")) == {
        paths.lock_dir,
        quarantine,
    }


@pytest.mark.parametrize("failure_mode", ["empty", "partial", "readback"])
def test_failed_owner_initialization_frees_lock_for_immediate_retry(
    tmp_path, monkeypatch, failure_mode
):
    paths = paths_for(tmp_path)
    real_write = cleanup.os.write
    real_read_owner = cleanup._read_lock_owner
    write_calls = 0

    def fail_owner_write(descriptor, payload):
        nonlocal write_calls
        write_calls += 1
        if failure_mode == "empty":
            raise OSError("injected empty owner write")
        if failure_mode == "partial":
            if write_calls == 1:
                return real_write(descriptor, payload[:1])
            raise OSError("injected partial owner write")
        return real_write(descriptor, payload)

    def fail_owner_readback(candidate):
        if candidate.path == paths.lock_dir:
            return None
        return real_read_owner(candidate)

    if failure_mode in {"empty", "partial"}:
        monkeypatch.setattr(cleanup.os, "write", fail_owner_write)
    else:
        monkeypatch.setattr(cleanup, "_read_lock_owner", fail_owner_readback)

    first = cleanup.run(paths, now=200_000)

    monkeypatch.setattr(cleanup.os, "write", real_write)
    monkeypatch.setattr(cleanup, "_read_lock_owner", real_read_owner)
    second = cleanup.run(paths, now=200_001)

    assert first.error_count == 1
    assert second.error_count == 0
    assert second.already_running is False
    assert not paths.lock_dir.exists()
    assert not quarantine_for(paths.lock_dir).exists()
    assert list(paths.hooks_dir.glob(f"{paths.lock_dir.name}*")) == []


def test_failed_owner_initialization_never_removes_replacement_lock(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)
    displaced = paths.hooks_dir / ".injected-displaced-lock"
    quarantine = quarantine_for(paths.lock_dir)
    real_read_owner = cleanup._read_lock_owner
    real_rename = cleanup.os.rename
    replaced = False

    def fail_owner_readback(candidate):
        if candidate.path == paths.lock_dir:
            return None
        return real_read_owner(candidate)

    def replace_before_claim(source, destination):
        nonlocal replaced
        if Path(source) == paths.lock_dir and Path(destination) == quarantine:
            replaced = True
            real_rename(paths.lock_dir, displaced)
            paths.lock_dir.mkdir()
            write_lock_owner(paths.lock_dir, pid=987, created_ts=200_000)
        return real_rename(source, destination)

    monkeypatch.setattr(cleanup, "_read_lock_owner", fail_owner_readback)
    monkeypatch.setattr(cleanup.os, "rename", replace_before_claim)

    report = cleanup.run(paths, now=200_000)

    assert report.error_count == 1
    assert replaced is True
    assert paths.lock_dir.is_dir()
    assert json.loads((paths.lock_dir / "owner.json").read_text())["pid"] == 987
    assert displaced.is_dir()
    assert not quarantine.exists()


def test_owner_is_created_exclusively_private_and_fsynced(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    owner_path = paths.lock_dir / cleanup.LOCK_OWNER_NAME
    real_open = cleanup.os.open
    real_close = cleanup.os.close
    real_fsync = cleanup.os.fsync
    owner_open = []
    owner_fsyncs = []
    owner_descriptor = -1

    def record_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal owner_descriptor
        if dir_fd is None:
            descriptor = real_open(path, flags, mode)
        else:
            descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path) == owner_path and flags & os.O_CREAT:
            owner_descriptor = descriptor
            owner_open.append((flags, mode))
        return descriptor

    def record_fsync(descriptor):
        if descriptor == owner_descriptor:
            owner_fsyncs.append(descriptor)
        return real_fsync(descriptor)

    def record_close(descriptor):
        nonlocal owner_descriptor
        if descriptor == owner_descriptor:
            owner_descriptor = -1
        return real_close(descriptor)

    monkeypatch.setattr(cleanup.os, "open", record_open)
    monkeypatch.setattr(cleanup.os, "close", record_close)
    monkeypatch.setattr(cleanup.os, "fsync", record_fsync)

    report = cleanup.run(paths, now=200_000)

    assert report.error_count == 0
    assert len(owner_open) == 1
    flags, mode = owner_open[0]
    assert flags & os.O_WRONLY
    assert flags & os.O_CREAT
    assert flags & os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        assert flags & os.O_NOFOLLOW
    assert mode == 0o600
    assert len(owner_fsyncs) == 1


def test_write_state_is_durable_before_and_after_replace(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    events = []
    real_named_temporary_file = cleanup.tempfile.NamedTemporaryFile
    real_replace = cleanup.os.replace

    class RecordingTemporaryFile:
        def __init__(self, *args, **kwargs):
            self._temporary = real_named_temporary_file(*args, **kwargs)

        @property
        def name(self):
            return self._temporary.name

        def __enter__(self):
            self._temporary.__enter__()
            return self

        def __exit__(self, *args):
            return self._temporary.__exit__(*args)

        def write(self, payload):
            events.append("write")
            return self._temporary.write(payload)

        def flush(self):
            events.append("flush")
            return self._temporary.flush()

        def fileno(self):
            return self._temporary.fileno()

    def record_fsync(_descriptor):
        events.append("file_fsync")

    def record_replace(source, destination):
        events.append("replace")
        return real_replace(source, destination)

    def record_parent_fsync(parent):
        assert parent == paths.state_path.parent
        events.append("parent_fsync")

    monkeypatch.setattr(
        cleanup.tempfile, "NamedTemporaryFile", RecordingTemporaryFile
    )
    monkeypatch.setattr(cleanup.os, "fsync", record_fsync)
    monkeypatch.setattr(cleanup.os, "replace", record_replace)
    monkeypatch.setattr(
        cleanup, "_fsync_parent_directory", record_parent_fsync, raising=False
    )

    cleanup._write_state(
        paths.state_path,
        {"last_attempt_ts": 100, "last_success_ts": 99},
    )

    assert events == ["write", "flush", "file_fsync", "replace", "parent_fsync"]


def test_write_state_cleans_temporary_file_when_fsync_fails(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    paths.state_path.write_text('{"last_attempt_ts":1,"last_success_ts":1}\n')
    original = paths.state_path.read_bytes()

    def fail_fsync(_descriptor):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(cleanup.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="injected fsync failure"):
        cleanup._write_state(
            paths.state_path,
            {"last_attempt_ts": 100, "last_success_ts": 99},
        )

    assert paths.state_path.read_bytes() == original
    assert list(paths.hooks_dir.glob(".jarvis_line_cleanup_state.json.*.tmp")) == []


def test_parent_directory_fsync_uses_safe_directory_flags(tmp_path, monkeypatch):
    paths = paths_for(tmp_path)
    real_open = cleanup.os.open
    opened = []
    fsynced = []

    def record_open(path, flags, mode=0o777, *, dir_fd=None):
        opened.append((Path(path), flags))
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def record_fsync(descriptor):
        fsynced.append(descriptor)

    monkeypatch.setattr(cleanup.os, "open", record_open)
    monkeypatch.setattr(cleanup.os, "fsync", record_fsync)

    cleanup._fsync_parent_directory(paths.hooks_dir)

    assert len(opened) == 1
    opened_path, flags = opened[0]
    assert opened_path == paths.hooks_dir
    if hasattr(os, "O_DIRECTORY"):
        assert flags & os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        assert flags & os.O_NOFOLLOW
    assert len(fsynced) == (0 if os.name == "nt" else 1)


def test_parent_directory_fsync_tolerates_unsupported_platform_error(
    tmp_path, monkeypatch
):
    paths = paths_for(tmp_path)

    def unsupported_open(_path, _flags):
        raise OSError(cleanup.errno.EINVAL, "directory fsync unsupported")

    monkeypatch.setattr(cleanup.os, "open", unsupported_open)

    cleanup._fsync_parent_directory(paths.hooks_dir)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific lock regression")
def test_cleanup_lock_can_be_acquired_on_windows(tmp_path):
    paths = paths_for(tmp_path)

    acquired = cleanup._acquire_cleanup_lock(paths, now=200_000)

    assert acquired is not None
    cleanup._release_cleanup_lock(acquired)
    assert not paths.lock_dir.exists()
