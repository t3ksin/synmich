"""Checkpoint for migration resume."""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class Checkpoint:
    """Atomic + thread-safe persistence."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._default()
        try:
            with open(self.path) as f:
                d = json.load(f)
            d.setdefault("syno_to_immich", {})
            d.setdefault("albums_done", [])
            d.setdefault("timeline_done", {})
            d.setdefault("failed_items", {})
            d.setdefault("counters", {})
            d["counters"].setdefault("uploaded", 0)
            d["counters"].setdefault("duplicate", 0)
            d["counters"].setdefault("failed", 0)
            return d
        except Exception:
            return self._default()

    @staticmethod
    def _default() -> Dict[str, Any]:
        return {
            "syno_to_immich": {},
            "albums_done": [],
            "timeline_done": {},
            "failed_items": {},
            "counters": {
                "uploaded": 0,
                "duplicate": 0,
                "failed": 0,
            },
        }

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)

    def reset(self) -> None:
        with self.lock:
            self.data = self._default()
            if self.path.exists():
                self.path.unlink()

    def mark_uploaded(
        self,
        user_name: str,
        syno_id: str,
        immich_id: str,
        was_duplicate: bool = False,
    ) -> None:
        with self.lock:
            self.data["syno_to_immich"].setdefault(
                user_name, {}
            )[str(syno_id)] = immich_id
            if was_duplicate:
                self.data["counters"]["duplicate"] += 1
            else:
                self.data["counters"]["uploaded"] += 1

    def is_uploaded(
        self, user_name: str, syno_id: str
    ) -> Optional[str]:
        return (
            self.data.get("syno_to_immich", {})
            .get(user_name, {})
            .get(str(syno_id))
        )

    def mark_album_done(self, passphrase: str) -> None:
        with self.lock:
            if passphrase not in self.data["albums_done"]:
                self.data["albums_done"].append(passphrase)

    def is_album_done(self, passphrase: str) -> bool:
        return passphrase in self.data.get("albums_done", [])

    def mark_timeline_done(self, user_name: str) -> None:
        with self.lock:
            self.data["timeline_done"][user_name] = True

    def is_timeline_done(self, user_name: str) -> bool:
        return self.data.get("timeline_done", {}).get(
            user_name, False
        )

    def mark_failed(
        self, user_name: str, syno_id: str
    ) -> None:
        with self.lock:
            self.data["failed_items"].setdefault(user_name, [])
            if str(syno_id) not in self.data["failed_items"][
                user_name
            ]:
                self.data["failed_items"][user_name].append(
                    str(syno_id)
                )
                self.data["counters"]["failed"] += 1

    def stats(self) -> Dict[str, int]:
        total_uploaded = sum(
            len(v)
            for v in self.data.get(
                "syno_to_immich", {}
            ).values()
        )
        total_failed = sum(
            len(v)
            for v in self.data.get("failed_items", {}).values()
        )
        counters = self.data.get("counters", {})
        return {
            "uploaded": counters.get(
                "uploaded", total_uploaded
            ),
            "duplicate": counters.get("duplicate", 0),
            "failed": counters.get("failed", total_failed),
            "total_in_immich": total_uploaded,
            "albums_done": len(
                self.data.get("albums_done", [])
            ),
            "users_with_uploads": len(
                self.data.get("syno_to_immich", {})
            ),
        }
