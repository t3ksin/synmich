"""First-launch onboarding modal (equivalent of `synmich init`)."""

from __future__ import annotations

import customtkinter as ctk

from synmich.config import save_config, validate_config
from synmich.gui import widgets as W


class FirstLaunchWizard(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.cfg = app.cfg
        self.title("Welcome to synmich")
        self.geometry("540x600")
        self.transient(app)
        self.after(120, self.grab_set)  # grab after the window is mapped

        ctk.CTkLabel(self, text="Welcome to synmich", font=W.font(22, "bold"),
                     text_color=W.GREEN).pack(pady=(22, 2))
        ctk.CTkLabel(self, text="Set up your first migration.",
                     text_color=W.MUTED).pack(pady=(0, 14))

        self.e_syno = self._field("Synology URL", "http://192.168.0.2:5000")
        self.e_immich = self._field("Immich URL", "http://192.168.0.2:2283")
        ctk.CTkLabel(self, text="FIRST USER", text_color=W.GREEN,
                     font=W.font(12, "bold")).pack(anchor="w", padx=26,
                                                   pady=(12, 2))
        self.e_name = self._field("Display name", "Me")
        self.e_suser = self._field("Synology username")
        self.e_spass = self._field("Synology password", secret=True)
        self.e_key = self._field("Immich API key", secret=True)

        self.err = ctk.CTkLabel(self, text="", text_color=W.RED)
        self.err.pack(pady=(6, 0))
        W.primary_button(self, "Save & continue", self._save, height=42).pack(
            fill="x", padx=26, pady=14)

    def _field(self, label, placeholder="", secret=False):
        ctk.CTkLabel(self, text=label, text_color=W.MUTED, anchor="w").pack(
            fill="x", padx=26)
        e = ctk.CTkEntry(self, placeholder_text=placeholder, corner_radius=0,
                         show="*" if secret else "")
        e.pack(fill="x", padx=26, pady=(2, 6))
        return e

    def _save(self):
        self.cfg.setdefault("synology", {})["url"] = self.e_syno.get().strip()
        self.cfg.setdefault("immich", {})["url"] = self.e_immich.get().strip()
        self.cfg["users"] = [{
            "name": self.e_name.get().strip() or "Me",
            "syno_username": self.e_suser.get().strip(),
            "syno_password": self.e_spass.get().strip(),
            "immich_api_key": self.e_key.get().strip(),
        }]
        errs = validate_config(self.cfg)
        if errs:
            self.err.configure(text=errs[0])
            return
        save_config(self.cfg)
        self.app.reload()
        self.destroy()
