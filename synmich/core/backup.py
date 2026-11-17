"""Resumable Synology folder exports, independent of the GUI."""

from pathlib import Path

from synmich.core.backup_checkpoint import BackupCheckpoint
from synmich.core.migrator import album_key, safe_name


def run_backup(
    sessions, selected, all_mode, owner_only, dest, stats, control, include_timeline=False
):
    stats.current_step = "backup"
    try:
        with BackupCheckpoint(dest) as checkpoint:
            _run_backup(
                sessions,
                selected,
                all_mode,
                owner_only,
                dest,
                stats,
                control,
                include_timeline,
                checkpoint,
            )
        stats.current_step = "done" if control.check() else "stopped"
    except Exception as exc:  # noqa: BLE001 - report background-worker errors to the GUI
        stats.failed += 1
        stats.log_message(f"Backup failed: {exc}")
        stats.current_step = "error"
    finally:
        for session in sessions:
            session.syno.close_downloads()


def _run_backup(
    sessions,
    selected,
    all_mode,
    owner_only,
    dest,
    stats,
    control,
    include_timeline=False,
    checkpoint=None,
):
    dest = Path(dest)
    seen, jobs = set(), []
    for s in sessions:
        try:
            albums = s.syno.list_albums()
        except Exception as e:  # noqa: BLE001
            stats.failed += 1
            stats.log_message(f"list albums {s.name}: {e}")
            continue
        for a in albums:
            k = album_key(s.name, a)
            if k in seen:
                continue
            seen.add(k)
            if all_mode or k in selected:
                jobs.append((s, a))

    # Albums count as work units; the full timeline (if enabled) adds one
    # extra unit per account, downloaded last into a "timeline" folder.
    stats.albums_total = len(jobs) + (len(sessions) if include_timeline else 0)
    if not jobs and not include_timeline:
        stats.log_message(
            "No album found for these accounts. Check the Synology address "
            "and that the account has access to Synology Photos albums."
        )
    for s, a in jobs:
        if not control.check():
            break
        name = a.get("name", "album")
        stats.current_album = name
        stats.log_message(f"Album: {name}")
        sharing = a.get("additional", {}).get("sharing_info", {}) or {}
        oid = sharing.get("owner", {}).get("id")
        owner_id = oid if (oid is not None and oid > 0) else a.get("owner_user_id")
        try:
            items = s.syno.list_items(album_id=a["id"])
        except Exception as e:  # noqa: BLE001
            stats.failed += 1
            stats.log_message(f"list items {name}: {e}")
            continue
        if owner_only:
            items = [it for it in items if it.get("owner_user_id") == owner_id]
        folder = dest / safe_name(s.name) / safe_name(name)
        stats.begin_items(len(items))
        for it in items:
            if not control.check():
                break
            try:
                fp, skipped = checkpoint.save_item(s, it, folder)
            except Exception as exc:  # noqa: BLE001
                stats.log_message(f"download {it.get('filename')}: {exc}")
                fp, skipped = None, False
            if fp:
                stats.skipped += int(skipped)
                stats.uploaded += int(not skipped)
            else:
                stats.failed += 1
                stats.log_message(f"failed: {it.get('filename')}")
            stats.items_done += 1
        if control.check():
            stats.albums_done += 1

    # Full timeline: every photo of each account (including those in no
    # album), saved under <destination>/<user>/timeline/. Done last.
    if include_timeline:
        for s in sessions:
            if not control.check():
                break
            stats.current_album = f"Timeline - {s.name}"
            stats.log_message(f"Timeline: {s.name}")
            try:
                items = s.syno.list_items()
            except Exception as e:  # noqa: BLE001
                stats.failed += 1
                stats.log_message(f"list timeline {s.name}: {e}")
                continue
            folder = dest / safe_name(s.name) / "timeline"
            stats.begin_items(len(items))
            for it in items:
                if not control.check():
                    break
                try:
                    fp, skipped = checkpoint.save_item(s, it, folder)
                except Exception as exc:  # noqa: BLE001
                    stats.log_message(f"download {it.get('filename')}: {exc}")
                    fp, skipped = None, False
                if fp:
                    stats.skipped += int(skipped)
                    stats.uploaded += int(not skipped)
                else:
                    stats.failed += 1
                    stats.log_message(f"failed: {it.get('filename')}")
                stats.items_done += 1
            if control.check():
                stats.albums_done += 1
