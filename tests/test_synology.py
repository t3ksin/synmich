"""Synology client helpers and API error handling."""

from unittest.mock import MagicMock, patch

import pytest

from synmich.core.synology import (
    SynologyClient,
    SynologyError,
    download_unit,
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
