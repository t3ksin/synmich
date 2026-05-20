"""synmich checkpoints — Manage checkpoints (v1.1.0).

Subcommands:
    list         List all existing checkpoints
    show         Details of the current checkpoint (per config)
    delete       Delete a checkpoint by hash
    migrate      Migrate the old checkpoint.json to the new format
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from synmich.ui.cli_helpers import (
    console, info, success, warn, error, muted,
    section, table_checkpoints, panel_summary,
    COLOR_PRIMARY, COLOR_OK, COLOR_WARN, COLOR_ERROR,
)


def cmd_checkpoints_list(args) -> int:
    """List all checkpoints."""
    from synmich.core.checkpoint import list_all_checkpoints

    cps = list_all_checkpoints()
    if not cps:
        muted("\n  No checkpoints found.\n")
        return 0

    console.print()
    table_checkpoints(cps)
    console.print()
    muted(f"  {len(cps)} checkpoint(s) total")
    muted(f"  Use 'synmich checkpoints show <hash>' for details")
    muted(f"  Use 'synmich checkpoints delete <hash>' to remove one")
    console.print()
    return 0


def cmd_checkpoints_show(args) -> int:
    """Details of a checkpoint."""
    from synmich.core.checkpoint import (
        Checkpoint, get_checkpoint_path_for_config, list_all_checkpoints,
    )
    from synmich.config import load_config

    if args.hash:
        # Find by hash
        cps = list_all_checkpoints()
        matches = [c for c in cps if c["hash"].startswith(args.hash)]
        if not matches:
            error(f"No checkpoint matching hash '{args.hash}'")
            return 1
        if len(matches) > 1:
            error(f"Ambiguous hash. Matches: {[m['hash'] for m in matches]}")
            return 1
        path = Path(matches[0]["path"])
        cp = Checkpoint(path=path)
    else:
        # Current checkpoint according to the config
        config = load_config()
        cp = Checkpoint(config=config)

    summary = cp.get_summary()

    console.print()
    section("Checkpoint details")
    console.print()

    items = [
        ("Path", cp.path.name),
        ("Uploaded", f"{summary['uploaded']:,}"),
        ("Duplicates", f"{summary['duplicate']:,}"),
        ("Failed", f"{summary['failed']:,}"),
        ("Albums done", f"{summary['albums_done']:,}"),
        ("Users tracked", ", ".join(summary['users']) or "—"),
    ]
    panel_summary("Summary", items, color=COLOR_OK)

    if summary["items_per_user"]:
        console.print(f"\n  [bold {COLOR_PRIMARY}]Items per user[/]")
        for user, n in summary["items_per_user"].items():
            console.print(f"    [bold]{user}:[/] {n:,} items")

    if summary["failed"] > 0:
        console.print(f"\n  [bold {COLOR_ERROR}]Failed items per user:[/]")
        for user, failures in cp.data.get("failed_items", {}).items():
            console.print(f"    [bold]{user}:[/] {len(failures)} failed")
            for syno_id, err in list(failures.items())[:5]:
                muted(f"      {syno_id}: {err[:80]}")
            if len(failures) > 5:
                muted(f"      ... and {len(failures) - 5} more")

    console.print()
    return 0


def cmd_checkpoints_delete(args) -> int:
    """Delete a checkpoint."""
    from synmich.core.checkpoint import delete_checkpoint, list_all_checkpoints

    cps = list_all_checkpoints()
    matches = [c for c in cps if c["hash"].startswith(args.hash)]
    if not matches:
        error(f"No checkpoint matching '{args.hash}'")
        return 1
    if len(matches) > 1:
        error(f"Ambiguous hash. Matches:")
        for m in matches:
            muted(f"  {m['hash']} - {m['description']}")
        return 1

    cp = matches[0]
    counters = cp.get("counters", {})

    if not args.yes:
        console.print()
        warn(f"About to delete checkpoint:")
        console.print(f"    Hash: {cp['hash']}")
        console.print(f"    Description: {cp['description']}")
        console.print(f"    Uploaded items: {counters.get('uploaded', 0):,}")
        console.print(f"    Albums done: {cp.get('albums_done', 0):,}")
        confirm = input("\n  Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            muted("  Cancelled.")
            return 0

    if delete_checkpoint(cp["hash"]):
        success(f"Checkpoint {cp['hash'][:8]} deleted")
        return 0
    else:
        error("Could not delete checkpoint")
        return 1


def cmd_checkpoints_migrate(args) -> int:
    """Migrate the old checkpoint.json to the new format."""
    from synmich.core.checkpoint import migrate_legacy_checkpoint
    from synmich.config import load_config

    try:
        config = load_config()
    except Exception as e:
        error(f"Cannot load config: {e}")
        return 1

    result = migrate_legacy_checkpoint(config)
    if result:
        success(f"Legacy checkpoint migrated to: {result.name}")
        muted("  Old checkpoint.json kept as checkpoint.json.legacy-backup")
        return 0
    else:
        warn("Nothing to migrate (no legacy checkpoint, or already migrated)")
        return 0


def add_subcommands(subparsers):
    """Add the checkpoints subcommands to the main CLI."""
    checkpoints = subparsers.add_parser(
        "checkpoints",
        help="Manage migration checkpoints",
    )
    cp_sub = checkpoints.add_subparsers(dest="cp_action")

    list_p = cp_sub.add_parser("list", help="List all checkpoints")
    list_p.set_defaults(func=cmd_checkpoints_list)

    show_p = cp_sub.add_parser("show", help="Show checkpoint details")
    show_p.add_argument("hash", nargs="?", help="Hash prefix (or current if omitted)")
    show_p.set_defaults(func=cmd_checkpoints_show)

    del_p = cp_sub.add_parser("delete", help="Delete a checkpoint")
    del_p.add_argument("hash", help="Hash prefix of checkpoint to delete")
    del_p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    del_p.set_defaults(func=cmd_checkpoints_delete)

    migrate_p = cp_sub.add_parser("migrate", help="Migrate legacy checkpoint.json")
    migrate_p.set_defaults(func=cmd_checkpoints_migrate)
