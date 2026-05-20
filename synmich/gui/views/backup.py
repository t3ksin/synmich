"""Synology to local - download Synology albums to a local folder.

Files are downloaded and KEPT, organized as <destination>/<user>/<album>/.
Albums are de-duplicated. A shared-albums mode controls whether contributor
photos are included. Synology-only (no Immich).
"""

from __future__ import annotations

import re
import threading
import time
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from synmich.core.migrator import (
    MigrationControl,
    MigrationStats,
    album_key,
    safe_name,
)
from synmich.gui import widgets as W
from synmich.ui.album_selector import _build_records

_BK_SHARED = [
    ("All photos", False,
     "Download every photo in each album, including photos contributed by "
     "other users. Each album is downloaded once."),
    ("Owner only", True,
     "For each album, download only the photos owned by that album's owner "
     "(skip photos added by other users)."),
]


def _plain(s):
    """Strip Rich markup and emoji/non-ASCII glyphs (they render as boxes in
    the Tk log) so the log stays clean and readable."""
    s = re.sub(r"\[/?[^\]]*\]", "", str(s))
    s = re.sub(r"[^\x00-\x7F]+", "", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def run_backup(sessions, selected, all_mode, owner_only, dest, stats, control):
    dest = Path(dest)
    seen, jobs = set(), []
    for s in sessions:
        try:
            albums = s.syno.list_albums()
        except Exception as e:  # noqa: BLE001
            stats.log_message(f"list albums {s.name}: {e}")
            continue
        for a in albums:
            k = album_key(s.name, a)
            if k in seen:
                continue
            seen.add(k)
            if all_mode or k in selected:
                jobs.append((s, a))

    stats.albums_total = len(jobs)
    if not jobs:
        stats.log_message(
            "No album found for these accounts. Check the Synology address "
            "and that the account has access to Synology Photos albums.")
    for s, a in jobs:
        if not control.check():
            break
        name = a.get("name", "album")
        stats.current_album = name
        stats.log_message(f"Album: {name}")
        sharing = a.get("additional", {}).get("sharing_info", {}) or {}
        oid = sharing.get("owner", {}).get("id")
        owner_id = (oid if (oid is not None and oid > 0)
                    else a.get("owner_user_id"))
        try:
            items = s.syno.list_items(album_id=a["id"])
        except Exception as e:  # noqa: BLE001
            stats.log_message(f"list items {name}: {e}")
            continue
        if owner_only:
            items = [it for it in items
                     if it.get("owner_user_id") == owner_id]
        folder = dest / safe_name(s.name) / safe_name(name)
        stats.items_total = len(items)
        stats.items_done = 0
        for it in items:
            if not control.check():
                break
            try:
                fp = s.syno.download(it, folder)
            except Exception:  # noqa: BLE001
                fp = None
            if fp:
                stats.uploaded += 1
            else:
                stats.failed += 1
                stats.log_message(f"failed: {it.get('filename')}")
            stats.items_done += 1
        stats.albums_done += 1
    stats.current_step = "done"


class BackupView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=W.CONTENT)
        self.app = app
        self.cfg = app.cfg
        self.album_vars: dict = {}
        self.records: dict = {}
        self.dest = ""
        self.stats = None
        self.control = None
        self._log_count = 0
        self._done = False

        ctk.CTkLabel(self, text="Synology to local", font=W.font(20, "bold"),
                     text_color=W.TEXT).pack(anchor="w", padx=20, pady=(12, 0))
        ctk.CTkLabel(self, text="Download your Synology Photos albums to a "
                     "folder on this computer. Files are kept; no Immich "
                     "needed.", font=W.font(12), text_color=W.MUTED,
                     wraplength=900, justify="left", anchor="w").pack(
            anchor="w", padx=20, pady=(0, 6))

        # ---- RUN bar pinned at the bottom ----
        run = W.card(self, "Run")
        run.pack(side="bottom", fill="x", padx=16, pady=(4, 10))
        self.start_btn = W.primary_button(run.body, "START BACKUP",
                                          self._start, height=42)
        self.start_btn.pack(fill="x")
        counters = ctk.CTkFrame(run.body, fg_color="transparent")
        counters.pack(fill="x", pady=(6, 0))
        self.v_down = tk.IntVar()
        self.v_fail = tk.IntVar()
        for lbl, var, col in [("DOWNLOADED", self.v_down, W.GREEN),
                              ("FAILED", self.v_fail, W.RED)]:
            b = ctk.CTkFrame(counters, fg_color="transparent")
            b.pack(side="left", expand=True)
            ctk.CTkLabel(b, textvariable=var, font=W.font(22, "bold"),
                         text_color=col).pack()
            ctk.CTkLabel(b, text=lbl, font=W.font(9, "bold"),
                         text_color=W.MUTED).pack()
        self.lbl_stats = ctk.CTkLabel(run.body, text="", text_color=W.MUTED,
                                      font=W.font(11))
        self.lbl_stats.pack(anchor="w", pady=(4, 0))
        self.progress = ctk.CTkProgressBar(run.body, progress_color=W.GREEN,
                                           corner_radius=0)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=4)
        ctl = ctk.CTkFrame(run.body, fg_color="transparent")
        ctl.pack(fill="x")
        self.stop_btn = W.primary_button(ctl, "Stop", self._stop, color=W.RED,
                                         hover=W.RED_DK, width=110, height=30)
        self.stop_btn.configure(state="disabled")
        self.stop_btn.pack(side="left")
        self.log = ctk.CTkTextbox(run.body, height=60, fg_color="#0d161e",
                                  text_color="#cfe3e0", font=W.font(11),
                                  corner_radius=0)
        self.log.pack(fill="x", pady=(8, 0))

        # ---- Options + album picker (between header and the Run bar) ----
        c = W.card(self, "Options")
        c.pack(side="top", fill="x", padx=16, pady=6)
        dr = ctk.CTkFrame(c.body, fg_color="transparent")
        dr.pack(fill="x")
        ctk.CTkLabel(dr, text="Destination folder", text_color=W.TEXT,
                     font=W.font(13, "bold")).pack(side="left")
        W.primary_button(dr, "Choose folder...", self._browse, color=W.BLUE,
                         hover=W.BLUE_DK, width=150).pack(side="right")
        self.dest_lbl = ctk.CTkLabel(c.body, text="No folder chosen yet.",
                                     text_color=W.MUTED, font=W.font(11),
                                     wraplength=620, justify="left")
        self.dest_lbl.pack(anchor="w", pady=(2, 1))
        self.space_lbl = ctk.CTkLabel(c.body, text="", text_color=W.MUTED,
                                      font=W.font(11))
        self.space_lbl.pack(anchor="w", pady=(0, 8))

        ar = ctk.CTkFrame(c.body, fg_color="transparent")
        ar.pack(fill="x")
        ctk.CTkLabel(ar, text="Albums to back up", text_color=W.TEXT,
                     font=W.font(13, "bold")).pack(side="left")
        self.toggle_mode = W.SquareToggle(
            ar, ["All albums", "Specific albums"], "All albums",
            command=self._on_mode)
        self.toggle_mode.pack(side="right")

        ctk.CTkLabel(c.body, text="Shared albums", text_color=W.TEXT,
                     font=W.font(13, "bold")).pack(anchor="w", pady=(12, 2))
        self.toggle_shared = W.SquareToggle(
            c.body, [n for n, _o, _d in _BK_SHARED], "All photos",
            command=self._shared_desc, width=130)
        self.toggle_shared.pack(anchor="w", pady=(2, 2))
        self.lbl_shared = ctk.CTkLabel(c.body, text="", text_color=W.MUTED,
                                       font=W.font(11), wraplength=620,
                                       justify="left")
        self.lbl_shared.pack(anchor="w")
        self._shared_desc("All photos")

        self.albums_card = W.card(self, "Albums (tick the ones to back up)")
        top = ctk.CTkFrame(self.albums_card.body, fg_color="transparent")
        top.pack(fill="x")
        W.primary_button(top, "Load albums", self._load, color=W.BLUE,
                         hover=W.BLUE_DK).pack(side="left")
        self.sel_count = ctk.CTkLabel(top, text="0 selected",
                                      text_color=W.GREEN, font=W.font(11,
                                                                      "bold"))
        self.sel_count.pack(side="left", padx=12)
        W.primary_button(top, "Uncheck all", lambda: self._set_all(False),
                         color=W.GREY, hover=W.GREY_DK, width=100,
                         height=30).pack(side="right")
        W.primary_button(top, "Check all", lambda: self._set_all(True),
                         color=W.GREY, hover=W.GREY_DK, width=90,
                         height=30).pack(side="right", padx=(0, 6))
        self.albums_box = ctk.CTkFrame(self.albums_card.body,
                                       fg_color="transparent")
        self.albums_box.pack(fill="both", expand=True, pady=(8, 0))
        ctk.CTkLabel(self.albums_box,
                     text="Click \"Load albums\" to choose what to back up.",
                     text_color=W.MUTED).pack(anchor="w", padx=8, pady=8)
        self._toggle_albums("All")
        W.fix_wrapping(self)

    # ---------------------------------------------------------- options
    def _shared_desc(self, name):
        d = {n: desc for n, _o, desc in _BK_SHARED}.get(name, "")
        self.lbl_shared.configure(text=d)

    def _on_mode(self, val):
        self._toggle_albums("Pick" if val == "Specific albums" else "All")

    def _toggle_albums(self, value):
        if value == "Pick":
            self.albums_card.pack(side="top", fill="both", expand=True,
                                  padx=16, pady=(0, 6))
        else:
            self.albums_card.pack_forget()

    def _browse(self):
        from synmich.gui.dialogs import prompt_folder
        d = prompt_folder(self, start=self.dest or None)
        if d:
            self.dest = d
            self.dest_lbl.configure(text=d, text_color=W.TEXT)
            try:
                import shutil
                free = shutil.disk_usage(d).free / (1024 ** 3)
                self.space_lbl.configure(
                    text=f"Free space here: {free:.1f} GB",
                    text_color=W.GREEN if free > 5 else W.ORANGE)
            except Exception:  # noqa: BLE001
                self.space_lbl.configure(text="")

    def _busy(self, on):
        if on:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)

    # ---------------------------------------------------------- albums
    def _precheck(self):
        if not self.cfg.get("synology", {}).get("url"):
            return "Set the Synology address in Settings (left panel) first."
        if not self.cfg.get("backup_accounts"):
            return ("No Synology account yet. Add one in the Settings panel "
                    "(left) before backing up.")
        return ""

    def _load(self):
        msg = self._precheck()
        if msg:
            self._set_log(msg)
            return
        self._busy(True)
        if not self.app.syno_sessions:
            self._set_log("Connecting to Synology...")
            self.app.connect_syno(self._after_connect)
        else:
            self._set_log("Loading albums...")
            threading.Thread(target=self._load_worker, daemon=True).start()

    def _after_connect(self, ok, msg):
        if ok:
            self._set_log("Connected. Loading albums...")
            threading.Thread(target=self._load_worker, daemon=True).start()
        else:
            self._busy(False)
            self._set_log(msg)

    def _load_worker(self):
        try:
            records = _build_records(self.app.syno_sessions)
        except Exception as e:  # noqa: BLE001
            self.after(0, lambda: (self._busy(False),
                                   self._set_log(f"Load albums failed: {e}")))
            return
        self.after(0, lambda: self._populate(records))

    def _populate(self, records):
        self._busy(False)
        self.records = records
        n = W.render_album_groups(
            self.albums_box, records, self.album_vars,
            on_change=self._update_count,
            empty_text="No album found for this account. Check the Synology "
                       "address and that the account has access to Photos.")
        self._update_count()
        if n:
            self._set_log(f"Loaded {n} album(s). Tick the ones to back up.")
        else:
            self._set_log("No album found.")

    def _update_count(self):
        n = sum(1 for v in self.album_vars.values() if v.get())
        self.sel_count.configure(text=f"{n} selected")

    def clear_albums(self):
        """Drop the loaded album list (e.g. after an account changed)."""
        self.album_vars = {}
        self.records = {}
        for w in self.albums_box.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.albums_box,
                     text="Click \"Load albums\" to choose what to back up.",
                     text_color=W.MUTED).pack(anchor="w", padx=8, pady=8)
        self.sel_count.configure(text="0 selected")

    def _set_all(self, value):
        for v in self.album_vars.values():
            v.set(value)
        self._update_count()

    # ---------------------------------------------------------- run
    def _start(self):
        if not self.dest:
            self._set_log("Choose a destination folder first.")
            return
        msg = self._precheck()
        if msg:
            self._set_log(msg)
            return
        if not self.app.syno_sessions:
            self._set_log("Connecting to Synology...")
            self.app.connect_syno(lambda ok, msg: self._launch() if ok
                                  else self._set_log(msg))
        else:
            self._launch()

    def _launch(self):
        all_mode = self.toggle_mode.get() == "All albums"
        owner_only = {n: o for n, o, _d in _BK_SHARED}.get(
            self.toggle_shared.get(), False)
        selected = {k for k, v in self.album_vars.items() if v.get()}
        if not all_mode and not selected:
            self._set_log("No album selected.")
            return
        self.stats = MigrationStats()
        self.control = MigrationControl()
        self.stats.start_time = time.time()
        self._log_count = 0
        self._done = False
        self.log.delete("1.0", "end")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        threading.Thread(
            target=run_backup,
            args=(self.app.syno_sessions, selected, all_mode, owner_only,
                  self.dest, self.stats, self.control), daemon=True).start()
        self._poll()

    def _poll(self):
        s = self.stats
        if s is None:
            return
        self.v_down.set(s.uploaded)
        self.v_fail.set(s.failed)
        el, eta, rate = (int(s.elapsed_seconds()), int(s.eta_seconds()),
                         s.rate_per_minute())
        cur = f"{s.current_album}    " if s.current_album else ""
        self.lbl_stats.configure(
            text=f"{cur}Albums {s.albums_done}/{s.albums_total}    "
                 f"Photos {s.items_done}/{s.items_total}    "
                 f"Elapsed {W.fmt_duration(el)}    "
                 f"ETA {W.fmt_duration(eta)}    {rate:.0f}/min")
        if s.items_total:
            self.progress.set(s.items_done / s.items_total)
        total = getattr(s, "total_messages_logged", len(s.last_messages))
        if total > self._log_count:
            new_n = min(total - self._log_count, len(s.last_messages))
            for m in s.last_messages[-new_n:]:
                self.log.insert("end", _plain(m) + "\n")
            self.log.see("end")
            self._log_count = total
        if s.current_step == "done" and not self._done:
            self._done = True
            self.progress.set(1)
            self.stop_btn.configure(state="disabled")
            self.start_btn.configure(state="normal")
            self.app.last_run = {"label": "Synology to local", "rows": [
                ("Downloaded", str(s.uploaded), W.GREEN),
                ("Failed", str(s.failed), W.RED),
                ("Albums", str(s.albums_done), W.TEXT),
                ("Total time", W.fmt_duration(el), W.MUTED)]}
            self._set_log(
                f"\nBackup complete - {s.uploaded} downloaded, "
                f"{s.failed} failed, {s.albums_done} album(s) in "
                f"{W.fmt_duration(el)}.\n"
                f"Saved to: {self.dest}")
        else:
            self.after(300, self._poll)

    def _stop(self):
        if self.control:
            self.control.stop()

    def _set_log(self, msg):
        self.log.insert("end", _plain(msg) + "\n")
        self.log.see("end")
