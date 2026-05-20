"""Helpers for the Migrator v1.1.0:
- Clean display (hide the "already done" spam)
- Config/checkpoint mismatch detection
- Pre-counting before migration
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from synmich.ui.cli_helpers import (
    console, info, success, warn, error, muted, panel_summary,
    COLOR_PRIMARY, COLOR_OK, COLOR_WARN, COLOR_ERROR,
)

log = logging.getLogger("synmich")


def check_and_warn_config_mismatch(config: Dict[str, Any]) -> bool:
    """Check for a config/checkpoint mismatch and warn if found.

    Returns True if we should continue, False if we should abort.
    """
    from synmich.core.checkpoint import detect_config_mismatch

    mismatch = detect_config_mismatch(config)
    if mismatch is None:
        return True

    console.print()
    warn("⚠ Config / checkpoint mismatch detected")
    console.print()
    muted(f"  Config users:     {', '.join(mismatch['config_users'])}")
    muted(f"  Checkpoint users: {', '.join(mismatch['checkpoint_users'])}")
    muted(f"  Extra in checkpoint: {', '.join(mismatch.get('extra_in_checkpoint', []))}")
    console.print()
    muted("  This usually happens when:")
    muted("    - You changed the user list in config")
    muted("    - You restored an old checkpoint")
    muted("    - You're using the wrong config file")
    console.print()
    muted("  Continuing may create duplicate albums.")
    muted("  Options:")
    muted("    1. Type 'continue' to proceed anyway")
    muted("    2. Type 'fresh' to start with an empty checkpoint")
    muted("    3. Type 'abort' to cancel and check your config")
    console.print()

    answer = input("  Choice [continue/fresh/abort]: ").strip().lower()
    if answer == "continue":
        return True
    elif answer == "fresh":
        from synmich.core.checkpoint import get_checkpoint_path_for_config
        path = get_checkpoint_path_for_config(config)
        if path.exists():
            path.unlink()
            info("Checkpoint cleared, starting fresh")
        return True
    else:
        info("Aborted")
        return False


def announce_migration_start(checkpoint, config: Dict[str, Any]) -> None:
    """Print a clean recap BEFORE launching the migration."""
    summary = checkpoint.get_summary()

    console.print()
    if summary["uploaded"] > 0:
        items = [
            ("Resume from checkpoint", "yes"),
            ("Already migrated", f"{summary['uploaded']:,} items"),
            ("Albums done", f"{summary['albums_done']} albums"),
            ("Users", ", ".join(summary['users']) or "—"),
        ]
        panel_summary("Migration resume", items, color=COLOR_OK)
        console.print()
        muted("  Items already migrated will be skipped silently.")
        muted("  Only new or failed items will be processed.")
    else:
        items = [
            ("Status", "fresh start"),
            ("Users", ", ".join(u.get("name", "?") for u in config.get("users", []))),
        ]
        panel_summary("Migration start", items, color=COLOR_PRIMARY)
    console.print()


class SilentSkipCounter:
    """Silently count the 'already done' items.

    Instead of logging every "already done", we increment a counter
    and print a periodic summary every 1000 skipped items.
    """

    def __init__(self, log_every: int = 1000):
        self.count = 0
        self.log_every = log_every

    def skip(self, item_id: Any = None) -> None:
        self.count += 1
        if self.count % self.log_every == 0:
            log.info("Skipped %d items (already migrated)...", self.count)

    def get_count(self) -> int:
        return self.count

    def summarize(self) -> None:
        if self.count > 0:
            muted(f"  ℹ Skipped {self.count:,} items already migrated")
