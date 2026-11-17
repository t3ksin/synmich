"""Folder export resumes across new runs and changing selections (#20)."""

from unittest.mock import MagicMock

import pytest

from synmich.core.backup import run_backup
from synmich.core.migrator import MigrationControl, MigrationStats, UserSession


@pytest.fixture
def session():
    syno = MagicMock()
    syno.base_url = "http://nas:5000"
    syno.list_albums.return_value = [{"id": 9, "name": "Christmas", "owner_user_id": 1}]
    syno.list_items.return_value = [
        {"id": i, "filename": f"image{i}.jpg", "owner_user_id": 1, "filesize": 4} for i in (1, 2)
    ]

    def download(item, folder):
        path = folder / f"{item['id']}_{item['filename']}"
        path.write_bytes(b"jpeg")
        return path

    syno.download.side_effect = download
    return UserSession("son", syno, None, 1, "")


def backup(session, dest, **kwargs):
    stats = MigrationStats()
    control = kwargs.pop("control", MigrationControl())
    run_backup(
        [session], set(), True, kwargs.pop("owner_only", False), dest, stats, control, **kwargs
    )
    return stats


def test_stop_and_restart_skips_completed_files_after_setting_change(session, tmp_path):
    control = MigrationControl()
    original = session.syno.download.side_effect

    def download(item, folder):
        path = original(item, folder)
        control.stop()
        return path

    session.syno.download.side_effect = download
    first = backup(session, tmp_path, control=control)
    assert first.current_step == "stopped"
    assert first.uploaded == 1
    saved = tmp_path / "son/Christmas/1_image1.jpg"
    mtime = saved.stat().st_mtime_ns

    session.syno.download.side_effect = original
    second = backup(session, tmp_path, owner_only=True)
    assert (second.uploaded, second.skipped, second.failed) == (1, 1, 0)
    assert saved.stat().st_mtime_ns == mtime
    assert session.syno.download.call_count == 2


@pytest.mark.parametrize("damage", ["delete", "truncate", "modify"])
def test_resume_repairs_only_missing_or_changed_files(session, tmp_path, damage):
    backup(session, tmp_path)
    saved = tmp_path / "son/Christmas/1_image1.jpg"
    if damage == "delete":
        saved.unlink()
    else:
        saved.write_bytes(b"x" if damage == "truncate" else b"oops")
    stats = backup(session, tmp_path)
    assert (stats.uploaded, stats.skipped, stats.failed) == (1, 1, 0)
    assert saved.read_bytes() == b"jpeg"


def test_timeline_and_new_destination_have_separate_completion_records(session, tmp_path):
    first = backup(session, tmp_path, include_timeline=True)
    assert first.uploaded == 4
    second = backup(session, tmp_path, include_timeline=True)
    assert (second.uploaded, second.skipped) == (0, 4)
    assert backup(session, tmp_path / "other").uploaded == 2


def test_failed_stream_does_not_publish_partial_or_complete_item(session, tmp_path):
    original = session.syno.download.side_effect

    def interrupted(item, folder):
        original(item, folder)
        raise ConnectionError("stream interrupted")

    session.syno.download.side_effect = interrupted
    assert backup(session, tmp_path).failed == 2
    assert not list(tmp_path.rglob("*.jpg"))
    session.syno.download.side_effect = original
    assert backup(session, tmp_path).uploaded == 2


def test_partial_live_photo_retries_both_components(session, tmp_path):
    session.syno.list_items.return_value = [
        {"id": 1, "filename": "live.HEIC", "type": "live", "owner_user_id": 1}
    ]

    def live(item, folder):
        still, motion = folder / "1_live.HEIC", folder / "1_live.MOV"
        still.write_bytes(b"still")
        motion.write_bytes(b"motion")
        return still, motion

    session.syno.download_live_photo.side_effect = lambda it, folder: (live(it, folder)[0], None)
    assert backup(session, tmp_path).failed == 1
    assert not list(tmp_path.rglob("*.HEIC"))
    session.syno.download_live_photo.side_effect = live
    assert backup(session, tmp_path).uploaded == 1
    assert backup(session, tmp_path).skipped == 1
    (tmp_path / "son/Christmas/1_live.MOV").unlink()
    assert backup(session, tmp_path).uploaded == 1


def test_foreign_contributors_without_login_keep_distinct_files(session, tmp_path):
    # Three libraries can contain the same numeric ID and original filename.
    session.syno.list_items.return_value = [
        {"id": 1, "filename": "same.jpg", "owner_user_id": owner} for owner in (1, 2, 3)
    ]

    def download(item, folder):
        path = folder / "1_same.jpg"
        path.write_bytes(str(item["owner_user_id"]).encode())
        return path

    session.syno.download.side_effect = download
    assert backup(session, tmp_path, owner_only=True).uploaded == 1
    stats = backup(session, tmp_path)
    assert (stats.uploaded, stats.skipped) == (2, 1)
    assert sorted(p.read_bytes() for p in tmp_path.rglob("*.jpg")) == [b"1", b"2", b"3"]


def test_unrecorded_files_are_not_assumed_correct(session, tmp_path):
    folder = tmp_path / "son/Christmas"
    folder.mkdir(parents=True)
    (folder / "1_image1.jpg").write_bytes(b"oops")
    assert backup(session, tmp_path).uploaded == 2
    assert (folder / "1_image1.jpg").read_bytes() == b"jpeg"


def test_source_changes_invalidate_completion(session, tmp_path):
    backup(session, tmp_path)
    session.syno.list_items.return_value[0]["indexed_time"] = 12345
    assert backup(session, tmp_path).uploaded == 1
    session.syno.base_url = "http://another-nas"
    assert backup(session, tmp_path).uploaded == 2


def test_short_response_is_not_checkpointed(session, tmp_path):
    session.syno.list_items.return_value[0]["filesize"] = 100
    stats = backup(session, tmp_path)
    assert (stats.uploaded, stats.failed) == (1, 1)
    assert not (tmp_path / "son/Christmas/1_image1.jpg").exists()
