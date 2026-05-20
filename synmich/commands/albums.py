"""synmich albums — Manage Immich albums (v1.1.0).

Subcommands:
    list         List all albums (with filters)
    delete-empty Delete empty albums (with confirmation)
    show         Album details
"""

from __future__ import annotations

import json
import requests
import sys

from synmich.ui.cli_helpers import (
    console, info, success, warn, error, muted,
    section, table_albums, panel_summary,
    COLOR_PRIMARY, COLOR_OK, COLOR_WARN, COLOR_ERROR,
)


def _get_admin_key(config):
    """Return the first available admin API key."""
    for u in config.get("users", []):
        key = u.get("immich_api_key", "")
        if key:
            return key, u.get("name", "?")
    return None, None


def cmd_albums_list(args) -> int:
    """List the albums."""
    from synmich.config import load_config

    try:
        config = load_config()
    except Exception as e:
        error(f"Cannot load config: {e}")
        return 1

    immich_url = (
        config.get("immich", {}).get("url")
        or config.get("immich", {}).get("base_url", "")
    )
    key, _ = _get_admin_key(config)
    if not key:
        error("No Immich API key in config")
        return 1

    try:
        r = requests.get(
            f"{immich_url.rstrip('/')}/api/albums",
            headers={"x-api-key": key},
            timeout=30,
        )
        if r.status_code != 200:
            error(f"Cannot fetch albums (status {r.status_code})")
            return 1
        albums = r.json()
    except Exception as e:
        error(f"Cannot fetch albums: {e}")
        return 1

    # Filters
    filtered = albums
    if args.empty:
        filtered = [a for a in filtered if a.get("assetCount", 0) == 0]
    if args.shared:
        filtered = [a for a in filtered if a.get("shared")]
    if args.owner:
        filtered = [
            a for a in filtered
            if (a.get("owner", {}) or {}).get("name", "").lower() == args.owner.lower()
        ]
    if args.search:
        s = args.search.lower()
        filtered = [a for a in filtered if s in a.get("albumName", "").lower()]

    if args.json:
        print(json.dumps([{
            "id": a.get("id"),
            "name": a.get("albumName"),
            "owner": (a.get("owner", {}) or {}).get("name"),
            "items": a.get("assetCount", 0),
            "shared": a.get("shared", False),
        } for a in filtered], indent=2))
        return 0

    console.print()
    if not filtered:
        muted("  No albums match the filter")
        return 0

    # Sort
    filtered.sort(key=lambda a: a.get("albumName", "").lower())
    table_albums(filtered, title=f"Immich Albums ({len(filtered)})")

    # Summary
    console.print()
    empty_count = sum(1 for a in filtered if a.get("assetCount", 0) == 0)
    shared_count = sum(1 for a in filtered if a.get("shared"))
    muted(
        f"  {len(filtered)} albums shown · "
        f"{empty_count} empty · {shared_count} shared"
    )
    if len(albums) > len(filtered):
        muted(f"  ({len(albums) - len(filtered)} hidden by filters)")
    console.print()
    return 0


def cmd_albums_delete_empty(args) -> int:
    """Delete empty albums."""
    from synmich.config import load_config

    try:
        config = load_config()
    except Exception as e:
        error(f"Cannot load config: {e}")
        return 1

    immich_url = (
        config.get("immich", {}).get("url")
        or config.get("immich", {}).get("base_url", "")
    )
    key, _ = _get_admin_key(config)
    if not key:
        error("No Immich API key in config")
        return 1

    try:
        r = requests.get(
            f"{immich_url.rstrip('/')}/api/albums",
            headers={"x-api-key": key},
            timeout=30,
        )
        albums = r.json()
    except Exception as e:
        error(f"Cannot fetch albums: {e}")
        return 1

    empty = [a for a in albums if a.get("assetCount", 0) == 0]

    if not empty:
        success("No empty albums to delete")
        return 0

    console.print()
    warn(f"Found {len(empty)} empty albums:")
    for a in empty:
        muted(
            f"  - {a.get('albumName', '?')} "
            f"(owner: {(a.get('owner', {}) or {}).get('name', '?')})"
        )

    if not args.yes:
        confirm = input(f"\n  Delete all {len(empty)} empty albums? (yes/no): ").strip().lower()
        if confirm != "yes":
            muted("  Cancelled.")
            return 0

    console.print()
    deleted = 0
    failed = 0
    for a in empty:
        try:
            r = requests.delete(
                f"{immich_url.rstrip('/')}/api/albums/{a['id']}",
                headers={"x-api-key": key},
                timeout=10,
            )
            if r.status_code in (200, 204):
                success(f"Deleted: {a.get('albumName', '?')}")
                deleted += 1
            else:
                error(f"Failed: {a.get('albumName', '?')} (status {r.status_code})")
                failed += 1
        except Exception as e:
            error(f"Failed: {a.get('albumName', '?')} - {e}")
            failed += 1

    console.print()
    if failed:
        warn(f"Done: {deleted} deleted, {failed} failed")
        return 1
    else:
        success(f"Done: {deleted} albums deleted")
        return 0


def add_subcommands(subparsers):
    """Add the albums subcommands."""
    albums = subparsers.add_parser(
        "albums",
        help="Manage Immich albums",
    )
    al_sub = albums.add_subparsers(dest="album_action")

    list_p = al_sub.add_parser("list", help="List albums")
    list_p.add_argument("--empty", action="store_true", help="Only empty albums")
    list_p.add_argument("--shared", action="store_true", help="Only shared albums")
    list_p.add_argument("--owner", help="Filter by owner name")
    list_p.add_argument("--search", help="Search by album name")
    list_p.add_argument("--json", action="store_true", help="JSON output")
    list_p.set_defaults(func=cmd_albums_list)

    del_empty = al_sub.add_parser(
        "delete-empty",
        help="Delete all empty albums",
    )
    del_empty.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    del_empty.set_defaults(func=cmd_albums_delete_empty)
