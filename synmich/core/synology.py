"""Client Synology Photos API."""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from synmich.core.synology_auth import (
    login_with_2fa,
    cli_otp_prompt,
    fetch_user_id,
    OTPRequired,
    LoginFailed,
)

import urllib3

urllib3.disable_warnings()


class SynologyError(Exception):
    pass


def _is_shared_space(item: Dict[str, Any]) -> bool:
    """Return True if item belongs to the Synology Shared Space.

    Items in the Shared Space have owner_user_id=0 and must be
    accessed via the SYNO.FotoTeam.* APIs instead of SYNO.Foto.*.
    """
    return item.get("owner_user_id") == 0


class SynologyClient:
    """Synology Photos API client (DSM 7+).

    Thread-safe: all HTTP calls are serialized via an internal lock
    to avoid `requests.Session` corruption when used from multiple
    threads (which is unsafe per requests docs).
    """

    def __init__(
        self,
        base_url: str,
        verify_ssl: bool = False,
        max_retries: int = 5,
        retry_backoff_s: int = 3,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s
        self.timeout = timeout
        self.session: Optional[requests.Session] = None
        self.sid: Optional[str] = None
        self.username: Optional[str] = None
        self.user_id: Optional[int] = None
        # Lock to serialize HTTP requests on the same Session
        # (requests.Session is NOT thread-safe).
        self._lock = threading.Lock()

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

    def login(self, username: str, password: str, otp_provider=None) -> bool:
        """Synology login with 2FA support (v1.0.4).

        If the account has 2FA enabled, otp_provider is called to enter
        the OTP. Default: CLI prompt via click.

        The returned device_token is saved (~/.config/synmich/
        device_tokens.json, 600) to skip the OTP on future
        connections as long as Synology considers the device trusted.
        """
        if otp_provider is None:
            otp_provider = cli_otp_prompt

        # v1.0.4 fix: create session if needed
        if self.session is None:
            import requests
            self.session = requests.Session()

        try:
            self.sid = login_with_2fa(
                session=self.session,
                base_url=self.base_url,
                username=username,
                password=password,
                verify_ssl=self.verify_ssl,
                otp_provider=otp_provider,
            )
            self.username = username
            self._password = password
            # v1.1.0 fix: re-populate user_id right after auth. The v1.0.4
            # 2FA rewrite dropped this; without it the Migrator's
            # syno_id_to_session owner mapping misses and albums are marked
            # done with 0 items uploaded.
            self.user_id = fetch_user_id(
                self.session, self.base_url, self.sid, self.verify_ssl
            )
            if self.user_id is None:
                logging.getLogger("synmich").warning(
                    "Synology: user_id unavailable after login for %s "
                    "(SYNO.Foto.UserInfo/me failed)",
                    username,
                )
            return True
        except (LoginFailed, OTPRequired) as e:
            logging.getLogger("synmich").error("Synology login failed: %s", e)
            return False


    def logout(self) -> None:
        if self.session and self.sid:
            try:
                self.session.get(
                    f"{self.base_url}/webapi/auth.cgi",
                    params={
                        "api": "SYNO.API.Auth",
                        "version": "6",
                        "method": "logout",
                        "session": "SynoPhoto",
                        "_sid": self.sid,
                    },
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                )
            except Exception:
                pass
        self.session = None
        self.sid = None

    def _api_get(
        self,
        api: str,
        method: str,
        version: str,
        extra: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ):
        if not self.sid or not self.session:
            raise SynologyError("Not logged in")
        params = {
            "api": api,
            "method": method,
            "version": version,
            "_sid": self.sid,
        }
        if extra:
            params.update(extra)

        def _do():
            # Serialize requests on the same Session (not thread-safe)
            with self._lock:
                return self.session.get(
                    f"{self.base_url}/webapi/entry.cgi",
                    params=params,
                    verify=self.verify_ssl,
                timeout=self.timeout,
                stream=stream,
            )

        return self._retry(_do)

    def me(self) -> Optional[int]:
        """Return the syno_user_id of the logged-in user (cached).

        login() populates user_id at auth time; this is the lazy
        fallback if it's still unset (e.g. user_id was cleared).
        """
        if self.user_id is None and self.sid and self.session:
            self.user_id = fetch_user_id(
                self.session, self.base_url, self.sid, self.verify_ssl
            )
        return self.user_id

    def list_albums(self) -> List[Dict[str, Any]]:
        """List all visible albums with sharing_info."""
        all_albums = []
        offset = 0
        while True:
            r = self._api_get(
                "SYNO.Foto.Browse.Album",
                "list",
                "5",
                {
                    "offset": offset,
                    "limit": 500,
                    "additional": json.dumps(
                        ["sharing_info", "provider_count"]
                    ),
                },
            )
            chunk = (
                r.json().get("data", {}).get("list", [])
            )
            if not chunk:
                break
            all_albums.extend(chunk)
            if len(chunk) < 500:
                break
            offset += len(chunk)
        return all_albums

    def list_items(
        self,
        album_id: Optional[int] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """List items in an album or full timeline."""
        all_items = []
        offset = 0
        while True:
            extra: Dict[str, Any] = {
                "offset": offset,
                "limit": limit,
            }
            if album_id is not None:
                extra["album_id"] = album_id
            r = self._api_get(
                "SYNO.Foto.Browse.Item",
                "list",
                "7",
                extra,
            )
            chunk = (
                r.json().get("data", {}).get("list", [])
            )
            if not chunk:
                break
            all_items.extend(chunk)
            if len(chunk) < limit:
                break
            offset += len(chunk)
        return all_items

    def list_shared_space_items(
        self, limit: int = 5000
    ) -> List[Dict[str, Any]]:
        """List items in the Synology Shared Space (Team library).

        New in v1.0.1: uses the SYNO.FotoTeam.Browse.Item API to enumerate
        photos and videos in the shared/team space. These items have
        owner_user_id=0 and must be downloaded via SYNO.FotoTeam.Download.
        """
        all_items = []
        offset = 0
        while True:
            r = self._api_get(
                "SYNO.FotoTeam.Browse.Item",
                "list",
                "7",
                {"offset": offset, "limit": limit},
            )
            chunk = (
                r.json().get("data", {}).get("list", [])
            )
            if not chunk:
                break
            all_items.extend(chunk)
            if len(chunk) < limit:
                break
            offset += len(chunk)
        return all_items

    def count_items(
        self, album_id: Optional[int] = None
    ) -> int:
        """Count total items."""
        extra = {}
        if album_id:
            extra["album_id"] = album_id
        r = self._api_get(
            "SYNO.Foto.Browse.Item",
            "count",
            "7",
            extra,
        )
        return r.json().get("data", {}).get("count", 0)

    def count_shared_space_items(self) -> int:
        """Count items in Shared Space (new in v1.0.1)."""
        r = self._api_get(
            "SYNO.FotoTeam.Browse.Item", "count", "7"
        )
        return r.json().get("data", {}).get("count", 0)

    def download(
        self,
        item: Dict[str, Any],
        folder: Path,
    ) -> Optional[Path]:
        """Download an item. Returns local path or None.

        Uses a fresh requests session per call to be thread-safe
        (requests.Session shared across threads can cause data races
        on streamed responses, leading to wrong asset bodies being
        attributed to the wrong file).

        v1.0.1: automatically routes via SYNO.FotoTeam.Download when the
        item belongs to the Shared Space (owner_user_id=0). Previously
        these items would fail silently with an unhelpful JSON response,
        leaving personal albums that contained shared-space photos empty
        in Immich.
        """
        folder.mkdir(parents=True, exist_ok=True)
        original_filename = item["filename"]
        item_id = item["id"]
        # Prefix filename with item_id to avoid collisions when two items
        # share the same filename (very common on Synology shared albums
        # where photos can have generic names like IMG_xxxx.HEIC).
        # The original name is preserved in the upload via the
        # filename passed to Immich, this is only for local storage.
        filepath = folder / f"{item_id}_{original_filename}"
        cache_key = (
            f"{item_id}_"
            f"{item.get('indexed_time', 0) // 1000}"
        )

        if not self.sid:
            return None

        # v1.0.1: route to the correct API based on item ownership.
        # Items in the Synology Shared Space (owner_user_id=0) must be
        # downloaded via SYNO.FotoTeam.Download. All other items use
        # SYNO.Foto.Download (per-user library).
        download_api = (
            "SYNO.FotoTeam.Download"
            if _is_shared_space(item)
            else "SYNO.Foto.Download"
        )

        params = {
            "api": download_api,
            "method": "download",
            "version": "1",
            "unit_id": json.dumps([item_id]),
            "cache_key": cache_key,
            "_sid": self.sid,
        }

        def _do():
            # Fresh session per download to avoid concurrent
            # streaming on the shared Session.
            return requests.get(
                f"{self.base_url}/webapi/entry.cgi",
                params=params,
                verify=self.verify_ssl,
                timeout=self.timeout,
                stream=True,
            )

        try:
            r = self._retry(_do)
        except Exception:
            return None

        if r.status_code != 200:
            return None

        ctype = r.headers.get("Content-Type", "").lower()
        if (
            "json" in ctype
            or "html" in ctype
            or "text" in ctype
        ):
            # The API returned a JSON/HTML body instead of binary data.
            # This usually means the wrong API was selected for this item
            # (e.g. SYNO.Foto.Download for a shared-space item, or vice
            # versa). v1.0.1: the routing above should prevent this, but
            # we keep the safety net to fail closed.
            return None

        try:
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
        finally:
            r.close()

        if filepath.stat().st_size == 0:
            try:
                filepath.unlink()
            except Exception:
                pass
            return None

        return filepath

    # === Admin / Detection ===

    def list_dsm_users(self) -> List[Dict[str, Any]]:
        """
        List DSM users (requires admin account).
        Returns [{name, uid, ...}].
        """
        if not self.sid or not self.session:
            raise SynologyError("Not logged in")

        def _do():
            return self.session.get(
                f"{self.base_url}/webapi/entry.cgi",
                params={
                    "api": "SYNO.Core.User",
                    "version": "1",
                    "method": "list",
                    "type": "local",
                    "offset": 0,
                    "limit": 500,
                    "_sid": self.sid,
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )

        r = self._retry(_do)
        d = r.json()
        if not d.get("success"):
            return []
        return d.get("data", {}).get("users", [])
