"""Synology client helpers and API error handling."""

from unittest.mock import MagicMock, patch

import pytest

from synmich.core.synology import (
    SynologyClient,
    SynologyError,
    download_unit,
    live_photo_parts,
)


def test_download_unit_uses_item_id_when_no_thumbnail():
    item = {"id": 10, "filename": "a.jpg", "indexed_time": 1_700_000_000_000}
    unit_id, cache_key = download_unit(item)
    assert unit_id == 10
    assert cache_key == "10_1700000000"


def test_download_unit_prefers_thumbnail_for_duplicate_linked_items():
    item = {
        "id": 435425,
        "filename": "watch.jpg",
        "indexed_time": 1_700_000_000_000,
        "additional": {
            "thumbnail": {
                "unit_id": 435419,
                "cache_key": "435419_1778357880",
            }
        },
    }
    unit_id, cache_key = download_unit(item)
    assert unit_id == 435419
    assert cache_key == "435419_1778357880"


def test_api_json_raises_on_success_false():
    client = SynologyClient("http://nas:5000")
    client.sid = "sid"
    client.session = MagicMock()
    fake = MagicMock()
    fake.json.return_value = {"success": False, "error": {"code": 104}}
    with patch.object(client, "_api_get", return_value=fake):
        with pytest.raises(SynologyError) as exc:
            client._api_json("SYNO.Foto.Browse.Item", "list", "7")
    assert "104" in str(exc.value)


def test_api_json_returns_inner_data():
    client = SynologyClient("http://nas:5000")
    client.sid = "sid"
    client.session = MagicMock()
    fake = MagicMock()
    fake.json.return_value = {"success": True, "data": {"list": [{"id": 1}]}}
    with patch.object(client, "_api_get", return_value=fake):
        data = client._api_json("SYNO.Foto.Browse.Item", "list", "6")
    assert data["list"][0]["id"] == 1


def test_best_version_caps_at_known_max():
    client = SynologyClient("http://nas:5000")
    client.sid = "sid"
    client.session = MagicMock()
    fake = MagicMock()
    fake.json.return_value = {
        "success": True,
        "data": {"SYNO.Foto.Browse.Item": {"maxVersion": 6}},
    }
    fake.status_code = 200
    client.session.get.return_value = fake
    assert client._best_version("SYNO.Foto.Browse.Item", 7) == 6
    # Cached
    assert client._best_version("SYNO.Foto.Browse.Item", 7) == 6
    assert client.session.get.call_count == 1


def test_list_items_requests_thumbnail_additional():
    client = SynologyClient("http://nas:5000")
    client.sid = "sid"
    client.session = MagicMock()
    with patch.object(client, "_best_version", return_value=6):
        with patch.object(
            client, "_api_json", return_value={"list": []}
        ) as api:
            assert client.list_items(album_id=3) == []
    extra = api.call_args.args[3]
    assert extra["album_id"] == 3
    assert "thumbnail" in extra["additional"]


_LIVE = {
    "id": 12534,
    "filename": "IMG_7688.HEIC",
    "type": "live",
    "indexed_time": 1_700_000_000_000,
    "additional": {
        "thumbnail": {
            "unit_id": 12542,
            "cache_key": "12542_1778357880",
        }
    },
}


def test_live_photo_parts_splits_still_and_motion():
    still_id, still_ck, motion_id, motion_ck = live_photo_parts(_LIVE)
    assert still_id == 12542
    assert still_ck == "12542_1778357880"
    assert motion_id == 12534
    assert motion_ck == "12534_1700000000"


def test_live_photo_parts_none_for_duplicate_linked_jpeg():
    item = {
        "id": 435425,
        "filename": "watch.jpg",
        "type": "photo",
        "additional": {"thumbnail": {"unit_id": 435419}},
    }
    assert live_photo_parts(item) is None


def test_live_photo_parts_none_when_unit_id_matches_item():
    item = {**_LIVE, "additional": {"thumbnail": {"unit_id": 12534}}}
    assert live_photo_parts(item) is None


def test_download_live_photo_forces_motion_unit_id(tmp_path):
    client = SynologyClient("http://nas:5000")
    calls = []

    def fake_download(item, folder, unit_id=None, cache_key=None):
        calls.append((item["filename"], unit_id, cache_key))
        return tmp_path / item["filename"]

    client.download = fake_download
    still, motion = client.download_live_photo(_LIVE, tmp_path)
    assert still.name == "IMG_7688.HEIC"
    assert motion.name == "IMG_7688.MOV"
    assert calls == [
        ("IMG_7688.MOV", 12534, "12534_1700000000"),
        ("IMG_7688.HEIC", 12542, "12542_1778357880"),
    ]


def test_download_live_photo_falls_back_when_parts_unavailable(tmp_path):
    client = SynologyClient("http://nas:5000")
    item = {**_LIVE, "additional": {"thumbnail": {"unit_id": 12534}}}
    client.download = lambda it, folder, **_k: tmp_path / it["filename"]
    still, motion = client.download_live_photo(item, tmp_path)
    assert still.name == "IMG_7688.HEIC"
    assert motion is None


def test_best_version_falls_back_to_6_when_info_fails():
    client = SynologyClient(
        "http://nas:5000", max_retries=1, retry_backoff_s=0
    )
    client.sid = "sid"
    client.session = MagicMock()
    client.session.get.side_effect = ConnectionError("unreachable")
    assert client._best_version("SYNO.Foto.Browse.Item", 7) == 6


def test_best_version_uses_reported_max():
    client = SynologyClient("http://nas:5000", max_retries=1, retry_backoff_s=0)
    client.sid = "sid"
    client.session = MagicMock()
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "success": True,
        "data": {"SYNO.Foto.Browse.Item": {"maxVersion": 4}},
    }
    client.session.get.return_value = fake
    assert client._best_version("SYNO.Foto.Browse.Item", 7) == 4


def test_download_retries_json_error_117_then_succeeds(tmp_path):
    import requests as req

    client = SynologyClient(
        "http://nas:5000", max_retries=3, retry_backoff_s=0
    )
    client.sid = "sid"
    client.session = MagicMock()
    client.session.cookies = req.cookies.RequestsCookieJar()

    json_resp = MagicMock()
    json_resp.status_code = 200
    json_resp.headers = {"Content-Type": "application/json"}
    json_resp.text = '{"success":false}'
    json_resp.json.return_value = {"success": False, "error": {"code": 117}}

    bin_resp = MagicMock()
    bin_resp.status_code = 200
    bin_resp.headers = {"Content-Type": "image/jpeg"}
    bin_resp.iter_content.return_value = [b"JPEGDATA"]

    with patch("synmich.core.synology.requests.Session") as sess_cls:
        sess = MagicMock()
        sess_cls.return_value = sess
        sess.get.side_effect = [json_resp, bin_resp]
        path = client.download(
            {"id": 10, "filename": "a.jpg", "indexed_time": 1_700_000_000_000},
            tmp_path,
        )

    assert path is not None
    assert path.read_bytes() == b"JPEGDATA"
    assert sess.get.call_count == 2
    unit = sess.get.call_args_list[0].kwargs["params"]["unit_id"]
    assert "10" in unit


def test_download_uses_thumbnail_unit_id_in_request(tmp_path):
    import requests as req

    client = SynologyClient(
        "http://nas:5000", max_retries=1, retry_backoff_s=0
    )
    client.sid = "sid"
    client.session = MagicMock()
    client.session.cookies = req.cookies.RequestsCookieJar()

    bin_resp = MagicMock()
    bin_resp.status_code = 200
    bin_resp.headers = {"Content-Type": "image/jpeg"}
    bin_resp.iter_content.return_value = [b"JPEG"]

    item = {
        "id": 435425,
        "filename": "watch.jpg",
        "indexed_time": 1_700_000_000_000,
        "additional": {
            "thumbnail": {
                "unit_id": 435419,
                "cache_key": "435419_1778357880",
            }
        },
    }
    with patch("synmich.core.synology.requests.Session") as sess_cls:
        sess = MagicMock()
        sess_cls.return_value = sess
        sess.get.return_value = bin_resp
        path = client.download(item, tmp_path)

    assert path is not None
    params = sess.get.call_args.kwargs["params"]
    assert params["unit_id"] == "[435419]"
    assert params["cache_key"] == "435419_1778357880"
