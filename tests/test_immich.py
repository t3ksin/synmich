"""Immich create_album handles duplicate names and list payloads."""

from unittest.mock import MagicMock, patch

import pytest

from synmich.core.immich import ImmichClient, ImmichError


def test_create_album_returns_id():
    client = ImmichClient("http://immich:2283", "key")
    resp = MagicMock(status_code=201)
    resp.json.return_value = {"id": "alb-1"}
    with patch("synmich.core.immich.requests.post", return_value=resp):
        assert client.create_album("Trip") == "alb-1"


def test_create_album_reuses_existing_on_400():
    client = ImmichClient("http://immich:2283", "key")
    created = MagicMock(status_code=400)
    listed = MagicMock(status_code=200)
    listed.json.return_value = [{"id": "alb-9", "albumName": "Trip"}]
    with patch("synmich.core.immich.requests.post", return_value=created):
        with patch("synmich.core.immich.requests.get", return_value=listed):
            assert client.create_album("Trip") == "alb-9"


def test_create_album_rejects_list_payload():
    client = ImmichClient("http://immich:2283", "key")
    resp = MagicMock(status_code=200)
    resp.json.return_value = [{"error": "bad"}]
    resp.raise_for_status = MagicMock()
    with patch("synmich.core.immich.requests.post", return_value=resp):
        with pytest.raises(ImmichError, match="Unexpected create-album"):
            client.create_album("Album Name")


def test_upload_asset_sends_live_photo_fields(tmp_path):
    filepath = tmp_path / "IMG_7688.HEIC"
    filepath.write_bytes(b"image")
    response = MagicMock(status_code=201)
    response.json.return_value = {"id": "still-id", "status": "created"}

    with patch("synmich.core.immich.requests.post", return_value=response) as post:
        result = ImmichClient("https://immich.example", "key").upload_asset(
            filepath,
            live_photo_video_id="motion-id",
            visibility="hidden",
        )

    assert result == ("still-id", False, None)
    assert post.call_args.kwargs["data"]["livePhotoVideoId"] == "motion-id"
    assert post.call_args.kwargs["data"]["visibility"] == "hidden"
