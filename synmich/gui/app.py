"""synmich GUI - CustomTkinter app.

Layout:
  LEFT  = settings / parameters panel (servers + users), always visible.
          The Immich URL is hidden on the "Synology to local" tab (unused).
  RIGHT = top tabs for the operations (Synology to Immich, Synology to local,
          Albums, Stats, Doctor). Each operation tab carries its own options.
"""

from __future__ import annotations

import os
import threading

import customtkinter as ctk

from synmich import __version__
from synmich.config import DEFAULT_CONFIG, load_config, validate_config
from synmich.gui import widgets as W
from synmich.gui.panels import show_doctor, show_stats
from synmich.gui.views.albums import AlbumsView
from synmich.gui.views.backup import BackupView
from synmich.gui.views.migration import MigrationView
from synmich.gui.views.settings import SettingsView
from synmich.gui.wizard_modal import FirstLaunchWizard
from synmich.logging_setup import setup_logging

_VER = __version__  # full version string shown in the title / brand
TAB_IMMICH = "Synology to Immich"
TAB_LOCAL = "Synology to local"
TAB_ALBUMS = "Immich Album Manager"

# Per-mode tab colours so the three top tabs read as three distinct modes.
# Each entry is (active bright colour, inactive dim, inactive hover).
TAB_COLORS = {
    TAB_IMMICH: ("#1D9E75", "#1c5a46", "#227a5d"),   # green  - migrate to Immich
    TAB_LOCAL:  ("#3d82d1", "#274d77", "#356a9e"),   # blue   - local backup
    TAB_ALBUMS: ("#EF9F27", "#7a5a26", "#a87b2f"),   # amber  - album manager
}


def _default_cfg():
    return {
        k: (dict(v) if isinstance(v, dict)
            else (list(v) if isinstance(v, list) else v))
        for k, v in DEFAULT_CONFIG.items()
    }


class SynmichApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(f"synmich {_VER}")
        # App icon: the brand "S" gradient, replacing the default Tk/Python
        # icon in the title bar and taskbar.
        try:
            from PIL import Image, ImageTk
            icon_path = os.path.join(os.path.dirname(__file__), "assets",
                                     "icon.png")
            self._icon_img = ImageTk.PhotoImage(Image.open(icon_path))
            self.iconphoto(True, self._icon_img)
        except Exception:  # noqa: BLE001
            pass
        # Comfortable windowed size (~1800x1140), but never larger than the
        # screen so it fits smaller laptops too - otherwise the WM would push
        # the bottom off-screen. Clamped to at least the minimum size.
        self.minsize(1050, 680)
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w = max(1050, min(1800, int(sw * 0.90)))
            h = max(680, min(1140, int(sh * 0.90)))
            self.geometry(f"{w}x{h}")
        except Exception:  # noqa: BLE001
            self.geometry("1400x900")
        self.configure(fg_color=W.CONTENT)

        self.cfg = load_config() or _default_cfg()
        for k in ("synology", "immich", "migration"):
            self.cfg.setdefault(k, {})
        self.cfg.setdefault("users", [])           # Immich migration (+ keys)
        self.cfg.setdefault("backup_accounts", [])  # local backup (Synology)

        self.sessions = []             # users + Immich (migration run)
        self.users_syno_sessions = []  # users, Synology-only (album listing)
        self.syno_sessions = []        # backup_accounts, Synology-only (backup)
        self.immich_clients = []       # users' Immich clients (Album Manager)
        self.last_run = None           # snapshot of the last finished run
        self.stats = None
        self.control = None
        self._last_tab = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build()
        self._watch_tab()

        if validate_config(self.cfg):  # not usable yet -> onboarding
            self.after(400, lambda: FirstLaunchWizard(self))

    # ------------------------------------------------------------- build
    def _build(self):
        # LEFT = parameters panel
        self._left = ctk.CTkFrame(self, width=430, corner_radius=0,
                                  fg_color=W.SIDEBAR)
        self._left.grid(row=0, column=0, sticky="nsw")
        self._left.grid_propagate(False)
        brand = ctk.CTkFrame(self._left, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(20, 0))
        # The gradient wordmark (same design as the README / CLI banner);
        # falls back to a large text title if the image can't be loaded.
        logo_ok = False
        try:
            from PIL import Image
            logo_path = os.path.join(os.path.dirname(__file__), "assets",
                                     "logo.png")
            self._logo_img = ctk.CTkImage(Image.open(logo_path),
                                          size=(320, 80))
            ctk.CTkLabel(brand, image=self._logo_img, text="").pack(side="left")
            logo_ok = True
        except Exception:  # noqa: BLE001
            ctk.CTkLabel(brand, text="synmich", font=W.font(38, "bold"),
                         text_color="white").pack(side="left")
        ctk.CTkLabel(brand, text=f" {_VER}", font=W.font(13, "bold"),
                     text_color=W.GREEN).pack(side="left",
                                              pady=(28, 0) if logo_ok
                                              else (16, 0))
        ctk.CTkLabel(self._left, text="Migrate & back up your Synology Photos",
                     font=W.font(11), text_color=W.MUTED).pack(
            anchor="w", padx=20, pady=(0, 8))
        # Stats / Doctor pinned at the bottom of the left panel.
        footer = ctk.CTkFrame(self._left, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=14, pady=12)
        W.primary_button(footer, "Stats", lambda: show_stats(self),
                         color=W.GREY, hover=W.GREY_DK).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        W.primary_button(footer, "Doctor", lambda: show_doctor(self),
                         color=W.GREY, hover=W.GREY_DK).pack(
            side="left", expand=True, fill="x", padx=(4, 0))
        self.settings = SettingsView(self._left, self)
        self.settings.pack(fill="both", expand=True)

        # RIGHT = operation tabs (top)
        self.tabview = ctk.CTkTabview(
            self, corner_radius=0, fg_color=W.CONTENT,
            command=self._recolor_tabs,
            segmented_button_fg_color=W.CONTENT,
            text_color="white")
        self.tabview.grid(row=0, column=1, sticky="nsew")
        self.migration_view = MigrationView(self.tabview.add(TAB_IMMICH), self)
        self.migration_view.pack(fill="both", expand=True)
        self.backup_view = BackupView(self.tabview.add(TAB_LOCAL), self)
        self.backup_view.pack(fill="both", expand=True)
        self.albums_view = AlbumsView(self.tabview.add(TAB_ALBUMS), self)
        self.albums_view.pack(fill="both", expand=True)
        self.tabview.set(TAB_IMMICH)
        # Make the 3 main tabs stand out: taller, bolder, brand-green when
        # active, and clearly spaced apart (these are the app's primary nav).
        try:
            sb = self.tabview._segmented_button
            # fg_color = content bg, so the gaps between tabs show the dark
            # background and each tab reads as a separate button.
            sb.configure(font=W.font(16, "bold"), height=46, corner_radius=0,
                         border_width=0, fg_color=W.CONTENT)
            for btn in sb._buttons_dict.values():
                btn.configure(corner_radius=0)
                btn.grid_configure(padx=6)
            sb.grid_configure(pady=(6, 10), padx=8)
        except Exception:  # noqa: BLE001
            pass
        self._recolor_tabs()

    def _recolor_tabs(self, *_):
        """Colour each top tab with its own mode colour: the active tab in its
        bright brand colour, the others in a dimmed version of that colour, so
        the three modes are visually distinct."""
        try:
            sb = self.tabview._segmented_button
            active = self.tabview.get()
        except Exception:  # noqa: BLE001
            return
        for name, btn in sb._buttons_dict.items():
            col = TAB_COLORS.get(name)
            if not col:
                continue
            bright, dim, hover = col
            if name == active:
                btn.configure(fg_color=bright, hover_color=bright,
                              text_color="white")
            else:
                btn.configure(fg_color=dim, hover_color=hover,
                              text_color="#d4dde6")

    def _watch_tab(self):
        try:
            tab = self.tabview.get()
        except Exception:  # noqa: BLE001
            tab = None
        if tab and tab != self._last_tab:
            self._last_tab = tab
            self.settings.set_context(tab)
            self._recolor_tabs()
        self.after(300, self._watch_tab)

    def reload(self):
        self._left.destroy()
        self.tabview.destroy()
        self._last_tab = None
        self._build()

    def invalidate_sessions(self):
        """Drop all cached logins so the next action reconnects with the
        current servers/accounts (e.g. after adding or editing an account),
        and clear any already-loaded album lists (now stale)."""
        self.sessions = []
        self.users_syno_sessions = []
        self.syno_sessions = []
        self.immich_clients = []
        for v in (getattr(self, "migration_view", None),
                  getattr(self, "backup_view", None),
                  getattr(self, "albums_view", None)):
            if v is not None:
                try:
                    v.clear_albums()
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------- 2FA
    def _gui_otp(self, username):
        box, done = {}, threading.Event()

        def ask():
            from synmich.gui.dialogs import prompt_otp
            box["code"] = prompt_otp(self, username)
            done.set()

        self.after(0, ask)
        done.wait()
        return box.get("code") or ""

    # ------------------------------------------------------------- connect
    def connect(self, callback):
        """Full connect (Synology + Immich) of the migration users."""
        self._do_connect(callback, with_immich=True, attr="sessions",
                         accounts_key="users")

    def connect_users_syno(self, callback):
        """Synology-only login of the migration users, so albums can be listed
        without requiring each user's Immich API key."""
        self._do_connect(callback, with_immich=False,
                         attr="users_syno_sessions", accounts_key="users")

    def connect_syno(self, callback):
        """Synology-only login of the local-backup accounts."""
        self._do_connect(callback, with_immich=False, attr="syno_sessions",
                         accounts_key="backup_accounts")

    def connect_immich(self, callback):
        """Immich-only connect (no Synology), for the Album Manager. Uses the
        API keys already entered for the Synology to Immich users."""
        def worker():
            try:
                clients = W.build_immich_clients(self.cfg)
                self.immich_clients = clients
                self.after(0, lambda: callback(
                    True, f"Connected - {len(clients)} account(s)"))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda err=e: callback(False, str(err)))
        threading.Thread(target=worker, daemon=True).start()

    def _do_connect(self, callback, with_immich, attr, accounts_key):
        def worker():
            try:
                s = W.build_sessions(self.cfg, otp_provider=self._gui_otp,
                                     with_immich=with_immich,
                                     accounts_key=accounts_key)
                setattr(self, attr, s)
                self.after(0, lambda: callback(
                    True, f"Connected - {len(s)} user(s)"))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda err=e: callback(False, str(err)))
        threading.Thread(target=worker, daemon=True).start()


def run_gui() -> int:
    setup_logging()
    SynmichApp().mainloop()
    return 0
