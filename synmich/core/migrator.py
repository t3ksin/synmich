"""Migrator — orchestrateur de la migration."""

import logging
import re
import threading
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from synmich.core.synology import SynologyClient
from synmich.core.immich import ImmichClient
from synmich.core.checkpoint import Checkpoint

log = logging.getLogger("synmich")

# Tolerance (seconds) when disambiguating same-named photos by capture date
# in external-library mode. Generous enough to absorb rounding / sub-second
# differences between Synology's capture time and Immich's dateTimeOriginal,
# tight enough that two genuinely different shots won't be confused.
_DATE_MATCH_TOLERANCE_S = 120

_ISO_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?"
)


def _iso_to_epoch(value: Optional[str]) -> Optional[float]:
    """Parse an Immich `dateTimeOriginal` into a UTC epoch.

    Hand-rolled rather than datetime.fromisoformat because Python 3.9/3.10
    reject offsets like `+00:00` combined with 2-digit fractional seconds
    (`...:48.41+00:00`), which is exactly the shape Immich returns.
    """
    if not value:
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    tz = m.group(8)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        tzinfo = timezone(sign * offset)
    else:
        tzinfo = timezone.utc
    try:
        return datetime(y, mo, d, hh, mm, ss, tzinfo=tzinfo).timestamp()
    except ValueError:
        return None


def match_existing_asset(
    index: Dict[str, List[Tuple]],
    filename: str,
    capture_epoch: Optional[float],
    owner_name: Optional[str] = None,
) -> Optional[str]:
    """Find an Immich asset already holding this Synology photo.

    `index` is ImmichClient.build_filename_index() output:
    {filename.lower(): [(asset_id, dateTimeOriginal, libraryId, originalPath), ...]}.
    Plain 2- and 3-tuples from older indexes/tests are also accepted.

    A single same-named asset is taken as the match (filename is the strong
    key — e.g. nino's `2025-09-18_12-54-48_IMG_6054.HEIC` prefix is unique).
    When several assets share the filename, we disambiguate by capture date
    and require a hit within _DATE_MATCH_TOLERANCE_S; if none qualifies we
    return None so the caller uploads rather than risk linking the wrong shot.

    When more than one asset qualifies — e.g. the photo exists both as an
    external-library asset and as a leftover copy in the upload library from
    an earlier run — the external one (`libraryId` set) is preferred, so we
    link to the media kept external rather than to a re-uploaded duplicate.

    If multiple external-library assets still qualify (same filename and
    capture date in more than one external library), prefer the one whose
    originalPath contains the current Synology user's name as a path segment.
    """
    candidates = index.get(filename.lower())
    if not candidates:
        return None

    # Normalise to (asset_id, dateTimeOriginal, library_id, original_path).
    # library_id is None for upload-library assets and set for external ones.
    norm = [
        (
            c[0],
            c[1] if len(c) > 1 else None,
            c[2] if len(c) > 2 else None,
            c[3] if len(c) > 3 else None,
        )
        for c in candidates
    ]

    if len(norm) == 1:
        return norm[0][0]

    # If exactly one external-library asset has this exact filename, prefer it
    # even when video metadata timestamps disagree. Some cameras/containers
    # expose video capture times in a different zone than Synology's album item
    # time; the exact filename is still stronger than leftover upload copies.
    external = [c for c in norm if c[2] is not None]
    if len(external) == 1:
        return external[0][0]

    if capture_epoch is None:
        return None

    owner = (owner_name or "").strip().lower()

    def owner_path_match(path: Optional[str]) -> bool:
        if not owner or not path:
            return False
        parts = [p.lower() for p in re.split(r"[\\/]+", str(path)) if p]
        return owner in parts

    # Keep every same-named asset whose capture date is within tolerance, then
    # prefer external assets. If date proximity ties, prefer the external path
    # that belongs to the current Synology user.
    qualifying = []  # (is_upload_copy, date_diff, not_owner_path, asset_id)
    for aid, dto, lib, path in norm:
        ep = _iso_to_epoch(dto)
        if ep is None:
            continue
        diff = abs(ep - capture_epoch)
        if diff <= _DATE_MATCH_TOLERANCE_S:
            qualifying.append(
                (lib is None, diff, not owner_path_match(path), aid)
            )
    if not qualifying:
        return None
    qualifying.sort(key=lambda q: (q[0], q[1], q[2]))
    return qualifying[0][3]


@dataclass
class MigrationStats:
    """Real-time statistics."""

    uploaded: int = 0
    duplicate: int = 0
    # External-library mode: photo already present in Immich (matched by
    # filename + capture date), so we linked the existing asset to the album
    # instead of re-uploading it.
    linked: int = 0
    failed: int = 0
    skipped: int = 0
    albums_done: int = 0
    albums_total: int = 0
    items_done: int = 0
    items_total: int = 0
    current_album: str = ""
    current_step: str = "starting"  # starting | albums | timeline | done
    last_messages: List[str] = field(default_factory=list)
    total_messages_logged: int = 0
    start_time: float = 0.0  # v1.0.3: set when migration actually begins

    def elapsed_seconds(self) -> float:
        """v1.0.3: elapsed time since migration start."""
        import time
        if self.start_time == 0.0:
            return 0.0
        return time.time() - self.start_time

    def eta_seconds(self) -> float:
        """v1.0.3: estimated time remaining in seconds."""
        if self.items_done == 0 or self.items_total == 0:
            return 0.0
        elapsed = self.elapsed_seconds()
        if elapsed < 1:
            return 0.0
        rate = self.items_done / elapsed
        if rate <= 0:
            return 0.0
        return (self.items_total - self.items_done) / rate

    def rate_per_minute(self) -> float:
        """v1.0.3: current processing rate in items per minute."""
        elapsed = self.elapsed_seconds()
        if elapsed < 1:
            return 0.0
        return self.items_done / elapsed * 60

    def log_message(self, msg: str) -> None:
        self.last_messages.append(msg)
        self.total_messages_logged += 1
        if len(self.last_messages) > 100:
            self.last_messages = self.last_messages[-100:]


@dataclass
class MigrationControl:
    """Live control (pause / stop)."""

    pause_event: threading.Event = field(
        default_factory=threading.Event
    )
    stop_requested: bool = False

    def __post_init__(self):
        self.pause_event.set()  # set = NOT paused

    def pause(self) -> None:
        self.pause_event.clear()

    def resume(self) -> None:
        self.pause_event.set()

    def is_paused(self) -> bool:
        return not self.pause_event.is_set()

    def stop(self) -> None:
        self.stop_requested = True
        self.pause_event.set()  # release paused threads

    def check(self) -> bool:
        """Block if paused, return False if stop requested."""
        self.pause_event.wait()
        return not self.stop_requested


@dataclass
class UserSession:
    """Session pour un user."""

    name: str
    syno: SynologyClient
    immich: ImmichClient
    syno_user_id: int
    immich_user_id: str
    output_dir_name: str = ""


def safe_name(name: str) -> str:
    bad = r'\\/:*?"<>|'
    cleaned = "".join(
        c
        for c in name
        if c not in bad
        and (c.isprintable() or c.isspace())
    ).strip()
    return cleaned[:200] if cleaned else "unnamed"


def album_key(owner_name: str, album: Dict[str, Any]) -> str:
    """Stable key identifying an album for selection and dedup.

    Uses the real `passphrase` when it exists (shared albums: stable and
    identical on the owner and recipient sides), otherwise a local key
    `local-<owner>-<id>` for personal, non-shared albums.

    The selector (ui.album_selector) and run_albums MUST use this same
    function, otherwise the keys saved in selected_albums would not match
    the ones tested at migration time.
    """
    return album.get("passphrase") or f"local-{owner_name}-{album['id']}"


class Migrator:
    """Orchestrateur de migration."""

    def __init__(
        self,
        config: Dict[str, Any],
        sessions: List[UserSession],
        checkpoint: Checkpoint,
        stats: MigrationStats,
        control: MigrationControl,
        dry_run: bool = False,
    ):
        self.config = config
        self.sessions = sessions
        self.checkpoint = checkpoint
        self.stats = stats
        self.control = control
        self.dry_run = dry_run

        self.sessions_by_name: Dict[str, UserSession] = {
            s.name: s for s in sessions
        }
        self.syno_id_to_session: Dict[int, UserSession] = {
            s.syno_user_id: s for s in sessions
        }

        mig = config.get("migration", {})

        # Shared Space owner
        owner_name = mig.get("shared_space_owner", "")
        self.shared_owner: Optional[UserSession] = (
            self.sessions_by_name.get(owner_name)
            or (sessions[0] if sessions else None)
        )

        # Shared albums mode: link | duplicate | ignore
        # (the "how", for SHARED albums only)
        self.shared_albums_mode = mig.get(
            "shared_albums_mode", "link"
        )
        if self.shared_albums_mode not in (
            "link",
            "duplicate",
            "ignore",
        ):
            self.shared_albums_mode = "link"

        # Albums mode: all | select  (the "what": which albums to migrate)
        # Independent axis from shared_albums_mode. In select mode, only the
        # albums whose key (see album_key) is in selected_albums are
        # migrated; the include/exclude regex is then ignored (the
        # interactive selection wins).
        self.albums_mode = mig.get("albums_mode", "all")
        if self.albums_mode not in ("all", "select"):
            self.albums_mode = "all"
        self.selected_albums = set(
            mig.get("selected_albums", []) or []
        )

        self.include_shared_space = bool(
            mig.get("include_shared_space", True)
        )

        # Parallel mode
        exec_cfg = config.get("execution", {})
        if exec_cfg.get("mode") == "sequential":
            self.workers = 1
        else:
            self.workers = max(
                1, int(exec_cfg.get("workers", 4))
            )

        self.delete_after = bool(
            exec_cfg.get("delete_after_upload", True)
        )

        # External-library mode (v2.2.0). When the photos already live in
        # Immich via an *external library*, re-uploading them creates a second
        # copy in the upload library — Immich's content-checksum dedup can't
        # catch it because external assets carry a dummy path-based checksum
        # (immich-app/immich#7804). In this mode we instead match each Synology
        # photo to the existing asset by filename + capture date and just add
        # that asset to the album, downloading nothing. If no match is found we
        # fall back to a normal upload so a photo is never silently dropped.
        self.external_library_mode = bool(
            mig.get("external_library_mode", False)
        )
        # Lazily-built filename index per uploader (keyed by uploader name);
        # each Immich user sees a different set of assets, so indexes aren't
        # shared. Guarded because uploads run on a thread pool.
        self._asset_index: Dict[
            str, Dict[str, List[Tuple[str, Optional[str], Optional[str]]]]
        ] = {}
        self._asset_index_lock = threading.Lock()
        # Per-(uploader, filename) cache for the targeted fallback lookup we
        # run when the bulk index misses a name (the bulk scan can drop assets
        # at page boundaries). Caches negatives too, so a genuinely-absent
        # file is queried at most once.
        self._fallback_cache: Dict[
            Tuple[str, str], List[Tuple[str, Optional[str], Optional[str]]]
        ] = {}
        self._fallback_lock = threading.Lock()

        # Filters
        filters = config.get("filters", {})
        self.include_re = self._compile_re(
            filters.get("include_albums_regex", "")
        )
        self.exclude_re = self._compile_re(
            filters.get("exclude_albums_regex", "")
        )
        self.include_videos = bool(
            filters.get("include_videos", True)
        )

        # Work dir
        self.work_dir = Path(
            config.get("paths", {}).get(
                "work_dir", "./synmich_backup"
            )
        )

        # Defaults
        for s in self.sessions:
            s.output_dir_name = safe_name(s.name).lower()

    @staticmethod
    def _compile_re(pattern: str):
        if not pattern:
            return None
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error:
            return None

    def _log(self, msg: str) -> None:
        log.info(msg)
        self.stats.log_message(msg)

    def _filter_album(self, name: str) -> bool:
        # In select mode the selection (applied in run_albums) wins:
        # we don't additionally apply the include/exclude regex.
        if self.albums_mode == "select":
            return True
        if (
            self.exclude_re
            and self.exclude_re.search(name)
        ):
            return False
        if self.include_re and not self.include_re.search(
            name
        ):
            return False
        return True

    def _determine_uploader(
        self, owner_user_id: int
    ) -> Optional[UserSession]:
        if owner_user_id == 0:
            return self.shared_owner
        return self.syno_id_to_session.get(owner_user_id)

    def _get_asset_index(
        self, uploader: UserSession
    ) -> Dict[str, List[Tuple[str, Optional[str], Optional[str]]]]:
        """Return (building once) the filename index for an uploader.

        Built lazily and cached per uploader. The build is done under a lock
        so that, when the worker pool first hits external-library mode, we
        scan each user's library once instead of N times in parallel.
        """
        with self._asset_index_lock:
            idx = self._asset_index.get(uploader.name)
            if idx is not None:
                return idx
            self._log(
                f"🔎 Indexing existing Immich assets for "
                f"{uploader.name} (external-library mode)…"
            )
            try:
                idx = uploader.immich.build_filename_index()
            except Exception as e:
                self._log(
                    f"⚠ Could not index Immich assets for "
                    f"{uploader.name}: {e} — will upload instead"
                )
                idx = {}
            self._asset_index[uploader.name] = idx
            total = sum(len(v) for v in idx.values())
            self._log(
                f"   {total} existing asset(s) across "
                f"{len(idx)} filename(s)"
            )
            return idx

    def _lookup_by_filename(
        self, uploader: UserSession, filename: str
    ) -> List[Tuple[str, Optional[str], Optional[str], Optional[str]]]:
        """Targeted exact-name lookup, used when the bulk index misses.

        Result (including the empty list) is cached per (uploader, filename)
        so a name is queried against Immich at most once per run.
        """
        if not filename:
            return []
        key = (uploader.name, filename.lower())
        with self._fallback_lock:
            cached = self._fallback_cache.get(key)
        if cached is not None:
            return cached
        try:
            candidates = uploader.immich.find_assets_by_filename(
                filename
            )
        except Exception as e:
            log.exception(
                "Fallback lookup failed for %r", filename
            )
            self._log(
                f"⚠ Fallback lookup failed for {filename}: {e}"
            )
            candidates = []
        with self._fallback_lock:
            self._fallback_cache[key] = candidates
        return candidates

    def _process_one_asset(
        self,
        item: Dict[str, Any],
        folder: Path,
        uploader: UserSession,
    ) -> Tuple[Optional[str], str]:
        """Returns (immich_asset_id or None, uploader_name)."""

        if not self.control.check():
            return None, uploader.name

        syno_id = str(item["id"])

        # Already uploaded?
        existing = self.checkpoint.is_uploaded(
            uploader.name, syno_id
        )
        if existing:
            return existing, uploader.name

        # Video filter — note that "live" type is an iPhone Live Photo
        # (HEIC photo + small associated video), NOT a regular video.
        # We only filter actual "video" type.
        if not self.include_videos and item.get("type") == "video":
            self._log(
                f"⏭ Video skipped (include_videos=false): "
                f"{item.get('filename')}"
            )
            return None, uploader.name

        # Dry-run: just log what would be done
        if self.dry_run:
            verb = (
                "link-or-upload"
                if self.external_library_mode
                else "download+upload"
            )
            self._log(
                f"  [DRY] Would {verb} "
                f"{item.get('filename')} (owner={uploader.name})"
            )
            self.stats.uploaded += 1
            return f"dry-run-{syno_id}", uploader.name

        # External-library mode: if the photo already exists in Immich (it's
        # served from an external library), link that asset to the album
        # instead of downloading and re-uploading a duplicate copy.
        if self.external_library_mode:
            index = self._get_asset_index(uploader)
            filename = item.get("filename", "")
            capture = item.get("time")
            existing_id = match_existing_asset(
                index, filename, capture, owner_name=uploader.name
            )
            if existing_id is None:
                # Bulk index miss isn't proof the asset is absent — the
                # full-library scan can drop rows at page boundaries. Confirm
                # with a targeted exact-name query before deciding to upload a
                # duplicate.
                candidates = self._lookup_by_filename(
                    uploader, filename
                )
                if candidates:
                    existing_id = match_existing_asset(
                        {filename.lower(): candidates},
                        filename,
                        capture,
                        owner_name=uploader.name,
                    )
            if existing_id:
                self.checkpoint.mark_linked(
                    uploader.name, syno_id, existing_id
                )
                self.stats.linked += 1
                self._log(f"🔗 Linked (external): {filename}")
                return existing_id, uploader.name
            # No match → fall through to a normal upload so the photo is
            # never silently missing from the migrated album.
            self._log(
                f"↑ No external match for {filename} — "
                f"uploading"
            )

        # Download
        if not self.control.check():
            return None, uploader.name

        filepath = uploader.syno.download(item, folder)
        if not filepath:
            self.checkpoint.mark_failed(
                uploader.name, syno_id
            )
            return None, uploader.name

        # Check size limit
        max_mb = (
            self.config.get("filters", {})
            .get("max_file_size_mb", 0)
        )
        if max_mb and filepath.stat().st_size > (
            max_mb * 1024 * 1024
        ):
            try:
                filepath.unlink()
            except Exception:
                pass
            return None, uploader.name

        # Upload
        if not self.control.check():
            return None, uploader.name

        asset_id, was_dup, err = uploader.immich.upload_asset(
            filepath,
            device_id=f"synology-{uploader.name}",
            device_asset_id=(
                f"{uploader.name}_{item['filename']}_"
                f"{filepath.stat().st_size}"
            ),
            file_created_at=item.get("time"),
            original_filename=item["filename"],
        )

        if self.delete_after and asset_id:
            try:
                filepath.unlink()
            except Exception:
                pass

        if asset_id:
            self.checkpoint.mark_uploaded(
                uploader.name, syno_id, asset_id,
                was_duplicate=was_dup,
            )
            if was_dup:
                self.stats.duplicate += 1
            else:
                self.stats.uploaded += 1
        else:
            self.checkpoint.mark_failed(
                uploader.name, syno_id
            )
            self.stats.failed += 1
            if err:
                self._log(
                    f"✖ {item.get('filename')}: {err}"
                )

        return asset_id, uploader.name

    def _process_album(
        self, album: Dict[str, Any]
    ) -> None:
        """Migrate a single album."""

        if not self.control.check():
            return

        name = album["name"]
        passphrase = (
            album.get("passphrase")
            or f"local-{album['id']}"
        )

        # Filters
        if not self._filter_album(name):
            self._log(f"⏭ Filtered: {name}")
            return

        # Already done?
        if self.checkpoint.is_album_done(passphrase):
            self._log(f"⏭ Already done: {name}")
            self.stats.albums_done += 1
            return

        # Determine real owner
        sharing = (
            album.get("additional", {}).get(
                "sharing_info", {}
            )
            or {}
        )
        # v1.0.3: Synology returns sharing.owner.id=-1 for non-shared
        # personal albums of non-admin users. Fall back to album.owner_user_id
        # whenever sharing.owner.id is missing OR <= 0 (invalid).
        _shared_oid = sharing.get("owner", {}).get("id")
        owner_syno_id = (
            _shared_oid
            if _shared_oid is not None and _shared_oid > 0
            else album.get("owner_user_id")
        )
        is_shared = bool(album.get("shared")) or bool(
            sharing.get("permission")
        )

        # Shared albums handling based on mode
        if is_shared:
            if self.shared_albums_mode == "ignore":
                self._log(
                    f"⏭ Shared album ignored "
                    f"(mode=ignore): {name}"
                )
                self.checkpoint.mark_album_done(passphrase)
                self.stats.albums_done += 1
                return
            if self.shared_albums_mode == "duplicate":
                # Each user who can see this shared album gets
                # their own separate copy, containing only the
                # photos they own.
                self._process_album_duplicate(
                    album, name, passphrase, sharing
                )
                return
            # else: link mode (default) - falls through

        if owner_syno_id == 0:
            owner = self.shared_owner
        else:
            owner = self.syno_id_to_session.get(
                owner_syno_id
            )

        if not owner:
            self._log(
                f"⚠ Skipping album \"{name}\": its owner (Synology user "
                f"id {owner_syno_id}) isn't part of this migration. "
                f"Add that user to your config to migrate this album."
            )
            return

        self.stats.current_album = name
        self._log(f"📂 Album: {name} (owner: {owner.name})")

        # Dry-run: skip Immich operations
        if self.dry_run:
            try:
                items = owner.syno.list_items(
                    album_id=album["id"]
                )
            except Exception as e:
                self._log(f"✖ List items '{name}': {e}")
                return
            self._log(
                f"  [DRY] Would create album with "
                f"{len(items)} items, share with "
                f"{len(sharing.get('permission', []))} users"
            )
            self.stats.items_total = len(items)
            self.stats.items_done = len(items)
            self.checkpoint.mark_album_done(passphrase)
            self.stats.albums_done += 1
            return

        # Create album in Immich
        try:
            immich_album_id = (
                owner.immich.create_album(name)
            )
        except Exception as e:
            self._log(f"✖ Create album '{name}': {e}")
            return

        # Share per Syno permissions (only in link mode)
        if is_shared and self.shared_albums_mode == "link":
            self._share_album(
                owner,
                immich_album_id,
                sharing.get("permission", []),
            )

        # List items
        try:
            items = owner.syno.list_items(
                album_id=album["id"]
            )
        except Exception as e:
            self._log(f"✖ List items '{name}': {e}")
            return

        if not items:
            self.checkpoint.mark_album_done(passphrase)
            self.checkpoint.save()
            self.stats.albums_done += 1
            return

        # Process items (parallel or sequential)
        uploaded_by_uploader: Dict[str, List[str]] = {}
        folder = (
            self.work_dir
            / owner.output_dir_name
            / safe_name(name)
        )

        self.stats.items_total = len(items)
        self.stats.items_done = 0

        if self.workers <= 1:
            self._process_items_sequential(
                items, folder, uploaded_by_uploader
            )
        else:
            self._process_items_parallel(
                items, folder, uploaded_by_uploader
            )

        if not self.control.check():
            self.checkpoint.save()
            return

        # Add to album per uploader (with their own API key).
        # v1.0.2: if a user's API key gets `no_permission` on some
        # assets (race condition in parallel attribution), retry the
        # failed adds using the album OWNER's key. The owner has full
        # admin rights on the shared album and can add any visible asset.
        for uploader_name, ids in uploaded_by_uploader.items():
            if not ids:
                continue
            uploader = self.sessions_by_name.get(
                uploader_name
            )
            if not uploader:
                continue
            ok, fail = uploader.immich.add_assets_to_album(
                immich_album_id, ids
            )
            # v1.0.2: retry with the album owner key if some assets
            # were rejected. This is a workaround for the parallel-
            # upload race condition where assets occasionally end up
            # attributed to the "wrong" owner under heavy load.
            if fail > 0 and uploader.name != owner.name:
                retry_ok, retry_fail = (
                    owner.immich.add_assets_to_album(
                        immich_album_id, ids
                    )
                )
                if retry_ok > 0:
                    self._log(
                        f"   {uploader_name}: {ok} added, "
                        f"{retry_ok} recovered via owner retry"
                        + (
                            f", {retry_fail} failed"
                            if retry_fail
                            else ""
                        )
                    )
                    ok += retry_ok
                    fail = retry_fail
                else:
                    self._log(
                        f"   {uploader_name}: {ok} added"
                        + (f", {fail} failed" if fail else "")
                    )
            else:
                self._log(
                    f"   {uploader_name}: {ok} added"
                    + (f", {fail} failed" if fail else "")
                )

        self.checkpoint.mark_album_done(passphrase)
        self.checkpoint.save()
        self.stats.albums_done += 1

    def _process_album_duplicate(
        self,
        album: Dict[str, Any],
        name: str,
        passphrase: str,
        sharing: Dict[str, Any],
    ) -> None:
        """Create separate album copies, one per user that
        can see this shared album. Each user only gets the
        photos they own."""
        self.stats.current_album = name
        self._log(
            f"📂 Album (duplicate mode): {name}"
        )

        # Identify which users can see this album
        # v1.0.3: same fix as above for the second occurrence.
        _shared_oid = sharing.get("owner", {}).get("id")
        owner_syno_id = (
            _shared_oid
            if _shared_oid is not None and _shared_oid > 0
            else album.get("owner_user_id")
        )
        visible_user_ids = {owner_syno_id} if owner_syno_id else set()
        for p in sharing.get("permission", []) or []:
            uid = p.get("db_id")
            if uid is not None:
                visible_user_ids.add(uid)

        # Choose an owner to list items (any owner that can see)
        list_owner = self.syno_id_to_session.get(owner_syno_id)
        if not list_owner and owner_syno_id == 0:
            list_owner = self.shared_owner
        if not list_owner:
            self._log(
                f"⚠ {name}: no session to list items"
            )
            return

        if self.dry_run:
            try:
                items = list_owner.syno.list_items(
                    album_id=album["id"]
                )
            except Exception as e:
                self._log(f"✖ List items '{name}': {e}")
                return
            for user_id in visible_user_ids:
                user_items = [
                    it for it in items
                    if it.get("owner_user_id") == user_id
                ]
                user_session = (
                    self.syno_id_to_session.get(user_id)
                    or (self.shared_owner if user_id == 0 else None)
                )
                if user_session:
                    self._log(
                        f"  [DRY] Would create album "
                        f"'{name}' for {user_session.name} "
                        f"with {len(user_items)} items"
                    )
            self.checkpoint.mark_album_done(passphrase)
            self.stats.albums_done += 1
            return

        # List items once
        try:
            items = list_owner.syno.list_items(
                album_id=album["id"]
            )
        except Exception as e:
            self._log(f"✖ List items '{name}': {e}")
            return

        # For each visible user, create their own album
        # with only their own photos
        for user_id in visible_user_ids:
            user_session = (
                self.syno_id_to_session.get(user_id)
                or (self.shared_owner if user_id == 0 else None)
            )
            if not user_session:
                continue

            user_items = [
                it for it in items
                if it.get("owner_user_id") == user_id
            ]
            if not user_items:
                continue

            try:
                user_album_id = (
                    user_session.immich.create_album(name)
                )
            except Exception as e:
                self._log(
                    f"✖ Create album '{name}' for "
                    f"{user_session.name}: {e}"
                )
                continue

            self._log(
                f"   📂 {user_session.name}: "
                f"{len(user_items)} items"
            )

            uploaded_by_uploader: Dict[str, List[str]] = {}
            folder = (
                self.work_dir
                / user_session.output_dir_name
                / safe_name(name)
            )

            self.stats.items_total = len(user_items)
            self.stats.items_done = 0

            if self.workers <= 1:
                self._process_items_sequential(
                    user_items, folder, uploaded_by_uploader
                )
            else:
                self._process_items_parallel(
                    user_items, folder, uploaded_by_uploader
                )

            if not self.control.check():
                self.checkpoint.save()
                return

            ids = uploaded_by_uploader.get(
                user_session.name, []
            )
            if ids:
                ok, fail = (
                    user_session.immich.add_assets_to_album(
                        user_album_id, ids
                    )
                )
                self._log(
                    f"     ✓ {ok} added"
                    + (f", {fail} failed" if fail else "")
                )

        self.checkpoint.mark_album_done(passphrase)
        self.checkpoint.save()
        self.stats.albums_done += 1

    def _share_album(
        self,
        owner: UserSession,
        album_id: str,
        permissions: List[Dict[str, Any]],
    ) -> None:
        """Share an album with the listed users."""

        default_role = self.config.get(
            "migration", {}
        ).get("share_role", "editor")

        # Map Synology db_id → user
        # Note: Syno db_id != syno_user_id Photos.
        # Try by db_id, fallback by name.
        for p in permissions:
            db_id = p.get("db_id")
            syno_name = p.get("name")
            role_syno = p.get("role", "view")
            role_immich = (
                "editor"
                if role_syno == "upload"
                else default_role
            )

            target: Optional[UserSession] = None

            # 1) Match by db_id (sometimes = syno_user_id)
            if db_id is not None:
                target = self.syno_id_to_session.get(db_id)

            # 2) Match by name
            if not target and syno_name:
                for s in self.sessions:
                    if s.name.lower() == syno_name.lower():
                        target = s
                        break

            if not target:
                who = syno_name or f"Synology user (db_id={db_id})"
                self._log(
                    f"   ⚠ Shared on Synology with \"{who}\", who isn't "
                    f"part of this migration — the album won't be shared "
                    f"with them in Immich. Add them as a user in your "
                    f"config to replicate the share."
                )
                continue

            ok = owner.immich.share_album(
                album_id,
                target.immich_user_id,
                role=role_immich,
            )
            if ok:
                self._log(
                    f"   🤝 Shared with {target.name} "
                    f"({role_immich})"
                )

    def _process_items_sequential(
        self,
        items: List[Dict[str, Any]],
        folder: Path,
        uploaded_by_uploader: Dict[str, List[str]],
    ) -> None:
        for item in items:
            if not self.control.check():
                return
            uploader = self._determine_uploader(
                item.get("owner_user_id")
            )
            if not uploader:
                continue
            asset_id, name = self._process_one_asset(
                item, folder, uploader
            )
            if asset_id:
                uploaded_by_uploader.setdefault(
                    name, []
                ).append(asset_id)
            self.stats.items_done += 1
            if self.stats.items_done % 25 == 0:
                self.checkpoint.save()

    def _process_items_parallel(
        self,
        items: List[Dict[str, Any]],
        folder: Path,
        uploaded_by_uploader: Dict[str, List[str]],
    ) -> None:
        with ThreadPoolExecutor(
            max_workers=self.workers
        ) as ex:
            futures = {}
            for item in items:
                if not self.control.check():
                    break
                uploader = self._determine_uploader(
                    item.get("owner_user_id")
                )
                if not uploader:
                    continue
                fut = ex.submit(
                    self._process_one_asset,
                    item,
                    folder,
                    uploader,
                )
                futures[fut] = item

            for fut in as_completed(futures):
                try:
                    asset_id, name = fut.result()
                except Exception as e:
                    # Don't swallow this silently anymore: an exception here
                    # (e.g. a checkpoint API mismatch) used to surface as
                    # "0 uploaded, 0 failed" while assets were actually being
                    # sent to Immich. Log it and mark the failure.
                    asset_id, name = None, ""
                    item = futures[fut]
                    self._log(
                        f"✖ {item.get('filename')}: {e}"
                    )
                    self.stats.failed += 1
                if asset_id:
                    uploaded_by_uploader.setdefault(
                        name, []
                    ).append(asset_id)
                self.stats.items_done += 1
                if self.stats.items_done % 25 == 0:
                    self.checkpoint.save()

    def run_albums(self) -> None:
        """Migrate all albums."""

        self.stats.current_step = "albums"

        # Collect unique albums by passphrase
        seen = set()
        all_albums = []
        excluded_shared = 0  # shared albums not selected (select mode)
        timeline_off = not self.config.get("migration", {}).get(
            "include_timeline", True
        )
        for session in self.sessions:
            try:
                albums = session.syno.list_albums()
            except Exception as e:
                self._log(
                    f"✖ list_albums {session.name}: {e}"
                )
                continue
            self._log(
                f"📚 {session.name}: {len(albums)} albums"
            )
            for a in albums:
                pp = album_key(session.name, a)
                if pp in seen:
                    continue
                seen.add(pp)
                # Select mode: keep only the chosen albums.
                if (
                    self.albums_mode == "select"
                    and pp not in self.selected_albums
                ):
                    # A SHARED album not selected + timeline OFF => some
                    # contributor photos won't be migrated anywhere. Count
                    # them for a single summary line (see below).
                    if timeline_off:
                        sharing = (
                            a.get("additional", {}).get(
                                "sharing_info", {}
                            )
                            or {}
                        )
                        if bool(a.get("shared")) or bool(
                            sharing.get("permission")
                        ):
                            excluded_shared += 1
                    continue
                all_albums.append(a)

        self.stats.albums_total = len(all_albums)
        if self.albums_mode == "select":
            self._log(
                f"📚 Select mode: {len(all_albums)} album(s) "
                f"selected to migrate"
            )
            if excluded_shared:
                self._log(
                    f"⚠ {excluded_shared} shared album(s) not selected: "
                    f"their photos will not be migrated "
                    f"(timeline disabled)"
                )
        else:
            self._log(
                f"📚 Unique albums total: {len(all_albums)}"
            )

        for album in all_albums:
            if not self.control.check():
                break
            try:
                self._process_album(album)
            except Exception as e:
                self._log(
                    f"✖ Album '{album.get('name')}': {e}"
                )

        self.checkpoint.save()

    def run_timeline(self) -> None:
        """Migrate the timeline of each user."""

        self.stats.current_step = "timeline"

        for session in self.sessions:
            if not self.control.check():
                break

            if self.checkpoint.is_timeline_done(
                session.name
            ):
                self._log(
                    f"⏭ Timeline {session.name} already done"
                )
                continue

            self.stats.current_album = (
                f"Timeline — {session.name}"
            )
            self._log(
                f"🕐 Timeline {session.name}..."
            )

            try:
                items = session.syno.list_items()
            except Exception as e:
                self._log(
                    f"✖ Timeline {session.name}: {e}"
                )
                continue

            self.stats.items_total = len(items)
            self.stats.items_done = 0
            self._log(
                f"   📸 {len(items)} items"
            )

            folder = (
                self.work_dir
                / session.output_dir_name
                / "_timeline"
            )

            uploaded_by_uploader: Dict[
                str, List[str]
            ] = {}

            if self.workers <= 1:
                self._process_items_sequential(
                    items, folder, uploaded_by_uploader
                )
            else:
                self._process_items_parallel(
                    items, folder, uploaded_by_uploader
                )

            if not self.control.check():
                self.checkpoint.save()
                return

            self.checkpoint.mark_timeline_done(
                session.name
            )
            self.checkpoint.save()

    def _start_keepalives(self):
        """Keep each user's Synology session alive for the whole migration.

        A Synology SID expires after ~60 min idle or ~6 h max lifetime. For
        long runs, a background thread per user pings every 30 min and, if the
        session has expired, silently re-logs in via the saved device token.
        Returns the started keepalives so run() can stop them at the end."""
        from synmich.core.synology_keepalive import SynologyKeepalive

        creds: Dict[str, Any] = {}
        for u in self.config.get("users", []):
            pair = (u.get("syno_username", ""), u.get("syno_password", ""))
            for key in (u.get("name"), u.get("syno_username")):
                if key:
                    creds[key] = pair

        keepalives = []
        for s in self.sessions:
            user, pw = creds.get(s.name, ("", ""))
            if not user or not pw:
                continue
            try:
                ka = SynologyKeepalive(
                    client=s.syno, username=user, password=pw,
                    ping_interval_seconds=1800)
                ka.start()
                keepalives.append(ka)
            except Exception:  # noqa: BLE001
                pass
        return keepalives

    def _stop_keepalives(self, keepalives) -> None:
        for ka in keepalives:
            try:
                ka.stop()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        """Run full migration based on config."""
        mig = self.config.get("migration", {})
        keepalives = self._start_keepalives()
        try:
            if mig.get("include_albums", True):
                self.run_albums()

            if (
                mig.get("include_timeline", True)
                and self.control.check()
            ):
                self.run_timeline()

            self.stats.current_step = "done"
            self.checkpoint.save()
        finally:
            self._stop_keepalives(keepalives)
