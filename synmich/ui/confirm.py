"""Pre-migration confirmation screen (Textual).

Shows a clean recap of what is about to be migrated and asks the user to
press a big "Confirm migration" button before anything is downloaded or
uploaded. Used by `synmich migrate` (interactive) and by `synmich init`
when it chains automatically into the migration.
"""

from __future__ import annotations

from typing import Any, Dict, List

from rich.table import Table

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static


# Internal shared_albums_mode value -> user-facing wizard name.
_SHARED_MODE_LABELS = {
    "link": "mirror-syno",
    "duplicate": "separate",
    "ignore": "skip",
}


def build_migration_summary(sessions, config: Dict[str, Any]) -> Dict[str, Any]:
    """Compute what WILL be migrated, for the confirmation recap.

    Reuses the album selector's record builder so the counts match exactly
    what the migrator will process (selection / regex applied identically).
    """
    from synmich.ui.album_selector import _build_records, _compile

    mig = config.get("migration", {})
    albums_mode = mig.get("albums_mode", "all")
    selected = set(mig.get("selected_albums", []) or [])
    rx = _compile(config.get("filters", {}).get("include_albums_regex"))

    records = _build_records(sessions)
    chosen: List = []
    for key, r in records.items():
        if albums_mode == "select":
            if key not in selected:
                continue
        elif rx and not rx.search(r["name"]):
            continue
        chosen.append((r["name"], r["items"], r["shared"]))
    chosen.sort(key=lambda x: x[0].lower())

    return {
        "syno_url": config.get("synology", {}).get("url", ""),
        "immich_url": config.get("immich", {}).get("url", ""),
        "users": [s.name for s in sessions],
        "albums": chosen,
        "total_items": sum(c for _, c, _ in chosen),
        "albums_mode": albums_mode,
        "shared_mode": mig.get("shared_albums_mode", "link"),
        "include_timeline": bool(mig.get("include_timeline", True)),
    }


class MigrationConfirmApp(App):
    """Full-screen confirmation with a recap and Confirm / Cancel buttons."""

    CSS = """
    Screen { align: center middle; }
    #card {
        width: 84; max-width: 92%; height: auto;
        border: round $primary; background: $panel; padding: 1 2;
    }
    #title {
        width: 100%; content-align: center middle;
        text-style: bold; color: $success; padding-bottom: 1;
    }
    #recap { width: 100%; padding-bottom: 1; }
    #buttons { width: 100%; height: auto; align: center middle; padding-top: 1; }
    Button { margin: 0 2; min-width: 26; }
    """

    BINDINGS = [
        Binding("y", "confirm", "Confirm"),
        Binding("escape", "cancel", "Cancel"),
        Binding("n", "cancel", "Cancel"),
    ]

    def __init__(self, summary: Dict[str, Any]):
        super().__init__()
        self._s = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static("🚀  Ready to migrate", id="title")
            yield Static(self._recap(), id="recap")
            with Horizontal(id="buttons"):
                yield Button(
                    "✓  Confirm migration", variant="success", id="confirm"
                )
                yield Button("✗  Cancel", variant="error", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#confirm", Button).focus()

    def _recap(self) -> Table:
        s = self._s
        t = Table.grid(padding=(0, 2))
        t.add_column(justify="right", style="bold cyan")
        t.add_column()
        t.add_row("From", f"Synology  [dim]{s['syno_url']}[/]")
        t.add_row("To", f"Immich  [dim]{s['immich_url']}[/]")
        t.add_row("User(s)", ", ".join(s["users"]) or "—")
        t.add_row("", "")
        scope = (
            "Selected albums"
            if s["albums_mode"] == "select"
            else "All albums"
        )
        t.add_row(scope, f"[bold]{len(s['albums'])}[/]")
        for name, count, shared in s["albums"][:12]:
            mark = " 🤝" if shared else ""
            t.add_row("", f"• {name}{mark}  [dim]({count} photos)[/]")
        if len(s["albums"]) > 12:
            t.add_row("", f"[dim]… and {len(s['albums']) - 12} more[/]")
        t.add_row("", "")
        t.add_row("Total photos", f"[bold green]{s['total_items']}[/]")
        t.add_row(
            "Shared mode",
            _SHARED_MODE_LABELS.get(s["shared_mode"], s["shared_mode"]),
        )
        t.add_row(
            "Timeline",
            "included" if s["include_timeline"] else "skipped",
        )
        return t

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.exit(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.exit(True)

    def action_cancel(self) -> None:
        self.exit(False)


def confirm_migration(summary: Dict[str, Any]) -> bool:
    """Show the confirmation screen. Returns True if the user confirmed."""
    return bool(MigrationConfirmApp(summary).run())
