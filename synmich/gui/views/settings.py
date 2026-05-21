"""Settings panel - servers + users, test connection, save configuration."""

from __future__ import annotations

import customtkinter as ctk

from synmich.config import save_config
from synmich.gui import widgets as W
from synmich.gui.dialogs import prompt_user


class SettingsView(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.cfg = app.cfg
        for k in ("synology", "immich"):
            self.cfg.setdefault(k, {})
        self.cfg.setdefault("users", [])
        self.cfg.setdefault("backup_accounts", [])
        self._use_immich = True
        self._mode = "migrate"   # migrate | manage | backup (per active tab)
        # Which account list the panel manages: "users" (Immich migration,
        # with API keys) or "backup_accounts" (local backup, Synology only).
        self._accounts_key = "users"

        ctk.CTkLabel(self, text="Settings", font=W.font(18, "bold"),
                     text_color=W.TEXT).pack(anchor="w", padx=18, pady=(6, 0))
        self.banner = ctk.CTkLabel(self, text="", font=W.font(12),
                                   text_color=W.ORANGE, wraplength=320,
                                   justify="left")
        self.banner.pack(anchor="w", padx=18)

        scroll = W.scroll_frame(self, fg="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Servers ---
        c = W.card(scroll, "Servers")
        c.pack(fill="x", pady=8)
        ctk.CTkLabel(c.body, text="Synology address (with port)",
                     text_color=W.MUTED, anchor="w").pack(fill="x")
        self.e_syno = ctk.CTkEntry(c.body, corner_radius=0,
                                   placeholder_text="e.g. 192.168.0.2:5000")
        self.e_syno.pack(fill="x", pady=(2, 10))
        self.e_syno.insert(0, self.cfg["synology"].get("url", ""))
        self.immich_lbl = ctk.CTkLabel(c.body, text="Immich address (with port)",
                                       text_color=W.MUTED, anchor="w")
        self.immich_lbl.pack(fill="x")
        self.e_immich = ctk.CTkEntry(c.body, corner_radius=0,
                                     placeholder_text="e.g. 192.168.0.2:2283")
        self.e_immich.pack(fill="x", pady=(2, 10))
        self.e_immich.insert(0, self.cfg["immich"].get("url", ""))
        self.var_verify = ctk.BooleanVar(
            value=self.cfg["synology"].get("verify_ssl", False))
        self.verify_sw = ctk.CTkCheckBox(
            c.body, text="Verify SSL certificate", variable=self.var_verify,
            fg_color=W.GREEN, hover_color=W.GREEN_DK, checkbox_width=20,
            checkbox_height=20, corner_radius=0, border_width=2,
            font=W.font(12))
        self.verify_sw.pack(anchor="w", pady=6)

        # --- Users ---
        c = W.card(scroll, "Users")
        c.pack(fill="x", pady=8)
        self.users_hint = ctk.CTkLabel(
            c.body, text="Users whose photos will be migrated to Immich "
                         "(each needs an Immich API key).",
            text_color=W.MUTED, font=W.font(11), wraplength=320,
            justify="left", anchor="w")
        self.users_hint.pack(fill="x", pady=(0, 6))
        self.users_count = ctk.CTkLabel(c.body, text="", text_color=W.GREEN,
                                        font=W.font(11, "bold"), anchor="w")
        self.users_count.pack(fill="x", pady=(0, 4))
        self.users_box = ctk.CTkFrame(c.body, fg_color="transparent")
        self.users_box.pack(fill="x")
        self.add_btn = W.primary_button(c.body, "+  Add user", self._add_user)
        self.add_btn.pack(fill="x", pady=(10, 0))
        W.primary_button(c.body, "Check NAS users", self._check_nas,
                         color=W.BLUE, hover=W.BLUE_DK).pack(fill="x",
                                                             pady=(6, 0))

        # --- Actions ---
        c = W.card(scroll)
        c.pack(fill="x", pady=8)
        W.primary_button(c.body, "Save settings", self._save).pack(fill="x")
        ctk.CTkLabel(
            c.body,
            text="Saves your addresses and accounts on this computer so "
                 "synmich remembers them next time (no photos involved). "
                 "Connections are checked when you add an account.",
            text_color=W.MUTED, font=W.font(10), wraplength=320,
            justify="left").pack(anchor="w", pady=(6, 0))
        self.status = ctk.CTkLabel(c.body, text="", text_color=W.MUTED,
                                   font=W.font(12), wraplength=320,
                                   justify="left")
        self.status.pack(anchor="w", fill="x", pady=(8, 0))
        W.primary_button(c.body, "Reset...", self._reset, color=W.GREY,
                         hover=W.GREY_DK).pack(fill="x", pady=(10, 0))

        self._refresh_users()
        W.fix_wrapping(self)

    # --------------------------------------------------- context (immich)
    # Per-tab text for the Users section so the panel reads coherently.
    _CONTEXT = {
        "Synology to Immich": (
            "migrate", "+  Add user",
            "Users whose photos will be migrated to Immich. Each one needs "
            "its Synology login and that same user's Immich API key."),
        "Immich Album Manager": (
            "manage", "+  Add Immich user",
            "The Immich users whose albums you want to manage. Each one uses "
            "only its Immich API key - no Synology login."),
        "Synology to local": (
            "backup", "+  Add Synology account",
            "Synology accounts whose albums you want to back up to this "
            "computer. Synology login only - no Immich API key."),
    }

    def set_context(self, tab: str):
        """Switch the panel to the active tab. 'Synology to Immich' and the
        'Immich Album Manager' both use the `users` list (with API keys);
        'Synology to local' uses the separate `backup_accounts` list (Synology
        only). The Immich address is hidden when the tab doesn't use Immich,
        and the Users hint is tailored to the tab so it reads coherently."""
        mode, add_text, hint = self._CONTEXT.get(
            tab, self._CONTEXT["Synology to Immich"])
        self._mode = mode
        use_immich = mode in ("migrate", "manage")
        self._use_immich = use_immich
        self._accounts_key = "users" if use_immich else "backup_accounts"
        self.cfg.setdefault(self._accounts_key, [])
        shown = self.e_immich.winfo_manager() != ""
        if use_immich and not shown:
            self.immich_lbl.pack(fill="x", before=self.verify_sw)
            self.e_immich.pack(fill="x", pady=(2, 10), before=self.verify_sw)
        elif not use_immich and shown:
            self.immich_lbl.pack_forget()
            self.e_immich.pack_forget()
        self.add_btn.configure(text=add_text)
        self.users_hint.configure(text=hint)
        self._refresh_users()

    def set_welcome(self, text):
        self.banner.configure(text=text)

    # --------------------------------------------------------- users
    def _refresh_users(self):
        for w in self.users_box.winfo_children():
            w.destroy()
        accounts = self.cfg.get(self._accounts_key, [])
        word = "user" if self._use_immich else "account"
        n = len(accounts)
        self.users_count.configure(
            text=f"{n} {word}{'' if n == 1 else 's'} configured")
        if not accounts:
            txt = ("No user yet. Add an account below (needs an Immich "
                   "API key)." if self._use_immich
                   else "No account yet. Add a Synology account below.")
            lbl = ctk.CTkLabel(self.users_box, text=txt, text_color=W.MUTED,
                               wraplength=320, justify="left")
            lbl.pack(fill="x")
            W.auto_wrap(lbl)
            return
        for i, u in enumerate(accounts):
            row = ctk.CTkFrame(self.users_box, fg_color=W.HOVER,
                               corner_radius=0)
            row.pack(fill="x", pady=3)
            # Buttons packed right-first so they're never clipped.
            W.primary_button(row, "Remove", lambda i=i: self._remove_user(i),
                             color=W.RED, hover=W.RED_DK, width=74,
                             height=28).pack(side="right", padx=(4, 6), pady=6)
            W.primary_button(row, "Edit", lambda i=i: self._edit_user(i),
                             color=W.BLUE, hover=W.BLUE_DK, width=56,
                             height=28).pack(side="right", pady=6)
            ctk.CTkLabel(
                row, text=f"  {u.get('syno_username') or u.get('name') or '?'}",
                anchor="w", text_color=W.TEXT, font=W.font(13, "bold")).pack(
                side="left", fill="x", expand=True, padx=6)

    def _dialog_urls(self):
        self._pull()
        return dict(
            mode=self._mode,
            syno_url=self.cfg["synology"].get("url", ""),
            verify=self.cfg["synology"].get("verify_ssl", False),
            immich_url=self.cfg["immich"].get("url", ""),
            otp_provider=self.app._gui_otp)

    def _add_user(self):
        u = prompt_user(self, None, **self._dialog_urls())
        if u:
            self.cfg.setdefault(self._accounts_key, []).append(u)
            save_config(self.cfg)
            self.app.invalidate_sessions()
            self._refresh_users()

    def _edit_user(self, i):
        u = prompt_user(self, self.cfg[self._accounts_key][i],
                        **self._dialog_urls())
        if u:
            self.cfg[self._accounts_key][i] = u
            save_config(self.cfg)
            self.app.invalidate_sessions()
            self._refresh_users()

    def _remove_user(self, i):
        del self.cfg[self._accounts_key][i]
        save_config(self.cfg)
        self.app.invalidate_sessions()
        self._refresh_users()

    # --------------------------------------------------------- config
    def _pull(self):
        self.cfg["synology"]["url"] = W.normalize_url(self.e_syno.get())
        self.cfg["synology"]["verify_ssl"] = bool(self.var_verify.get())
        self.cfg["immich"]["url"] = W.normalize_url(self.e_immich.get())

    def _validate_syno(self):
        if not self.cfg["synology"].get("url"):
            return "Enter the Synology address."
        accounts = self.cfg.get("backup_accounts", [])
        if not accounts:
            return "Add at least one Synology account."
        for u in accounts:
            if not u.get("syno_username") or not u.get("syno_password"):
                return "Each account needs a Synology username and password."
        return ""

    def _check(self):
        # Local backup (no Immich) only needs Synology + accounts.
        if self._use_immich:
            issues = W.friendly_config(self.cfg)
            return issues[0] if issues else ""
        return self._validate_syno()

    def _reset(self):
        from synmich.gui.panels import show_reset
        show_reset(self.app)

    def _check_nas(self):
        self._pull()
        from synmich.gui.panels import show_nas_users
        show_nas_users(self.app, self._accounts_key)

    def _save(self):
        self._pull()
        msg = self._check()
        if msg:
            self.status.configure(text=msg, text_color=W.RED)
            return
        save_config(self.cfg)
        self.app.invalidate_sessions()
        self.status.configure(text="Settings saved.", text_color=W.GREEN)
