"""Keeping the Synology session alive during long migrations.

A Synology session (SID) expires after a period of inactivity (~60min)
or after a maximum lifetime (~6h depending on DSM).

For long migrations (8h-24h), we need to:
1. Ping the API regularly to keep the session active
2. Detect when the SID expires and re-login automatically

Usage:
    keepalive = SynologyKeepalive(
        client=synology_client,
        username="testtest",
        password="...",
        ping_interval_seconds=1800,  # 30 min
    )
    keepalive.start()
    try:
        # ... migration in progress ...
    finally:
        keepalive.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests

log = logging.getLogger("synmich")


class SynologyKeepalive:
    """Daemon thread that keeps the Synology session alive.

    Pings the SYNO.API.Info API periodically. If the ping fails (session
    expired), it attempts an automatic re-login with the device_token.
    """

    def __init__(
        self,
        client,  # SynologyClient instance
        username: str,
        password: str,
        ping_interval_seconds: int = 1800,
    ):
        self.client = client
        self.username = username
        self.password = password
        self.ping_interval = ping_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reconnect_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="SynologyKeepalive",
        )
        self._thread.start()
        log.info(
            "Synology keepalive started (ping every %ds)", self.ping_interval
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Synology keepalive stopped")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            # Wait the interval (but with a stop check)
            if self._stop_event.wait(self.ping_interval):
                return

            self._check_and_renew()

    def _check_and_renew(self) -> None:
        """Check the session and reconnect if necessary."""
        try:
            ok = self._ping()
            if ok:
                log.debug("Synology keepalive: session OK")
                return

            # Ping failed, attempt a re-login
            log.warning("Synology session expired, re-login...")
            with self._reconnect_lock:
                # Make sure we haven't already been reconnected by
                # another path while waiting for the lock
                if self._ping():
                    return
                self._relogin()
        except Exception as e:
            log.error("Synology keepalive error: %s", e)

    def _ping(self) -> bool:
        """Lightweight ping to check the session."""
        try:
            r = requests.get(
                f"{self.client.base_url}/webapi/entry.cgi",
                params={
                    "api": "SYNO.Foto.Browse.Album",
                    "method": "count",
                    "version": "5",
                    "_sid": self.client.sid,
                },
                verify=self.client.verify_ssl,
                timeout=10,
            )
            data = r.json()
            return bool(data.get("success"))
        except Exception:
            return False

    def _relogin(self) -> None:
        """Reconnect via device_token (silent, no OTP)."""
        from synmich.core.synology_auth import login_with_2fa

        try:
            new_sid = login_with_2fa(
                session=requests.Session(),
                base_url=self.client.base_url,
                username=self.username,
                password=self.password,
                verify_ssl=self.client.verify_ssl,
                otp_provider=None,  # Must work without OTP via device_token
            )
            self.client.sid = new_sid
            log.info("Synology re-login OK, new SID acquired")
        except Exception as e:
            log.error(
                "Synology re-login FAILED: %s — migration may halt soon", e
            )
