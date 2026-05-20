"""Album selector (used when migration.albums_mode == "select").

Two interfaces, same result (a set of album keys, see migrator.album_key):

- **Textual** (default, interactive terminal): real checkboxes,
  ↑↓ to navigate, space to toggle, Enter to confirm, Escape to cancel.
- **Text** (fallback): Rich table + number input, used when Textual is
  not available.

If stdin is not interactive (`</dev/null`, automated run), we simply return
the already-saved selection.

Semantics: a flat list of unique albums (a shared album appears as a single
entry, with its owner + 🤝). Ticking it is enough to migrate it; in mirror
mode all contributions are included.
"""

from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from rich.box import ROUNDED
from rich.table import Table

from textual.app import App
from textual.binding import Binding
from textual.widgets import Footer, Label, SelectionList, TabbedContent, TabPane
from textual.widgets.selection_list import Selection

from synmich.core.migrator import album_key
from synmich.ui.theme import (
    console,
    success,
    warn,
    muted,
    COLOR_PRIMARY,
    COLOR_ACCENT,
    COLOR_MUTED,
    COLOR_SUCCESS as COLOR_OK,
)


# ----------------------------------------------------------------------------
# Data building (shared by both interfaces)
# ----------------------------------------------------------------------------
def _build_records(sessions) -> Dict[str, Dict[str, Any]]:
    """album_key -> {name, items, shared, owner_name, viewers}."""
    records: Dict[str, Dict[str, Any]] = {}
    sessions_by_uid = {s.syno_user_id: s for s in sessions}

    for s in sessions:
        try:
            albums = s.syno.list_albums()
        except Exception as e:  # noqa: BLE001
            warn(f"{s.name}: could not list albums ({e})")
            continue

        for a in albums:
            key = album_key(s.name, a)
            if key in records:
                continue
            sharing = (
                a.get("additional", {}).get("sharing_info", {}) or {}
            )
            oid = sharing.get("owner", {}).get("id")
            owner_syno_id = (
                oid
                if (oid is not None and oid > 0)
                else a.get("owner_user_id")
            )
            owner_sess = sessions_by_uid.get(owner_syno_id)
            owner_name = (
                sharing.get("owner", {}).get("name")
                or (owner_sess.name if owner_sess else s.name)
            )
            is_shared = bool(a.get("shared")) or bool(
                sharing.get("permission")
            )

            viewers: Set[str] = set()
            viewers.add(owner_sess.name if owner_sess else s.name)
            for p in sharing.get("permission", []) or []:
                pname = (p.get("name") or "").strip()
                matched = False
                for cand in sessions:
                    if (
                        p.get("db_id") == cand.syno_user_id
                        or pname.lower() == cand.name.lower()
                    ):
                        viewers.add(cand.name)
                        matched = True
                # Even if this viewer isn't a configured account, show the
                # name Synology reports so "shared with X" works everywhere.
                if not matched and pname:
                    viewers.add(pname)

            records[key] = {
                "name": a.get("name", "?"),
                "items": a.get("item_count", 0),
                "shared": is_shared,
                "owner_name": owner_name,
                "viewers": viewers,
            }
    return records


def _compile(regex: Optional[str]):
    if not regex:
        return None
    try:
        return re.compile(regex, re.IGNORECASE)
    except re.error:
        return None


def _album_label(r: Dict[str, Any]) -> str:
    """Per-tab label: the owner is the tab, so show name + items + who it's
    shared with (the tab already tells you whose album it is)."""
    shared_with = sorted(set(r.get("viewers") or set()) - {r.get("owner_name")})
    if r["shared"] and shared_with:
        tag = f"   ·   shared with {', '.join(shared_with)}"
    elif r["shared"]:
        tag = "   ·   shared"
    else:
        tag = ""
    return f"{r['name']}   ·   {r['items']} items{tag}"


# ----------------------------------------------------------------------------
# Textual interface (checkboxes)
# ----------------------------------------------------------------------------
class AlbumSelectionList(SelectionList):
    """SelectionList where **Enter confirms** the selection.

    By default SelectionList/OptionList bind both `enter` AND `space` to
    "select" (= toggle). We rebind `enter` so it triggers the app's
    validation; `space` stays the toggle. This is the expected interaction:
    space to tick, Enter to confirm.
    """

    BINDINGS = [Binding("enter", "confirm", "Confirm", show=False)]

    def action_confirm(self) -> None:
        self.app.action_validate()


class AlbumSelectorApp(App):
    """Album selection via checkboxes, with one tab per user (owner) - the
    same grouping as the GUI, so multiple users' albums are never mixed."""

    CSS = """
    Screen { align: center middle; }
    #title { width: 100%; content-align: center middle; text-style: bold;
             color: $accent; }
    #hint  { width: 100%; content-align: center middle; color: $text-muted; }
    TabbedContent { width: 92%; height: 1fr; margin: 1 0; }
    AlbumSelectionList { height: 1fr; border: round $primary; padding: 0 1; }
    #status { width: 100%; content-align: center middle; color: $text-muted; }
    """

    BINDINGS = [
        Binding("enter", "validate", "Confirm"),
        Binding("a", "all", "All (this user)"),
        Binding("n", "none", "None (this user)"),
        Binding("right_square_bracket", "next_tab", "Next user"),
        Binding("left_square_bracket", "prev_tab", "Prev user"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        groups: "Dict[str, List[Tuple[str, str]]]",  # owner -> [(label, key)]
        preselected: Set[str],
    ):
        super().__init__()
        self._groups = dict(groups)
        self._pre = set(preselected or set())
        self._total = sum(len(v) for v in groups.values())

    def compose(self):
        yield Label("synmich · Choose the albums to migrate", id="title")
        yield Label(
            "Tab: switch field   [ ]: switch user   ↑↓ navigate   "
            "␣ tick   a/n: all/none (user)   Enter confirm   Esc cancel",
            id="hint",
        )
        with TabbedContent():
            for i, (owner, opts) in enumerate(self._groups.items()):
                with TabPane(f"{owner} ({len(opts)})", id=f"u{i}"):
                    yield AlbumSelectionList(
                        *[Selection(label, key, key in self._pre)
                          for (label, key) in opts],
                        id=f"list-u{i}",
                    )
        yield Label("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        lists = self.query(SelectionList)
        if lists:
            lists.first().focus()
        self._refresh_status()

    def _selected_all(self) -> Set[str]:
        sel: Set[str] = set()
        for sl in self.query(SelectionList):
            sel |= set(sl.selected)
        return sel

    def _refresh_status(self) -> None:
        self.query_one("#status", Label).update(
            f"{self._total} albums  ·  {len(self._selected_all())} selected"
        )

    def on_selection_list_selected_changed(self, _event) -> None:
        self._refresh_status()

    def _active_list(self):
        tc = self.query_one(TabbedContent)
        return tc.get_pane(tc.active).query_one(SelectionList)

    def _switch(self, delta: int) -> None:
        tc = self.query_one(TabbedContent)
        n = len(self._groups)
        cur = int(tc.active[1:]) if (tc.active or "").startswith("u") else 0
        nxt = (cur + delta) % n
        tc.active = f"u{nxt}"
        try:
            tc.get_pane(f"u{nxt}").query_one(SelectionList).focus()
        except Exception:  # noqa: BLE001
            pass

    def action_next_tab(self) -> None:
        self._switch(1)

    def action_prev_tab(self) -> None:
        self._switch(-1)

    def action_all(self) -> None:
        try:
            self._active_list().select_all()
        except Exception:  # noqa: BLE001
            pass
        self._refresh_status()

    def action_none(self) -> None:
        try:
            self._active_list().deselect_all()
        except Exception:  # noqa: BLE001
            pass
        self._refresh_status()

    def action_validate(self) -> None:
        self.exit(self._selected_all())

    def action_cancel(self) -> None:
        self.exit(None)


# ----------------------------------------------------------------------------
# Text interface (fallback)
# ----------------------------------------------------------------------------
def _parse_selection(raw: str, n: int):
    """Return "all", "none", a set of 1-based indices, or None (unchanged)."""
    raw = (raw or "").strip().lower()
    if not raw:
        return None
    if raw in ("all", "a", "*"):
        return "all"
    if raw in ("none", "n", "0"):
        return "none"
    out: Set[int] = set()
    for part in raw.replace(" ", ",").split(","):
        if not part:
            continue
        if "-" in part:
            try:
                a_s, b_s = part.split("-", 1)
                a, b = int(a_s), int(b_s)
            except ValueError:
                continue
            for x in range(min(a, b), max(a, b) + 1):
                if 1 <= x <= n:
                    out.add(x)
        else:
            try:
                x = int(part)
            except ValueError:
                continue
            if 1 <= x <= n:
                out.add(x)
    return out or None


def _show_and_prompt(
    user_name: str,
    visible: List[Tuple[str, Dict[str, Any]]],
    selected: Set[str],
) -> None:
    console.print()
    console.rule(
        f"[bold {COLOR_PRIMARY}]Albums visible to {user_name}[/]",
        style=COLOR_PRIMARY,
    )
    table = Table(box=ROUNDED, header_style=f"bold {COLOR_PRIMARY}")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Sel.", justify="center", width=4)
    table.add_column("Album")
    table.add_column("Items", justify="right")
    table.add_column("Shared")
    for i, (key, r) in enumerate(visible, 1):
        mark = f"[{COLOR_OK}]✓[/]" if key in selected else "[dim]·[/]"
        shared = "🤝" if r["shared"] else ""
        items_str = f"[{COLOR_MUTED}]0[/]" if not r["items"] else str(r["items"])
        table.add_row(str(i), mark, r["name"], items_str, shared)
    console.print(table)
    muted(
        "  ✓ = selected. Numbers to TOGGLE (e.g. 1,3 / 1-3), "
        "'all', 'none', or Enter to continue."
    )
    try:
        raw = input(f"  {user_name} ▸ ").strip()
    except EOFError:
        raw = ""
    sel = _parse_selection(raw, len(visible))
    if sel == "all":
        for key, _ in visible:
            selected.add(key)
    elif sel == "none":
        for key, _ in visible:
            selected.discard(key)
    elif isinstance(sel, set):
        for idx in sel:
            key = visible[idx - 1][0]
            (selected.discard if key in selected else selected.add)(key)
    cur = sum(1 for key, _ in visible if key in selected)
    success(f"{user_name}: {cur}/{len(visible)} album(s) selected")


def _text_select(sessions, records, selected, rx) -> Set[str]:
    """Text fallback: one pass per user (toggle by numbers)."""
    for s in sessions:
        visible = [
            (key, r) for key, r in records.items() if s.name in r["viewers"]
        ]
        if rx:
            visible = [(k, r) for k, r in visible if rx.search(r["name"])]
        if not visible:
            continue
        visible.sort(key=lambda kr: kr[1]["name"].lower())
        _show_and_prompt(s.name, visible, selected)
    return selected


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def select_albums(
    sessions,
    preselected: Optional[Set[str]] = None,
    include_regex: Optional[str] = None,
) -> Optional[Set[str]]:
    """Return the set of chosen album keys.

    - set()    : selection (possibly empty).
    - None     : the user cancelled (Escape) -> migration must stop.
    """
    selected: Set[str] = set(preselected or set())

    records = _build_records(sessions)
    if not records:
        warn("No album found on Synology.")
        return selected

    rx = _compile(include_regex)
    items = [
        (key, r)
        for key, r in sorted(
            records.items(), key=lambda kr: kr[1]["name"].lower()
        )
        if not (rx and not rx.search(r["name"]))
    ]
    if not items:
        warn("No album matches the include_albums_regex filter.")
        return selected

    if not sys.stdin.isatty():
        warn(
            "Non-interactive input: selector skipped, "
            "using the saved selection."
        )
        return selected

    # Group by owner -> one tab per user (same as the GUI).
    groups: Dict[str, List[Tuple[str, str]]] = {}
    for key, r in items:
        groups.setdefault(r["owner_name"], []).append((_album_label(r), key))
    groups = {k: groups[k] for k in sorted(groups, key=str.lower)}

    # Textual interface (tabs + checkboxes) by default, text fallback on error.
    try:
        app = AlbumSelectorApp(groups, selected)
        result = app.run()
    except Exception as e:  # noqa: BLE001
        warn(f"Graphical selector unavailable ({e}); falling back to text mode.")
        return _text_select(sessions, records, selected, rx)

    return result  # set OR None (cancelled)
