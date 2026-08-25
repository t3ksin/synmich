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
