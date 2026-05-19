"""Migrator — orchestrateur de la migration."""

import logging
import re
import threading
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from synmich.core.synology import SynologyClient
from synmich.core.immich import ImmichClient
from synmich.core.checkpoint import Checkpoint

log = logging.getLogger("synmich")


@dataclass
class MigrationStats:
    """Real-time statistics."""

    uploaded: int = 0
    duplicate: int = 0
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
        self.shared_albums_mode = mig.get(
            "shared_albums_mode", "link"
        )
        if self.shared_albums_mode not in (
            "link",
            "duplicate",
            "ignore",
        ):
            self.shared_albums_mode = "link"

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
            self._log(
                f"  [DRY] Would download+upload "
                f"{item.get('filename')} (owner={uploader.name})"
            )
            self.stats.uploaded += 1
            return f"dry-run-{syno_id}", uploader.name

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
        owner_syno_id = sharing.get("owner", {}).get(
            "id"
        ) or album.get("owner_user_id")
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
                f"⚠ {name}: owner_syno_id="
                f"{owner_syno_id} not mapped"
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
        owner_syno_id = (
            sharing.get("owner", {}).get("id")
            or album.get("owner_user_id")
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
                self._log(
                    f"   ⚠ Share: user "
                    f"'{syno_name}' (db_id={db_id}) "
                    f"not mapped"
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
                except Exception:
                    asset_id, name = None, ""
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
                pp = (
                    a.get("passphrase")
                    or f"local-{session.name}-{a['id']}"
                )
                if pp in seen:
                    continue
                seen.add(pp)
                all_albums.append(a)

        self.stats.albums_total = len(all_albums)
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

    def run(self) -> None:
        """Run full migration based on config."""
        mig = self.config.get("migration", {})

        if mig.get("include_albums", True):
            self.run_albums()

        if (
            mig.get("include_timeline", True)
            and self.control.check()
        ):
            self.run_timeline()

        self.stats.current_step = "done"
        self.checkpoint.save()
