"""synmich stats — Detailed statistics of the Immich state (v1.1.0)."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import requests

from synmich.ui.cli_helpers import (
    console, info, success, warn, error,
    section, table_stats, panel_summary,
    COLOR_PRIMARY, COLOR_OK, COLOR_MUTED,
)


def cmd_stats(args) -> int:
    """Display the Immich + checkpoint stats."""
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
    users = config.get("users", [])

    if args.json:
        return _stats_json(config)

    console.print()
    section("Immich statistics")
    console.print()

    # Server stats
    try:
        first_key = next(
            u.get("immich_api_key", "") for u in users if u.get("immich_api_key")
        )
    except StopIteration:
        error("No API key available in config")
        return 1

    try:
        r = requests.get(
            f"{immich_url.rstrip('/')}/api/server/statistics",
            headers={"x-api-key": first_key},
            timeout=15,
        )
        if r.status_code != 200:
            warn(f"Cannot get server stats (status {r.status_code})")
            warn("Note: stats endpoint requires admin permissions")
            stats_data = None
        else:
            stats_data = r.json()
    except Exception as e:
        warn(f"Could not fetch server stats: {e}")
        stats_data = None

    if stats_data:
        total_photos = 0
        total_videos = 0
        per_user = {}
        for u in stats_data.get("usageByUser", []):
            name = u.get("userName", "?")
            photos = u.get("photos", 0)
            videos = u.get("videos", 0)
            per_user[name] = {
                "photos": photos,
                "videos": videos,
                "usage_bytes": u.get("usage", 0),
                "total": photos + videos,
            }
            total_photos += photos
            total_videos += videos

        usage_bytes = stats_data.get("usage", 0)
        usage_gb = usage_bytes / (1024 ** 3)

        items = [
            ("Total photos", f"{total_photos:,}"),
            ("Total videos", f"{total_videos:,}"),
            ("Total items", f"{total_photos + total_videos:,}"),
            ("Storage used", f"{usage_gb:.1f} GB"),
        ]
        panel_summary("Server totals", items, color=COLOR_PRIMARY)

        if per_user:
            console.print()
            console.print(f"  [bold {COLOR_PRIMARY}]Per user[/]")
            for name, data in per_user.items():
                gb = data["usage_bytes"] / (1024 ** 3)
                console.print(
                    f"    [bold]{name}:[/] "
                    f"{data['photos']:,} photos · "
                    f"{data['videos']:,} videos · "
                    f"{gb:.1f} GB"
                )

    # Album stats
    try:
        r = requests.get(
            f"{immich_url.rstrip('/')}/api/albums",
            headers={"x-api-key": first_key},
            timeout=15,
        )
        if r.status_code == 200:
            albums = r.json()
            shared = [a for a in albums if a.get("shared")]
            empty = [a for a in albums if a.get("assetCount", 0) == 0]

            items = [
                ("Total albums", f"{len(albums):,}"),
                ("Shared albums", f"{len(shared):,}"),
                ("Empty albums", f"{len(empty):,}"),
            ]
            console.print()
            panel_summary("Albums", items, color=COLOR_PRIMARY)
    except Exception:
        pass

    # Checkpoint stats
    try:
        from synmich.core.checkpoint import Checkpoint
        cp = Checkpoint(config=config)
        summary = cp.get_summary()

        items = [
            ("Uploaded", f"{summary['uploaded']:,}"),
            ("Duplicates", f"{summary['duplicate']:,}"),
        ]
        if summary.get("linked"):
            items.append(("Linked (external)", f"{summary['linked']:,}"))
        items += [
            ("Failed", f"{summary['failed']:,}"),
            ("Albums done", f"{summary['albums_done']:,}"),
        ]
        console.print()
        panel_summary("Migration checkpoint", items, color=COLOR_OK)

        if summary["items_per_user"]:
            console.print(f"\n  [bold {COLOR_PRIMARY}]Items per user[/]")
            for u, n in summary["items_per_user"].items():
                console.print(f"    [bold]{u}:[/] {n:,} items mapped")
    except Exception as e:
        warn(f"Could not load checkpoint stats: {e}")

    console.print()
    return 0


def _stats_json(config: Dict[str, Any]) -> int:
    """JSON output for use in scripts."""
    immich_url = (
        config.get("immich", {}).get("url")
        or config.get("immich", {}).get("base_url", "")
    )
    users = config.get("users", [])

    out = {
        "immich_url": immich_url,
        "users": [u.get("name") for u in users],
        "server_stats": None,
        "albums": {},
        "checkpoint": None,
    }

    try:
        first_key = next(
            u.get("immich_api_key", "") for u in users if u.get("immich_api_key")
        )
        r = requests.get(
            f"{immich_url.rstrip('/')}/api/server/statistics",
            headers={"x-api-key": first_key}, timeout=15,
        )
        if r.status_code == 200:
            out["server_stats"] = r.json()

        r = requests.get(
            f"{immich_url.rstrip('/')}/api/albums",
            headers={"x-api-key": first_key}, timeout=15,
        )
        if r.status_code == 200:
            albums = r.json()
            out["albums"] = {
                "total": len(albums),
                "shared": sum(1 for a in albums if a.get("shared")),
                "empty": sum(1 for a in albums if a.get("assetCount", 0) == 0),
            }
    except Exception:
        pass

    try:
        from synmich.core.checkpoint import Checkpoint
        cp = Checkpoint(config=config)
        out["checkpoint"] = cp.get_summary()
    except Exception:
        pass

    print(json.dumps(out, indent=2))
    return 0
