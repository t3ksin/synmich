"""Destination-local, per-item completion records for folder exports."""

import hashlib
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory


class BackupCheckpoint:
    """Commit each completed item without rewriting a growing JSON manifest.

    Only files recorded by this exporter are trusted. A file's existence alone
    cannot distinguish a complete photo from an interrupted or wrong download.
    """

    def __init__(self, destination):
        self.root = Path(destination).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / ".synmich-backup.sqlite3")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS completed (item_key TEXT PRIMARY KEY, files TEXT NOT NULL)"
        )
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def _key(self, session, item, folder):
        identity = {
            "server": session.syno.base_url.rstrip("/"),
            "account": session.name,
            "user_id": session.syno_user_id,
            "folder": str(folder.relative_to(self.root)),
            "item": {
                key: item.get(key)
                for key in (
                    "id",
                    "owner_user_id",
                    "filename",
                    "filesize",
                    "indexed_time",
                    "type",
                )
            },
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def _completed(self, key):
        row = self.db.execute("SELECT files FROM completed WHERE item_key = ?", (key,)).fetchone()
        if row is None:
            return None
        files = json.loads(row[0])
        for record in files:
            path = self.root / record["path"]
            try:
                stat = path.stat()
            except OSError:
                return None
            if not path.is_file() or (stat.st_size, stat.st_mtime_ns) != (
                record["size"],
                record["mtime_ns"],
            ):
                return None
        return self.root / files[0]["path"] if files else None

    def save_item(self, session, item, folder):
        """Return (saved path, reused); incomplete Live Photos stay retryable."""
        folder = Path(folder).resolve()
        owner_id = item.get("owner_user_id")
        if owner_id is not None and owner_id != session.syno_user_id:
            # Different personal libraries can contain identical IDs/names.
            folder = folder / "_contributors" / str(int(owner_id))
        key = self._key(session, item, folder)
        existing = self._completed(key)
        if existing is not None:
            return existing, True

        folder.mkdir(parents=True, exist_ok=True)
        # Keep partial files away from published output. A crash before the
        # completion commit results in a retry, never a false successful skip.
        with TemporaryDirectory(prefix=".synmich-part-", dir=folder) as staging:
            if item.get("type") == "live":
                files = session.syno.download_live_photo(item, Path(staging))
            else:
                files = (session.syno.download(item, Path(staging)),)
            if not all(path and path.is_file() and path.stat().st_size > 0 for path in files):
                return None, False
            expected_size = item.get("filesize")
            if (
                item.get("type") != "live"
                and isinstance(expected_size, int)
                and expected_size > 0
                and files[0].stat().st_size != expected_size
            ):
                return None, False
            records = []
            for path in files:
                target = folder / path.name
                path.replace(target)
                stat = target.stat()
                records.append(
                    {
                        "path": str(target.relative_to(self.root)),
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                )
            with self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO completed (item_key, files) VALUES (?, ?)",
                    (key, json.dumps(records)),
                )
            return self.root / records[0]["path"], False
