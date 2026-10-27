"""Synology client helpers and API error handling."""

from unittest.mock import MagicMock, patch

import pytest

from synmich.core.synology import (
    SynologyClient,
    SynologyError,
    download_unit,
    extract_live_bundle,
    live_photo_parts,
    media_kind,
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


HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "


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
        path = tmp_path / item["filename"]
        path.write_bytes(MOV if path.suffix == ".MOV" else HEIC)
        return path

    client.download = fake_download
    still, motion = client.download_live_photo(_LIVE, tmp_path)
    assert still.name == "IMG_7688.HEIC"
    assert motion.name == "IMG_7688.MOV"
    assert calls == [
        ("IMG_7688.MOV", 12534, "12534_1700000000"),
        ("IMG_7688.HEIC", 12542, "12542_1778357880"),
    ]


def test_extract_live_bundle_splits_heic_and_mov():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("IMG_1786.HEIC", HEIC)
        zf.writestr("IMG_1786.MOV", MOV)
    still_name, still, motion_name, motion = extract_live_bundle(buf.getvalue())
    assert still_name == "IMG_1786.HEIC"
    assert still == HEIC
    assert motion_name == "IMG_1786.MOV"
    assert motion == MOV


def test_extract_live_bundle_none_for_plain_heic():
    assert extract_live_bundle(b"\x00\x00\x00\x18ftypheic") is None


def test_download_live_photo_falls_back_when_parts_unavailable(tmp_path):
    client = SynologyClient("http://nas:5000")
    item = {**_LIVE, "additional": {"thumbnail": {"unit_id": 12534}}}
    client._download_live_zip = lambda it, folder: (None, None)
    path = tmp_path / item["filename"]
    path.write_bytes(HEIC)
    client.download = lambda it, folder, **_k: path
    still, motion = client.download_live_photo(item, tmp_path)
    assert still.name == "IMG_7688.HEIC"
    assert motion is None


def test_download_live_photo_extracts_item_id_zip(tmp_path):
    import io
    import zipfile

    import requests as req

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("IMG_7688.HEIC", HEIC)
        zf.writestr("IMG_7688.MOV", MOV)
    zip_bytes = buf.getvalue()

    client = SynologyClient("http://nas:5000", max_retries=1, retry_backoff_s=0)
    client.sid = "sid"
    client.session = MagicMock()
    client.session.cookies = req.cookies.RequestsCookieJar()

    zip_resp = MagicMock()
    zip_resp.status_code = 200
    zip_resp.headers = {"Content-Type": "application/zip"}
    zip_resp.iter_content.return_value = [zip_bytes]

    item = {**_LIVE, "additional": {"thumbnail": {"unit_id": 12534}}}
    with patch("synmich.core.synology.requests.Session") as sess_cls:
        sess = MagicMock()
        sess_cls.return_value = sess
        sess.get.return_value = zip_resp
        still, motion = client.download_live_photo(item, tmp_path)

    assert still is not None and still.read_bytes() == HEIC
    assert motion is not None and motion.read_bytes() == MOV
    params = sess.get.call_args.kwargs["params"]
    assert params["item_id"] == "[12534]"
    assert "unit_id" not in params


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


def test_bundle_preferred_even_when_thumbnail_has_different_id(tmp_path):
    client = SynologyClient("http://nas:5000")
    still = tmp_path / "image.HEIC"
    motion = tmp_path / "motion.MOV"
    still.write_bytes(HEIC)
    motion.write_bytes(MOV)
    with patch.object(client, "_download_live_zip", return_value=(still, motion)):
        with patch.object(client, "download") as download:
            assert client.download_live_photo(_LIVE, tmp_path) == (still, motion)
    download.assert_not_called()


@pytest.mark.parametrize("swapped", [False, True])
def test_split_live_photo_checks_content_instead_of_unit_roles(tmp_path, swapped):
    client = SynologyClient("http://nas:5000")
    client._download_live_zip = lambda *_: (None, None)

    def download(item, folder, **kwargs):
        path = folder / item["filename"]
        is_motion_name = path.suffix == ".MOV"
        path.write_bytes(MOV if is_motion_name != swapped else HEIC)
        return path

    client.download = download
    still, motion = client.download_live_photo(_LIVE, tmp_path)
    assert still.read_bytes() == HEIC
    assert motion.read_bytes() == MOV
    assert motion.suffix == ".MOV"


def test_still_bytes_returned_as_mov_are_not_a_live_video(tmp_path):
    client = SynologyClient("http://nas:5000")
    client._download_live_zip = lambda *_: (None, None)

    def download(item, folder, **kwargs):
        path = folder / item["filename"]
        path.write_bytes(HEIC)
        return path

    client.download = download
    still, motion = client.download_live_photo(_LIVE, tmp_path)
    assert still.read_bytes() == HEIC
    assert motion is None


@pytest.mark.parametrize("shared", [False, True])
def test_video_error_117_falls_back_to_streamed_item_download(tmp_path, shared):
    import requests as req
    client = SynologyClient("http://nas:5000", max_retries=1)
    client.sid = "sid"
    client.session = MagicMock()
    client.session.cookies = req.cookies.RequestsCookieJar()
    error = MagicMock(status_code=200)
    error.headers = {"Content-Type": "application/json"}
    error.text = '{"success":false,"error":{"code":117}}'
    error.json.return_value = {"success": False, "error": {"code": 117}}
    success = MagicMock(status_code=200)
    success.headers = {"Content-Type": "video/quicktime"}
    success.iter_content.return_value = [MOV]
    item = {"id": 105315, "filename": "IMG_0002.MOV", "owner_user_id": 0 if shared else 1}
    with patch("synmich.core.synology.requests.Session") as factory:
        factory.return_value.get.side_effect = [error, success]
        path = client.download(item, tmp_path)
        calls = factory.return_value.get.call_args_list
    assert path.read_bytes() == MOV
    assert calls[1].kwargs["params"]["item_id"] == "[105315]"
    assert "unit_id" not in calls[1].kwargs["params"]
    assert calls[1].kwargs["params"]["api"] == (
        "SYNO.FotoTeam.Download" if shared else "SYNO.Foto.Download"
    )
    assert calls[1].kwargs["stream"] is True
    success.iter_content.assert_called_once_with(8192)
    error.close.assert_called_once()
    success.close.assert_called_once()


@pytest.mark.parametrize("payload,kind", [
    (HEIC, "image"), (MOV, "video"),
    (b"\xff\xd8\xffJPEG", "image"), (b"<html>error</html>", None),
    (b"\x00\x00\x00\x08wide", "video"),
])
def test_media_kind_ignores_filename(tmp_path, payload, kind):
    path = tmp_path / "misleading.MOV"
    path.write_bytes(payload)
    assert media_kind(path) == kind


def test_live_photo_named_after_motion_keeps_both_files(tmp_path):
    client = SynologyClient("http://nas:5000")
    client._download_live_zip = lambda *_: (None, None)

    def download(item, folder, unit_id=None, **kwargs):
        path = folder / item["filename"]
        path.write_bytes(HEIC if unit_id == 12542 else MOV)
        return path

    client.download = download
    still, motion = client.download_live_photo({**_LIVE, "filename": "IMG_7688.MOV"}, tmp_path)
    assert still != motion
    assert still.read_bytes() == HEIC
    assert motion.read_bytes() == MOV
    assert still.suffix == ".HEIC"


def test_error_117_item_fallback_is_bounded(tmp_path):
    import requests as req
    client = SynologyClient("http://nas:5000", max_retries=1, retry_backoff_s=0)
    client.sid = "sid"
    client.session = MagicMock()
    client.session.cookies = req.cookies.RequestsCookieJar()
    error = MagicMock(status_code=200)
    error.headers = {"Content-Type": "application/json"}
    error.json.return_value = {"success": False, "error": {"code": 117}}
    error.text = '{"error":{"code":117}}'
    with patch("synmich.core.synology.requests.Session") as factory:
        factory.return_value.get.return_value = error
        assert client.download({"id": 42, "filename": "video.MOV"}, tmp_path) is None
        assert factory.return_value.get.call_count == 2
