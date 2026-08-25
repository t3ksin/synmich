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

log = logging.getLogger("synmich")


class SynologyError(Exception):
    pass


def _is_shared_space(item: Dict[str, Any]) -> bool:
    """Return True if item belongs to the Synology Shared Space.

    Items in the Shared Space have owner_user_id=0 and must be
    accessed via the SYNO.FotoTeam.* APIs instead of SYNO.Foto.*.
    """
    return item.get("owner_user_id") == 0


def download_unit(item: Dict[str, Any]) -> Tuple[Any, str]:
    """Return the (unit_id, cache_key) to pass to SYNO.Foto.Download.

    Duplicate-linked items (Synology Photos stores one physical file and
    points other items at it) cannot be downloaded with the item's own
    `id`: the NAS returns error 117. The real storage unit is exposed as
    `additional.thumbnail.unit_id` / `cache_key`, which `list_items`
    requests via additional=["thumbnail"].
    """
    item_id = item["id"]
    thumb = (item.get("additional") or {}).get("thumbnail") or {}
    unit_id = thumb.get("unit_id") if thumb.get("unit_id") is not None else item_id
    cache_key = thumb.get("cache_key") or (
        f"{item_id}_{item.get('indexed_time', 0) // 1000}"
    )
    return unit_id, str(cache_key)


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
        # Max supported API versions, queried once per API via SYNO.API.Info.
        self._api_versions: Dict[str, int] = {}

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

    def _best_version(self, api: str, known_max: int) -> int:
        """Highest API version this NAS supports for `api`, capped at
        `known_max` (the highest the code is written for).

        Requesting a version above the NAS's maxVersion returns
        `success:false` (error 104) with HTTP 200. synmich previously used
        version "7" for SYNO.Foto.Browse.Item, which caps at 6 on most
        DSM 7.x / Photos 1.9 boxes — list/count came back empty and albums
        were created with zero photos migrated.
        """
        with self._lock:
            cached = self._api_versions.get(api)
        if cached is not None:
            return min(cached, known_max)

        maxv = known_max
        # Photos 1.9 / DSM 7.x commonly cap Browse.Item at 6, not 7.
        # If SYNO.API.Info is unreachable we still prefer 6 over 7.
        if api.endswith(".Browse.Item") and known_max >= 6:
            maxv = 6
        try:
            def _do():
                if not self.session:
                    raise SynologyError("Not logged in")
                with self._lock:
                    return self.session.get(
                        f"{self.base_url}/webapi/query.cgi",
                        params={
                            "api": "SYNO.API.Info",
                            "version": "1",
                            "method": "query",
                            "query": api,
                        },
                        verify=self.verify_ssl,
                        timeout=self.timeout,
                    )

            r = self._retry(_do)
            payload = r.json()
            if payload.get("success"):
                reported = (
                    (payload.get("data") or {}).get(api, {}) or {}
                ).get("maxVersion")
                if reported:
                    maxv = int(reported)
        except Exception:  # noqa: BLE001
            pass

        chosen = max(1, min(maxv, known_max))
        with self._lock:
            self._api_versions[api] = chosen
        return chosen

    def _api_json(
        self,
        api: str,
        method: str,
        version: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """GET an API and return its inner `data` object, raising on errors.

        The Synology web API always answers HTTP 200 and signals failures
        via `success:false` in the body. Ignoring that flag made failures
        (e.g. an unsupported API version) look like empty results.
        """
        r = self._api_get(api, method, version, extra)
        try:
            payload = r.json()
        except ValueError as e:
            raise SynologyError(f"{api}.{method}: invalid JSON: {e}") from e
        if not payload.get("success"):
            code = (payload.get("error") or {}).get("code")
            raise SynologyError(f"{api}.{method}: API error {code}")
        return payload.get("data") or {}

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
        version = str(self._best_version("SYNO.Foto.Browse.Album", 5))
        while True:
            data = self._api_json(
                "SYNO.Foto.Browse.Album",
                "list",
                version,
                {
                    "offset": offset,
                    "limit": 500,
                    "additional": json.dumps(
                        ["sharing_info", "provider_count"]
                    ),
                },
            )
            chunk = data.get("list") or []
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
        """List items in an album or full timeline.

        Requests additional=["thumbnail"] so each item carries the real
        download unit_id/cache_key (needed for duplicate-linked items).
        """
        all_items = []
        offset = 0
        version = str(self._best_version("SYNO.Foto.Browse.Item", 7))
        while True:
            extra: Dict[str, Any] = {
                "offset": offset,
                "limit": limit,
                "additional": json.dumps(["thumbnail"]),
            }
            if album_id is not None:
                extra["album_id"] = album_id
            data = self._api_json(
                "SYNO.Foto.Browse.Item",
                "list",
                version,
                extra,
            )
            chunk = data.get("list") or []
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

        Uses the SYNO.FotoTeam.Browse.Item API to enumerate photos and
        videos in the shared/team space. These items have owner_user_id=0
        and must be downloaded via SYNO.FotoTeam.Download.
        """
        all_items = []
        offset = 0
        version = str(self._best_version("SYNO.FotoTeam.Browse.Item", 7))
        while True:
            data = self._api_json(
                "SYNO.FotoTeam.Browse.Item",
                "list",
                version,
                {
                    "offset": offset,
                    "limit": limit,
                    "additional": json.dumps(["thumbnail"]),
                },
            )
            chunk = data.get("list") or []
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
        extra: Dict[str, Any] = {}
        if album_id:
            extra["album_id"] = album_id
        data = self._api_json(
            "SYNO.Foto.Browse.Item",
            "count",
            str(self._best_version("SYNO.Foto.Browse.Item", 7)),
            extra,
        )
        return data.get("count", 0)

    def count_shared_space_items(self) -> int:
        """Count items in Shared Space."""
        data = self._api_json(
            "SYNO.FotoTeam.Browse.Item",
            "count",
            str(self._best_version("SYNO.FotoTeam.Browse.Item", 7)),
        )
        return data.get("count", 0)

    def download(
        self,
        item: Dict[str, Any],
        folder: Path,
    ) -> Optional[Path]:
        """Download an item. Returns local path or None.

        Uses a fresh requests session per call (seeded with the login
        cookies) so concurrent streamed downloads cannot corrupt each
        other, while still sending the authenticated SID + cookies.

        Shared Space items (owner_user_id=0) go through
        SYNO.FotoTeam.Download. Duplicate-linked items use
        additional.thumbnail.unit_id rather than the item's own id.
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

        unit_id, cache_key = download_unit(item)
        download_api = (
            "SYNO.FotoTeam.Download"
            if _is_shared_space(item)
            else "SYNO.Foto.Download"
        )

        with self._lock:
            sid = self.sid
            cookie_dict = {}
            if self.session is not None:
                cookie_dict = requests.utils.dict_from_cookiejar(
                    self.session.cookies
                )

        if not sid:
            log.warning("Download skipped %s: not logged in", original_filename)
            return None

        params = {
            "api": download_api,
            "method": "download",
            "version": "1",
            "unit_id": json.dumps([unit_id]),
            "cache_key": cache_key,
            "_sid": sid,
        }

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            sess = requests.Session()
            if cookie_dict:
                sess.cookies.update(cookie_dict)
            try:
                r = sess.get(
                    f"{self.base_url}/webapi/entry.cgi",
                    params=params,
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                    stream=True,
                )
            except (
                requests.exceptions.RequestException,
                ConnectionError,
            ) as e:
                last_error = f"network: {e}"
                sess.close()
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * attempt)
                    continue
                log.warning(
                    "Download failed %s (id=%s unit=%s): %s",
                    original_filename, item_id, unit_id, last_error,
                )
                return None

            if r.status_code != 200:
                last_error = f"http_{r.status_code}"
                r.close()
                sess.close()
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * attempt)
                    continue
                log.warning(
                    "Download failed %s (id=%s unit=%s): %s",
                    original_filename, item_id, unit_id, last_error,
                )
                return None

            ctype = r.headers.get("Content-Type", "").lower()
            if "json" in ctype or "html" in ctype or "text" in ctype:
                body = ""
                try:
                    body = r.text[:300]
                    err = r.json()
                    last_error = (
                        f"api_error {(err.get('error') or {}).get('code')} "
                        f"{body}"
                    )
                except Exception:  # noqa: BLE001
                    last_error = f"non-binary {ctype}: {body[:200]}"
                r.close()
                sess.close()
                # Application-level errors (e.g. 117) used to be returned
                # as HTTP 200 + JSON and never retried, because _retry()
                # only catches network exceptions.
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * attempt)
                    continue
                log.warning(
                    "Download failed %s (id=%s unit=%s): %s",
                    original_filename, item_id, unit_id, last_error,
                )
                return None

            try:
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)
            finally:
                r.close()
                sess.close()

            if filepath.stat().st_size == 0:
                try:
                    filepath.unlink()
                except Exception:
                    pass
                last_error = "empty_file"
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * attempt)
                    continue
                log.warning(
                    "Download failed %s (id=%s): empty file",
                    original_filename, item_id,
                )
                return None

            return filepath

        log.warning(
            "Download failed %s (id=%s unit=%s): %s",
            original_filename, item_id, unit_id, last_error,
        )
        return None

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
