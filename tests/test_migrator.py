"""Migrator helpers: device_asset_id, album keys, download-fail stats."""

from pathlib import Path
from unittest.mock import MagicMock

from synmich.core.checkpoint import Checkpoint
from synmich.core.migrator import (
    Migrator,
    MigrationControl,
    MigrationStats,
    UserSession,
    album_key,
    device_asset_id,
)


def test_device_asset_id_is_stable_and_unique_per_syno_item():
    a = device_asset_id("cyrille", "435425")
    b = device_asset_id("cyrille", "435426")
    assert a == "cyrille_synoid435425"
    assert a != b
    # Same filename+size would previously collide; ids must not.
    assert "watch.jpg" not in a


def test_album_key_shared_uses_passphrase():
    album = {"id": 1, "name": "Trip", "passphrase": "abc"}
    assert album_key("alice", album) == "abc"


def test_album_key_personal_includes_owner():
    album = {"id": 5, "name": "Private"}
    assert album_key("alice", album) == "local-alice-5"
    assert album_key("bob", album) == "local-bob-5"


def _migrator(tmp_path: Path, syno) -> Migrator:
    cp = Checkpoint(path=tmp_path / "cp.json")
    session = UserSession(
        name="cyrille",
        syno=syno,
        immich=MagicMock(),
        syno_user_id=1,
        immich_user_id="immich-1",
    )
    return Migrator(
        config={"migration": {}, "execution": {"mode": "sequential"}},
        sessions=[session],
        checkpoint=cp,
        stats=MigrationStats(),
        control=MigrationControl(),
    )


def test_download_failure_increments_failed_and_logs(tmp_path):
    syno = MagicMock()
    syno.download.return_value = None
    mig = _migrator(tmp_path, syno)
    uploader = mig.sessions[0]
    item = {"id": 42, "filename": "watch.jpg", "type": "photo"}

    asset_id, name = mig._process_one_asset(item, tmp_path, uploader)

    assert asset_id is None
    assert name == "cyrille"
    assert mig.stats.failed == 1
    assert mig.checkpoint.data["failed_items"]["cyrille"]["42"] == "download_failed"
    assert any("download failed" in m for m in mig.stats.last_messages)


def test_date_filter_skips_out_of_range(tmp_path):
    syno = MagicMock()
    mig = _migrator(tmp_path, syno)
    mig.min_ts = 1_700_000_000.0
    mig.max_ts = 1_800_000_000.0
    item = {"id": 1, "filename": "old.jpg", "time": 1_000_000_000}
    asset_id, _ = mig._process_one_asset(item, tmp_path, mig.sessions[0])
    assert asset_id is None
    assert mig.stats.skipped == 1
    syno.download.assert_not_called()


_LIVE_ITEM = {
    "id": 12534,
    "filename": "IMG_7688.HEIC",
    "type": "live",
    "time": 1_700_000_000,
    "additional": {
        "thumbnail": {
            "unit_id": 12542,
            "cache_key": "12542_1778357880",
        }
    },
}


def test_item_timestamp_normalizes_milliseconds(tmp_path):
    mig = _migrator(tmp_path, MagicMock())
    assert mig._item_timestamp({"time": 1_700_000_000}) == 1_700_000_000
    assert mig._item_timestamp({"time": 1_700_000_000_000}) == 1_700_000_000
    assert mig._item_timestamp({"indexed_time": 1_700_000_000_000}) == 1_700_000_000


def test_live_photo_uploads_motion_then_still_with_link(tmp_path):
    syno = MagicMock()
    still = tmp_path / "still.HEIC"
    motion = tmp_path / "motion.MOV"
    still.write_bytes(b"heic")
    motion.write_bytes(b"mov")
    syno.download_live_photo.return_value = (still, motion)

    mig = _migrator(tmp_path, syno)
    uploader = mig.sessions[0]
    uploader.immich.upload_asset.side_effect = [
        ("motion-id", False, None),
        ("still-id", False, None),
    ]

    asset_id, name = mig._process_one_asset(_LIVE_ITEM, tmp_path, uploader)

    assert asset_id == "still-id"
    assert name == "cyrille"
    syno.download_live_photo.assert_called_once()
    syno.download.assert_not_called()
    calls = uploader.immich.upload_asset.call_args_list
    assert calls[0].kwargs["visibility"] == "hidden"
    assert calls[0].kwargs["device_asset_id"] == "cyrille_synoid12534_motion"
    assert calls[1].kwargs["live_photo_video_id"] == "motion-id"
    assert calls[1].kwargs["device_asset_id"] == "cyrille_synoid12534"
    assert calls[1].kwargs["file_created_at"] == 1_700_000_000
    assert mig.stats.uploaded == 1
    assert mig.checkpoint.is_uploaded("cyrille", "12534") == "still-id"


def test_duplicate_linked_jpeg_uses_regular_download(tmp_path):
    syno = MagicMock()
    jpeg = tmp_path / "watch.jpg"
    jpeg.write_bytes(b"jpeg")
    syno.download.return_value = jpeg

    mig = _migrator(tmp_path, syno)
    uploader = mig.sessions[0]
    uploader.immich.upload_asset.return_value = ("imm-1", False, None)
    item = {
        "id": 435425,
        "filename": "watch.jpg",
        "type": "photo",
        "time": 1_700_000_000,
        "additional": {"thumbnail": {"unit_id": 435419}},
    }

    asset_id, _ = mig._process_one_asset(item, tmp_path, uploader)

    assert asset_id == "imm-1"
    syno.download.assert_called_once()
    syno.download_live_photo.assert_not_called()


def test_live_photo_not_skipped_when_videos_disabled(tmp_path):
    syno = MagicMock()
    still = tmp_path / "still.HEIC"
    still.write_bytes(b"heic")
    syno.download_live_photo.return_value = (still, None)

    mig = _migrator(tmp_path, syno)
    mig.include_videos = False
    uploader = mig.sessions[0]
    uploader.immich.upload_asset.return_value = ("still-id", False, None)

    asset_id, _ = mig._process_one_asset(_LIVE_ITEM, tmp_path, uploader)
    assert asset_id == "still-id"
    syno.download_live_photo.assert_called_once()


def test_video_skipped_when_videos_disabled(tmp_path):
    syno = MagicMock()
    mig = _migrator(tmp_path, syno)
    mig.include_videos = False
    item = {"id": 9, "filename": "clip.mp4", "type": "video"}
    asset_id, _ = mig._process_one_asset(item, tmp_path, mig.sessions[0])
    assert asset_id is None
    assert mig.stats.skipped == 1
    syno.download.assert_not_called()
    syno.download_live_photo.assert_not_called()


def test_live_still_download_failure_counts_as_failed(tmp_path):
    syno = MagicMock()
    syno.download_live_photo.return_value = (None, None)
    mig = _migrator(tmp_path, syno)
    asset_id, _ = mig._process_one_asset(
        _LIVE_ITEM, tmp_path, mig.sessions[0]
    )
    assert asset_id is None
    assert mig.stats.failed == 1
    assert mig.checkpoint.data["failed_items"]["cyrille"]["12534"] == (
        "download_failed"
    )


def test_external_library_link_skips_download(tmp_path):
    syno = MagicMock()
    mig = _migrator(tmp_path, syno)
    mig.external_library_mode = True
    mig._asset_index["cyrille"] = {
        "watch.jpg": [("imm-ext", None, "lib-1", "/homes/cyrille/watch.jpg")]
    }
    item = {"id": 42, "filename": "watch.jpg", "type": "photo"}

    asset_id, _ = mig._process_one_asset(item, tmp_path, mig.sessions[0])

    assert asset_id == "imm-ext"
    assert mig.stats.linked == 1
    assert mig.checkpoint.is_uploaded("cyrille", "42") == "imm-ext"
    syno.download.assert_not_called()
    syno.download_live_photo.assert_not_called()
    mig.sessions[0].immich.upload_asset.assert_not_called()


def test_external_library_falls_through_to_upload_when_no_match(tmp_path):
    syno = MagicMock()
    jpeg = tmp_path / "watch.jpg"
    jpeg.write_bytes(b"jpeg")
    syno.download.return_value = jpeg

    mig = _migrator(tmp_path, syno)
    mig.external_library_mode = True
    mig._asset_index["cyrille"] = {}
    mig.sessions[0].immich.find_assets_by_filename.return_value = []
    mig.sessions[0].immich.upload_asset.return_value = ("imm-new", False, None)
    item = {"id": 42, "filename": "watch.jpg", "type": "photo"}

    asset_id, _ = mig._process_one_asset(item, tmp_path, mig.sessions[0])

    assert asset_id == "imm-new"
    syno.download.assert_called_once()
    assert mig.stats.uploaded == 1
    assert mig.stats.linked == 0


def test_external_match_accepts_millisecond_synology_time(tmp_path):
    syno = MagicMock()
    mig = _migrator(tmp_path, syno)
    mig.external_library_mode = True
    mig._asset_index["cyrille"] = {
        "a.jpg": [
            ("ext-old", "2023-10-01T00:00:00+00:00", "lib-a", "/a-old.jpg"),
            ("ext-hit", "2023-11-14T22:13:20+00:00", "lib-a", "/a.jpg"),
        ]
    }
    mig.sessions[0].immich.find_assets_by_filename.return_value = []
    item = {
        "id": 7,
        "filename": "a.jpg",
        "type": "photo",
        "time": 1_700_000_000_000,  # ms for 2023-11-14 22:13:20 UTC
    }

    asset_id, _ = mig._process_one_asset(item, tmp_path, mig.sessions[0])
    assert asset_id == "ext-hit"
    syno.download.assert_not_called()


def test_shared_space_skipped_when_disabled(tmp_path):
    syno = MagicMock()
    mig = _migrator(tmp_path, syno)
    mig.include_shared_space = False
    mig.run_shared_space()
    syno.list_shared_space_items.assert_not_called()


def test_already_uploaded_is_resumed_without_redownload(tmp_path):
    syno = MagicMock()
    mig = _migrator(tmp_path, syno)
    mig.checkpoint.mark_uploaded("cyrille", "42", "imm-old")
    item = {"id": 42, "filename": "watch.jpg", "type": "photo"}
    asset_id, _ = mig._process_one_asset(item, tmp_path, mig.sessions[0])
    assert asset_id == "imm-old"
    syno.download.assert_not_called()
