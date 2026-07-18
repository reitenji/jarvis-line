import json
import os
from pathlib import Path

import pytest

from jarvis_line import cleanup


def paths_for(root: Path) -> cleanup.CleanupPaths:
    hooks = root / "hooks"
    generated = root / "jarvis" / "tts" / "generated"
    hooks.mkdir(parents=True)
    generated.mkdir(parents=True)
    return cleanup.CleanupPaths(
        hooks_dir=hooks,
        generated_audio_dir=generated,
        state_path=hooks / ".jarvis_line_cleanup_state.json",
        lock_dir=hooks / ".jarvis_line_cleanup.lock.d",
        watcher_log=hooks / "jarvis_line_watcher.log",
        worker_log=hooks / "jarvis_line_audio_worker.log",
    )


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


def test_run_removes_only_exact_old_diagnostics_and_atomic_temp_allowlists(tmp_path):
    paths = paths_for(tmp_path)
    rotated = paths.watcher_log.with_suffix(".log.1")
    temporary = paths.hooks_dir / ".jarvis_line_audio_queue.json.1.2.tmp"
    current_log = paths.watcher_log
    current_queue = paths.hooks_dir / "jarvis_line_audio_queue.json"
    current_state = paths.state_path
    unexpected_temp = paths.hooks_dir / "tmp123"
    near_match_log = paths.hooks_dir / "jarvis_line_watcher.log.2"
    near_match_temp = paths.hooks_dir / ".unknown.json.1.2.tmp"
    for path in (
        rotated,
        temporary,
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
    assert current_log.exists()
    assert current_queue.exists()
    assert current_state.exists()
    assert unexpected_temp.exists()
    assert near_match_log.exists()
    assert near_match_temp.exists()
    assert report.removed_files == 2
    assert report.categories["rotated_logs"].removed_files == 1
    assert report.categories["runtime_temp"].removed_files == 1


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
    assert cleanup_lock.exists()
    assert unknown.exists()
    assert report.categories["stale_locks"].removed_files == 1


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
        "eligible_files",
        "eligible_bytes",
        "removed_files",
        "removed_bytes",
        "skipped_files",
        "error_count",
        "errors",
        "categories",
    ]
    assert list(report["categories"]) == [
        "generated_audio",
        "rotated_logs",
        "runtime_temp",
        "stale_locks",
    ]


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
