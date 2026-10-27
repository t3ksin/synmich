"""Reusable HTTP sessions leased exclusively to one request at a time."""

import threading
from contextlib import contextmanager
from typing import Dict, List

import requests


class SessionPool:
    """Keep TCP/TLS connections alive without sharing Session state concurrently.

    A lease covers the whole streamed response, not only its headers. Clients
    own separate pools, so cookies and API credentials cannot cross accounts.
    """

    def __init__(self, max_idle: int = 16):
        self._lock = threading.Lock()
        self._idle: List[requests.Session] = []
        self._active: Dict[requests.Session, int] = {}
        self._generation = 0
        self._max_idle = max_idle

    def acquire(self) -> requests.Session:
        with self._lock:
            session = self._idle.pop() if self._idle else requests.Session()
            self._active[session] = self._generation
            return session

    def release(self, session: requests.Session) -> None:
        with self._lock:
            generation = self._active.pop(session, None)
            if generation == self._generation and len(self._idle) < self._max_idle:
                self._idle.append(session)
                return
        session.close()

    @contextmanager
    def session(self):
        session = self.acquire()
        try:
            yield session
        finally:
            self.release(session)

    def close(self) -> None:
        """Close idle sessions; active leases close when released. Reusable later."""
        with self._lock:
            self._generation += 1
            idle, self._idle = self._idle, []
        for session in idle:
            session.close()
