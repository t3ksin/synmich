"""Client Immich API."""

import base64
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


class ImmichError(Exception):
    pass


def sha1_b64(filepath: Path) -> str:
    """SHA1 du fichier en base64 (pour x-immich-checksum)."""
    h = hashlib.sha1()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


def iso_utc(ts: Optional[float] = None) -> str:
    if ts is None:
        dt = datetime.now(timezone.utc)
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class ImmichClient:
    """Client pour l'API Immich (v1.106+)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        max_retries: int = 5,
        retry_backoff_s: int = 3,
        timeout: int = 60,
    ):
        # Normalize: ensure '/api' suffix
        url = base_url.rstrip("/")
        if not url.endswith("/api"):
            url = url + "/api"
        self.base_url = url
        self.api_key = api_key
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s
        self.timeout = timeout

    def _retry(self, fn, *args, **kwargs):
        last = None
        for i in range(1, self.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except (
                requests.exceptions.RequestException,
                ConnectionError,
            ) as e:
                last = e
                if i < self.max_retries:
                    time.sleep(self.retry_backoff_s * i)
        raise last

    def _headers(self, extra: Optional[Dict] = None) -> Dict:
        h = {"x-api-key": self.api_key}
        if extra:
            h.update(extra)
        return h

    def ping(self) -> bool:
        """Test de connexion."""
        try:
            r = requests.get(
                f"{self.base_url}/server/ping",
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def me(self) -> Dict[str, Any]:
        def _do():
            r = requests.get(
                f"{self.base_url}/users/me",
                headers=self._headers(),
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()

        return self._retry(_do)

    def list_albums(
        self, shared: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        params = {}
        if shared is not None:
            params["shared"] = "true" if shared else "false"

        def _do():
            r = requests.get(
                f"{self.base_url}/albums",
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()

        return self._retry(_do)

    def get_album(self, album_id: str) -> Dict[str, Any]:
        def _do():
            r = requests.get(
                f"{self.base_url}/albums/{album_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()

        return self._retry(_do)

    def create_album(self, name: str) -> str:
        def _do():
            r = requests.post(
                f"{self.base_url}/albums",
                headers=self._headers(
                    {"Content-Type": "application/json"}
                ),
                json={"albumName": name},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()["id"]

        return self._retry(_do)

    def delete_album(self, album_id: str) -> bool:
        def _do():
            return requests.delete(
                f"{self.base_url}/albums/{album_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )

        r = self._retry(_do)
        return r.status_code in [200, 204]

    def share_album(
        self,
        album_id: str,
        user_id: str,
        role: str = "editor",
    ) -> bool:
        """Share with a user. Falls back to legacy schema if needed."""

        def _do_new():
            return requests.put(
                f"{self.base_url}/albums/{album_id}/users",
                headers=self._headers(
                    {"Content-Type": "application/json"}
                ),
                json={
                    "albumUsers": [
                        {"userId": user_id, "role": role}
                    ]
                },
                timeout=self.timeout,
            )

        r = self._retry(_do_new)
        if r.status_code in [200, 201]:
            return True

        # Legacy schema fallback
        def _do_legacy():
            return requests.put(
                f"{self.base_url}/albums/{album_id}/users",
                headers=self._headers(
                    {"Content-Type": "application/json"}
                ),
                json={"sharedUserIds": [user_id]},
                timeout=self.timeout,
            )

        r2 = self._retry(_do_legacy)
        return r2.status_code in [200, 201]

    def upload_asset(
        self,
        filepath: Path,
        device_id: str = "synmich",
        device_asset_id: Optional[str] = None,
        file_created_at: Optional[float] = None,
        is_favorite: bool = False,
        original_filename: Optional[str] = None,
    ) -> Tuple[Optional[str], bool, Optional[str]]:
        """
        Upload a file to Immich.
        Returns (asset_id, is_duplicate, error_msg).

        original_filename: if set, sent to Immich as the asset filename
        (useful when filepath.name is a temp/prefixed name).
        """
        if not filepath.exists():
            return None, False, "file_not_found"

        size = filepath.stat().st_size
        if size == 0:
            return None, False, "empty_file"

        upload_name = original_filename or filepath.name

        if not device_asset_id:
            device_asset_id = f"{upload_name}_{size}"

        checksum = sha1_b64(filepath)
        created = iso_utc(file_created_at)
        modified = iso_utc(filepath.stat().st_mtime)

        def _do():
            with open(filepath, "rb") as f:
                files = {
                    "assetData": (
                        upload_name,
                        f,
                        "application/octet-stream",
                    )
                }
                form = {
                    "deviceAssetId": device_asset_id,
                    "deviceId": device_id,
                    "fileCreatedAt": created,
                    "fileModifiedAt": modified,
                    "isFavorite": (
                        "true" if is_favorite else "false"
                    ),
                }
                return requests.post(
                    f"{self.base_url}/assets",
                    headers=self._headers(
                        {"x-immich-checksum": checksum}
                    ),
                    files=files,
                    data=form,
                    timeout=300,
                )

        try:
            r = self._retry(_do)
        except Exception as e:
            return None, False, f"network: {e}"

        if r.status_code not in [200, 201]:
            return (
                None,
                False,
                f"http_{r.status_code}: {r.text[:200]}",
            )

        try:
            d = r.json()
        except Exception:
            return None, False, "invalid_json"

        return (
            d.get("id"),
            d.get("status") == "duplicate",
            None,
        )

    def add_assets_to_album(
        self, album_id: str, asset_ids: List[str]
    ) -> Tuple[int, int]:
        """
        Add assets to an album.
        Returns (success_count, fail_count).
        Les 'duplicate' comptent comme success.
        """
        if not asset_ids:
            return 0, 0

        def _do():
            return requests.put(
                f"{self.base_url}/albums/{album_id}/assets",
                headers=self._headers(
                    {"Content-Type": "application/json"}
                ),
                json={"ids": asset_ids},
                timeout=120,
            )

        try:
            r = self._retry(_do)
        except Exception:
            return 0, len(asset_ids)

        if r.status_code not in [200, 201]:
            return 0, len(asset_ids)

        ok, fail = 0, 0
        try:
            for entry in r.json():
                if entry.get("success") or entry.get(
                    "error"
                ) == "duplicate":
                    ok += 1
                else:
                    fail += 1
        except Exception:
            ok = len(asset_ids)
        return ok, fail

    def search_assets(
        self, size: int = 1000
    ) -> Dict[str, Any]:
        """Search assets (used for wipe/verify)."""

        def _do():
            r = requests.post(
                f"{self.base_url}/search/metadata",
                headers=self._headers(
                    {"Content-Type": "application/json"}
                ),
                json={"size": size},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()

        return self._retry(_do)
