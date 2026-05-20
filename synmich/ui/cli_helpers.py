"""Helpers for a nicer CLI with Rich (v1.1.0).

Centralizes all the display helpers for:
- Titles / sections
- Organized tables
- Clear errors (no tracebacks)
- User-friendly messages
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.box import ROUNDED
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# v1.1.0: SINGLE source for the console and the palette = theme.py, for a
# consistent rendering across the whole CLI. The message helpers
# (info/success/warn/error/muted) are re-exported from theme so they are
# strictly the same everywhere. COLOR_OK/COLOR_WARN are aliases of the theme
# names (COLOR_SUCCESS/COLOR_WARNING) so as not to break imports.
from synmich.ui.theme import (  # noqa: F401  (intentional re-exports)
    console,
    info,
    success,
    warn,
    error,
    muted,
    COLOR_PRIMARY,
    COLOR_ACCENT,
    COLOR_MUTED,
    COLOR_ERROR,
    COLOR_SUCCESS as COLOR_OK,
    COLOR_WARNING as COLOR_WARN,
)


def section(title: str, subtitle: Optional[str] = None) -> None:
    """Print a section title like 'Step 1/4 · ...'."""
    text = f"[bold {COLOR_PRIMARY}]{title}[/]"
    if subtitle:
        text += f"  [{COLOR_MUTED}]· {subtitle}[/]"
    console.rule(text, style=COLOR_PRIMARY)


def table_albums(
    albums: List[Dict[str, Any]],
    title: str = "Albums",
    max_rows: int = 100,
) -> None:
    """Display a list of albums in a colored table."""
    t = Table(title=title, box=ROUNDED, header_style=f"bold {COLOR_PRIMARY}")
    t.add_column("ID", style="dim", width=10)
    t.add_column("Name")
    t.add_column("Owner", style=COLOR_ACCENT)
    t.add_column("Items", justify="right")
    t.add_column("Shared", justify="center")

    shown = 0
    for a in albums[:max_rows]:
        name = a.get("albumName") or a.get("name", "?")
        owner = (a.get("owner", {}) or {}).get("name", "?")
        items = a.get("assetCount", 0)
        shared = "✓" if a.get("shared") else ""
        items_str = (
            f"[{COLOR_ERROR}]{items}[/]" if items == 0
            else f"[{COLOR_OK}]{items}[/]" if items > 0
            else str(items)
        )
        t.add_row(
            a.get("id", "")[:8],
            name,
            owner,
            items_str,
            shared,
        )
        shown += 1

    if len(albums) > max_rows:
        t.caption = f"Showing {shown}/{len(albums)} albums"

    console.print(t)


def table_users(users: List[Dict[str, Any]], title: str = "Users") -> None:
    """Display a list of users."""
    t = Table(title=title, box=ROUNDED, header_style=f"bold {COLOR_PRIMARY}")
    t.add_column("Name", style=COLOR_PRIMARY)
    t.add_column("Synology")
    t.add_column("Immich")
    t.add_column("Status", justify="center")

    for u in users:
        status = u.get("_status", "?")
        status_str = (
            f"[{COLOR_OK}]✓ OK[/]" if status == "ok"
            else f"[{COLOR_ERROR}]✗ {status}[/]" if status != "?"
            else "[dim]?[/]"
        )
        t.add_row(
            u.get("name", "?"),
            u.get("syno_username", "?"),
            u.get("immich_email", "?"),
            status_str,
        )

    console.print(t)


def table_stats(
    stats: Dict[str, Any],
    title: str = "Migration statistics",
) -> None:
    """Display the migration counters."""
    t = Table(box=ROUNDED, header_style=f"bold {COLOR_PRIMARY}", title=title)
    t.add_column("Metric")
    t.add_column("Value", justify="right")

    for k, v in stats.items():
        if isinstance(v, dict):
            # nested (e.g. items_per_user)
            t.add_row(
                f"[bold]{k}[/]",
                "",
            )
            for sub_k, sub_v in v.items():
                t.add_row(
                    f"  {sub_k}",
                    str(sub_v),
                )
        elif isinstance(v, (int, float)):
            t.add_row(k, f"{v:,}")
        else:
            t.add_row(k, str(v))

    console.print(t)


def table_checkpoints(checkpoints: List[Dict[str, Any]]) -> None:
    """Display the list of checkpoints."""
    if not checkpoints:
        muted("No checkpoints found.")
        return

    t = Table(
        title="Checkpoints",
        box=ROUNDED,
        header_style=f"bold {COLOR_PRIMARY}",
    )
    t.add_column("Hash", style="dim")
    t.add_column("Description")
    t.add_column("Users")
    t.add_column("Uploaded", justify="right")
    t.add_column("Albums", justify="right")
    t.add_column("Last used", style="dim")

    for cp in checkpoints:
        users_str = ", ".join(cp.get("users", []))
        counters = cp.get("counters", {})
        t.add_row(
            cp.get("hash", "")[:8],
            cp.get("description", "?"),
            users_str,
            f"{counters.get('uploaded', 0):,}",
            str(cp.get("albums_done", 0)),
            cp.get("last_used", "?").split("T")[0],  # just date
        )

    console.print(t)


def panel_error(title: str, message: str, hint: Optional[str] = None) -> None:
    """Display an error in a clean panel (instead of a traceback)."""
    content = f"[bold {COLOR_ERROR}]{message}[/]"
    if hint:
        content += f"\n\n[{COLOR_MUTED}]Hint:[/] {hint}"
    console.print(Panel(
        content,
        title=f"[bold {COLOR_ERROR}]✗ {title}[/]",
        border_style=COLOR_ERROR,
        padding=(1, 2),
    ))


def panel_summary(
    title: str,
    items: List[tuple],
    color: str = None,
) -> None:
    """Summary panel with labels + values.

    items: list of (label, value) tuples
    """
    color = color or COLOR_PRIMARY
    lines = []
    max_label_width = max(len(str(label)) for label, _ in items) + 2
    for label, value in items:
        label_str = f"{label}".ljust(max_label_width)
        lines.append(f"  [{COLOR_MUTED}]{label_str}[/] {value}")
    content = "\n".join(lines)
    console.print(Panel(
        content,
        title=f"[bold {color}]{title}[/]",
        border_style=color,
        padding=(1, 2),
    ))


def panel_help_grouped(groups: Dict[str, List[tuple]]) -> None:
    """Display a help organized in groups."""
    for group_name, commands in groups.items():
        console.print(f"\n  [bold {COLOR_ACCENT}]{group_name}[/]")
        for cmd, desc in commands:
            console.print(
                f"    [bold {COLOR_PRIMARY}]{cmd:<18}[/] [{COLOR_MUTED}]{desc}[/]"
            )
