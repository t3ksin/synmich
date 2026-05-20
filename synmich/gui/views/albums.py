"""Album Manager - browse and rename Immich albums (no deletion).

One sub-tab per Immich user (so it's clear whose albums these are), including
users that have no API key or no album yet. Renaming proposes a cleaned-up
name which the user confirms or edits. Albums are never deleted here.
"""

from __future__ import annotations

import re
import threading

import customtkinter as ctk

from synmich.gui import widgets as W
from synmich.gui.dialogs import prompt_rename


def _clean_name(name: str) -> str:
    n = (name or "").replace("_", " ")
    n = re.sub(r"\s+", " ", n).strip()
    return n or name


def _immich_shared(album) -> list:
    """Names/emails an Immich album is shared with (best effort from the
    fields the album listing exposes)."""
    names = []
    for au in (album.get("albumUsers") or []):
        u = au.get("user", au) if isinstance(au, dict) else {}
        n = u.get("name") or u.get("email")
        if n:
            names.append(n)
    for u in (album.get("sharedUsers") or []):
        n = (u.get("name") or u.get("email")) if isinstance(u, dict) else None
        if n:
            names.append(n)
    return names


class AlbumsView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=W.CONTENT)
        self.app = app
        self._albums = []

        ctk.CTkLabel(self, text="Immich Album Manager", font=W.font(20, "bold"),
                     text_color=W.TEXT).pack(anchor="w", padx=20, pady=(14, 0))
        ctk.CTkLabel(self, text="Browse and rename the albums already in "
                     "Immich, grouped per user. Renaming only - albums are "
                     "never deleted.", font=W.font(12), text_color=W.MUTED,
                     wraplength=900, justify="left", anchor="w").pack(
            anchor="w", padx=20, pady=(0, 4))

        c = W.card(self, "Immich albums")
        c.pack(fill="both", expand=True, padx=16, pady=6)
        top = ctk.CTkFrame(c.body, fg_color="transparent")
        top.pack(fill="x")
        W.primary_button(top, "Load albums", self._load, color=W.BLUE,
                         hover=W.BLUE_DK).pack(side="left")
        self.count_lbl = ctk.CTkLabel(top, text="", text_color=W.MUTED)
        self.count_lbl.pack(side="left", padx=12)
        self.progress = ctk.CTkProgressBar(c.body, progress_color=W.GREEN,
                                           corner_radius=0, height=6)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(8, 0))
        self.box = ctk.CTkFrame(c.body, fg_color="transparent")
        self.box.pack(fill="both", expand=True, pady=(6, 0))
        ctk.CTkLabel(self.box,
                     text="Click \"Load albums\" to browse and rename your "
                          "Immich albums. Only your Immich API key is used "
                          "here (no Synology login needed).",
                     text_color=W.MUTED, wraplength=700, justify="left").pack(
            anchor="w", padx=6, pady=8)
        self.status = ctk.CTkLabel(c.body, text="", text_color=W.MUTED,
                                   font=W.font(11), wraplength=700,
                                   justify="left")
        self.status.pack(anchor="w", pady=(6, 0))
        W.fix_wrapping(self)

    def _busy(self, on):
        if on:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)

    def _load(self):
        # The Album Manager only talks to Immich - it needs the API key only,
        # no Synology login. Keys come from the Synology to Immich users.
        if not self.app.cfg.get("users"):
            self.status.configure(
                text="No Immich user yet. Add a user with an Immich API key "
                     "in the Synology to Immich tab, then come back here.",
                text_color=W.ORANGE)
            return
        if not self.app.immich_clients:
            self.status.configure(text="Connecting to Immich...",
                                  text_color=W.MUTED)
            self._busy(True)
            self.app.connect_immich(self._after_connect)
            return
        self.status.configure(text="Loading albums...", text_color=W.MUTED)
        self._busy(True)
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _after_connect(self, ok, msg):
        if ok:
            self.status.configure(text="Loading albums...", text_color=W.MUTED)
            threading.Thread(target=self._load_worker, daemon=True).start()
        else:
            self._busy(False)
            self.status.configure(text=msg, text_color=W.RED)

    def _load_worker(self):
        groups: dict = {}
        try:
            for name, client in self.app.immich_clients:
                info = groups.setdefault(name, {"email": "", "albums": []})
                try:
                    me = client.me()
                    info["email"] = me.get("email") or me.get("name") or ""
                except Exception:  # noqa: BLE001
                    pass
                seen = set()
                # Owned albums + albums shared with this user, merged & deduped
                # (GET /albums alone only returns the ones the user owns).
                lists = [client.list_albums()]
                try:
                    lists.append(client.list_albums(shared=True))
                except Exception:  # noqa: BLE001
                    pass
                for lst in lists:
                    for a in (lst or []):
                        aid = a.get("id")
                        if aid in seen:
                            continue
                        seen.add(aid)
                        info["albums"].append((client, a))
        except Exception as e:  # noqa: BLE001
            self.after(0, lambda: (self._busy(False), self.status.configure(
                text=f"Failed: {e}", text_color=W.RED)))
            return
        self.after(0, lambda: self._populate(groups))

    def _populate(self, groups):
        self._busy(False)
        self._albums = groups
        for w in self.box.winfo_children():
            w.destroy()
        total = sum(len(v["albums"]) for v in groups.values())
        self.count_lbl.configure(text=f"{total} album(s)")
        self.status.configure(text="")

        def uname(u):
            return u.get("name") or u.get("syno_username") or "user"
        cfg_users = self.app.cfg.get("users", [])
        no_key = {uname(u) for u in cfg_users if not u.get("immich_api_key")}
        all_names = sorted(set(list(groups) + [uname(u) for u in cfg_users]),
                           key=str.lower)
        if not all_names:
            ctk.CTkLabel(self.box, text="No Immich user yet.",
                         text_color=W.MUTED).pack(anchor="w", padx=6, pady=8)
            return

        tv = W.sub_tabview(self.box)
        tv.pack(fill="both", expand=True)
        for name in all_names:
            info = groups.get(name, {"email": "", "albums": []})
            albums = info["albums"]
            tab = tv.add(f"{name} ({len(albums)})")
            sf = W.scroll_frame(tab)
            sf.pack(fill="both", expand=True)
            if name in no_key:
                ctk.CTkLabel(
                    sf, text="This user has no Immich API key. Add it in the "
                    "Synology to Immich tab to manage its albums.",
                    text_color=W.ORANGE, wraplength=600, justify="left").pack(
                    anchor="w", padx=8, pady=8)
                continue
            # Show which Immich account this API key maps to (helps spot a
            # key that points to the wrong account).
            if info.get("email"):
                ctk.CTkLabel(sf, text=f"Immich account: {info['email']}",
                             text_color=W.MUTED, font=W.font(10),
                             anchor="w").pack(fill="x", padx=8, pady=(6, 2))
            if not albums:
                ctk.CTkLabel(
                    sf, text="This Immich account (above) owns / is shared "
                    "0 album. Note: the \"Synology to Immich\" tab lists this "
                    "user's Synology albums (the source, on the NAS) - those "
                    "show up here only once migrated into this Immich "
                    "account. Albums migrated from a shared album appear "
                    "under their owner's tab.", text_color=W.ORANGE,
                    wraplength=600, justify="left").pack(anchor="w", padx=8,
                                                         pady=8)
                continue
            for client, a in sorted(
                    albums,
                    key=lambda x: (x[1].get("albumName") or "").lower()):
                row = ctk.CTkFrame(sf, fg_color=W.CARD, corner_radius=0)
                row.pack(fill="x", padx=4, pady=3)
                W.primary_button(
                    row, "Rename",
                    lambda c=client, al=a: self._rename(c, al),
                    color=W.BLUE, hover=W.BLUE_DK, width=90, height=28).pack(
                    side="right", padx=6, pady=6)
                ctk.CTkLabel(row, text=f"  {a.get('albumName', '?')}",
                             anchor="w", text_color=W.TEXT,
                             font=W.font(12, "bold")).pack(side="left",
                                                           padx=6, pady=6)
                ctk.CTkLabel(row, text=f"{a.get('assetCount', 0)} photos",
                             text_color=W.MUTED, font=W.font(11)).pack(
                    side="left", padx=(4, 0))
                shared = _immich_shared(a)
                if shared:
                    ctk.CTkLabel(row, text=f"shared with {', '.join(shared)}",
                                 text_color=W.ORANGE,
                                 font=W.font(11, "bold")).pack(side="left",
                                                               padx=(10, 0))

    def clear_albums(self):
        """Drop the loaded album list (e.g. after an account changed)."""
        self._albums = []
        for w in self.box.winfo_children():
            w.destroy()
        self.count_lbl.configure(text="")
        self.status.configure(text="")
        ctk.CTkLabel(self.box,
                     text="Click \"Load albums\" to browse and rename your "
                          "Immich albums.", text_color=W.MUTED,
                     wraplength=700, justify="left").pack(anchor="w", padx=6,
                                                          pady=8)

    def _rename(self, client, album):
        old = album.get("albumName", "")
        new = prompt_rename(self, old, _clean_name(old))
        if not new or new == old:
            return
        self.status.configure(text="Renaming...", text_color=W.MUTED)

        def worker():
            try:
                ok = client.rename_album(album["id"], new)
            except Exception:  # noqa: BLE001
                ok = False
            self.after(0, lambda: self._after_rename(ok))

        threading.Thread(target=worker, daemon=True).start()

    def _after_rename(self, ok):
        if ok:
            self.status.configure(text="Album renamed.", text_color=W.GREEN)
            self._load()
        else:
            self.status.configure(text="Rename failed.", text_color=W.RED)
