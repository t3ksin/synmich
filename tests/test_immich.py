"""Immich create_album handles duplicate names and list payloads."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from requests_toolbelt import MultipartEncoder

from synmich.core.immich import ImmichClient, ImmichError, sha1_b64


def test_create_album_returns_id():
    client = ImmichClient("http://immich:2283", "key")
    listed = MagicMock(status_code=200)
    listed.json.return_value = []
    listed.raise_for_status = MagicMock()
    resp = MagicMock(status_code=201)
    resp.json.return_value = {"id": "alb-1"}
    resp.raise_for_status = MagicMock()
    with patch("synmich.core.immich.requests.get", return_value=listed):
        with patch("synmich.core.immich.requests.post", return_value=resp):
            assert client.create_album("Trip") == "alb-1"


def test_create_album_reuses_existing_before_post():
    client = ImmichClient("http://immich:2283", "key")
    listed = MagicMock(status_code=200)
    listed.json.return_value = [
        {"id": "empty", "albumName": "Trip", "assetCount": 0},
        {"id": "full", "albumName": "Trip", "assetCount": 5},
    ]
    listed.raise_for_status = MagicMock()
    with patch("synmich.core.immich.requests.get", return_value=listed):
        with patch("synmich.core.immich.requests.post") as post:
            assert client.create_album("Trip") == "full"
            post.assert_not_called()


def test_create_album_reuses_existing_on_400():
    client = ImmichClient("http://immich:2283", "key")
    created = MagicMock(status_code=400)
    empty = MagicMock(status_code=200)
    empty.json.return_value = []
    empty.raise_for_status = MagicMock()
    listed = MagicMock(status_code=200)
    listed.json.return_value = [{"id": "alb-9", "albumName": "Trip"}]
    listed.raise_for_status = MagicMock()
    with patch("synmich.core.immich.requests.post", return_value=created):
        with patch(
            "synmich.core.immich.requests.get",
            side_effect=[empty, listed],
        ):
            assert client.create_album("Trip") == "alb-9"


def test_create_album_rejects_list_payload():
    client = ImmichClient("http://immich:2283", "key")
    listed = MagicMock(status_code=200)
    listed.json.return_value = []
    listed.raise_for_status = MagicMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = [{"error": "bad"}]
    resp.raise_for_status = MagicMock()
    with patch("synmich.core.immich.requests.get", return_value=listed):
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
    encoder = post.call_args.kwargs["data"]
    assert isinstance(encoder, MultipartEncoder)
    assert encoder.fields["livePhotoVideoId"] == "motion-id"
    assert encoder.fields["visibility"] == "hidden"


def test_upload_asset_streams_multipart_instead_of_buffering(tmp_path):
    filepath = tmp_path / "clip.mp4"
    filepath.write_bytes(b"video-bytes")
    response = MagicMock(status_code=201)
    response.json.return_value = {"id": "vid-1", "status": "created"}

    with patch("synmich.core.immich.requests.post", return_value=response) as post:
        result = ImmichClient("https://immich.example", "key").upload_asset(
            filepath,
            device_id="synmich",
            device_asset_id="user_synoid1",
        )

    assert result == ("vid-1", False, None)
    kwargs = post.call_args.kwargs
    assert "files" not in kwargs
    encoder = kwargs["data"]
    assert isinstance(encoder, MultipartEncoder)
    assert hasattr(encoder, "read")
    assert kwargs["headers"]["x-immich-checksum"] == sha1_b64(filepath)
    assert kwargs["headers"]["Content-Type"] == encoder.content_type
    assert "multipart/form-data" in encoder.content_type
    assert kwargs["timeout"] == (30, None)
    name, _fileobj, ctype = encoder.fields["assetData"]
    assert name == "clip.mp4"
    assert ctype == "application/octet-stream"
    assert encoder.fields["deviceAssetId"] == "user_synoid1"
    assert encoder.fields["isFavorite"] == "false"


def test_upload_asset_rebuilds_encoder_on_retry(tmp_path):
    filepath = tmp_path / "clip.mp4"
    filepath.write_bytes(b"video-bytes")
    ok = MagicMock(status_code=201)
    ok.json.return_value = {"id": "vid-2", "status": "created"}
    client = ImmichClient(
        "https://immich.example",
        "key",
        retry_backoff_s=0,
    )

    with patch(
        "synmich.core.immich.requests.post",
        side_effect=[requests.exceptions.ConnectionError("boom"), ok],
    ) as post:
        result = client.upload_asset(filepath)

    assert result == ("vid-2", False, None)
    assert post.call_count == 2
    assert isinstance(post.call_args.kwargs["data"], MultipartEncoder)
