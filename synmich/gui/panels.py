"""Stats and Doctor modals (opened from the left panel)."""

from __future__ import annotations

import threading

import customtkinter as ctk

from synmich.gui import widgets as W


def _modal(app, title, w=460, h=380):
    dlg = ctk.CTkToplevel(app)
    dlg.title(title)
    dlg.geometry(f"{w}x{h}")
    dlg.transient(app)
    dlg.lift()
    dlg.after(150, dlg.grab_set)
    ctk.CTkLabel(dlg, text=title, font=W.font(18, "bold"),
                 text_color=W.GREEN).pack(pady=(18, 10))
    return dlg


def _row(parent, label, value="", value_color=None):
    r = ctk.CTkFrame(parent, fg_color="transparent")
    r.pack(fill="x", padx=28, pady=4)
    ctk.CTkLabel(r, text=label, text_color=W.MUTED, anchor="w").pack(side="left")
    v = ctk.CTkLabel(r, text=value, text_color=value_color or W.TEXT,
                     font=W.font(14, "bold"))
    v.pack(side="right")
    return v


# Built-in / system accounts to hide from the "real users" list.
_SYSTEM_USERS = {"admin", "guest", "anonymous", "root"}


def _real_users(users):
    """Keep only real DSM users: drop built-in/system accounts (admin, guest,
    ...) and the low UID range DSM reserves for system accounts."""
    out = []
    for u in users:
        name = u.get("name", "")
        uid = u.get("uid", 0)
        if not name or name.lower() in _SYSTEM_USERS:
            continue
        if isinstance(uid, int) and uid and uid < 1026:
            continue
        out.append(name)
    return sorted(out, key=str.lower)


def show_nas_users(app, accounts_key):
    """Read-only list of the real Synology users on the NAS, with a count.
    Needs an admin account among the configured ones (Synology only - no
    Immich). System accounts (admin/guest/...) are hidden."""
    dlg = _modal(app, "Synology users", w=520, h=480)
    ctk.CTkLabel(dlg, text="Real users found on the NAS. System accounts "
                 "(admin, guest, service accounts) are hidden. This is just "
                 "for reference - it configures nothing.", text_color=W.MUTED,
                 font=W.font(11), wraplength=460, justify="left",
                 anchor="w").pack(fill="x", padx=22)
    scroll = W.scroll_frame(dlg, fg="transparent")
    scroll.pack(fill="both", expand=True, padx=18, pady=8)
    status = ctk.CTkLabel(scroll, text="Connecting to the NAS...",
                          text_color=W.MUTED, wraplength=440, justify="left")
    status.pack(anchor="w", padx=6, pady=8)
    W.primary_button(dlg, "Close", dlg.destroy, width=120).pack(pady=12)

    def worker():
        try:
            sessions = W.build_sessions(app.cfg, otp_provider=app._gui_otp,
                                        with_immich=False,
                                        accounts_key=accounts_key)
        except Exception as e:  # noqa: BLE001
            app.after(0, lambda err=e: status.configure(text=str(err),
                                                        text_color=W.RED))
            return
        names = []
        for s in sessions:
            try:
                names = _real_users(s.syno.list_dsm_users())
            except Exception:  # noqa: BLE001
                names = []
            if names:
                break

        def show():
            for w in scroll.winfo_children():
                w.destroy()
            if not names:
                ctk.CTkLabel(
                    scroll, text="Could not list users. This needs an admin "
                    "Synology account - make sure one of your configured "
                    "accounts is an administrator.", text_color=W.ORANGE,
                    wraplength=460, justify="left", anchor="w").pack(
                    fill="x", padx=6, pady=8)
                return
            ctk.CTkLabel(scroll, text=f"{len(names)} user(s) on the NAS",
                         text_color=W.GREEN, font=W.font(14, "bold")).pack(
                anchor="w", padx=6, pady=(4, 8))
            for n in names:
                ctk.CTkLabel(scroll, text=f"  -  {n}", text_color=W.TEXT,
                             anchor="w").pack(fill="x", padx=8, pady=2)
        app.after(0, show)

    threading.Thread(target=worker, daemon=True).start()
    W.fix_wrapping(dlg)


def _section(parent, text):
    ctk.CTkLabel(parent, text=text.upper(), text_color=W.GREEN,
                 font=W.font(12, "bold")).pack(anchor="w", padx=28,
                                               pady=(14, 2))


def show_stats(app):
    """Two views: the last run of this session, and the saved cumulative
    progress (the checkpoint, kept across runs so migrations can resume)."""
    from synmich.core.checkpoint import Checkpoint

    dlg = _modal(app, "Stats", h=560)

    _section(dlg, "Last run (this session)")
    lr = getattr(app, "last_run", None)
    if not lr:
        ctk.CTkLabel(dlg, text="No migration or backup has run yet in this "
                     "session.", text_color=W.MUTED, wraplength=400,
                     justify="left", anchor="w").pack(fill="x", padx=28)
    else:
        ctk.CTkLabel(dlg, text=lr["label"], text_color=W.MUTED,
                     font=W.font(11), anchor="w").pack(fill="x", padx=28)
        for label, val, col in lr["rows"]:
            _row(dlg, label, val, col)

    _section(dlg, "Saved progress (all runs)")
    try:
        s = Checkpoint(config=app.cfg).get_summary()
    except Exception:  # noqa: BLE001
        s = {}
    _row(dlg, "Photos uploaded", str(s.get("uploaded", 0)), W.GREEN)
    _row(dlg, "Duplicates", str(s.get("duplicate", 0)), W.BLUE)
    _row(dlg, "Failed", str(s.get("failed", 0)), W.RED)
    _row(dlg, "Albums done", str(s.get("albums_done", 0)))
    _row(dlg, "Skipped (already done)", str(s.get("skipped", 0)))
    users = ", ".join(s.get("users", [])) or "None yet"
    _row(dlg, "Users", users)
    W.primary_button(dlg, "Close", dlg.destroy, width=120).pack(pady=16)
    W.fix_wrapping(dlg)


def show_reset(app):
    """Scoped reset. Never touches any photo - only synmich's own local files:
    the saved progress, the 2FA device tokens, and/or the configuration."""
    from synmich.config import save_config
    from synmich.core.checkpoint import Checkpoint
    from synmich.core.device_tokens import _tokens_path

    dlg = _modal(app, "Reset", w=580, h=620)
    ctk.CTkLabel(dlg, text="No photo is ever touched - this only clears "
                 "synmich's own local files on this computer.",
                 text_color=W.MUTED, font=W.font(11), wraplength=520,
                 justify="left", anchor="w").pack(fill="x", padx=22)
    scroll = W.scroll_frame(dlg, fg="transparent")
    scroll.pack(fill="both", expand=True, padx=14, pady=8)
    status = ctk.CTkLabel(dlg, text="", text_color=W.GREEN, font=W.font(12),
                          wraplength=520, justify="left", anchor="w")

    def _card(title, desc, btn_text, color, hover, action):
        c = W.card(scroll, title)
        c.pack(fill="x", pady=6)
        ctk.CTkLabel(c.body, text=desc, text_color=W.MUTED, font=W.font(11),
                     wraplength=490, justify="left", anchor="w").pack(
            fill="x", pady=(0, 8))
        W.primary_button(c.body, btn_text, action, color=color,
                         hover=hover).pack(fill="x")

    def _reset_progress():
        Checkpoint(config=app.cfg).reset()
        app.last_run = None

    def _reset_tokens():
        _tokens_path().unlink(missing_ok=True)

    def _reset_config():
        app.cfg["synology"] = {"url": "", "verify_ssl": False}
        app.cfg["immich"] = {"url": ""}
        app.cfg["users"] = []
        app.cfg["backup_accounts"] = []
        save_config(app.cfg)
        app.sessions = []
        app.users_syno_sessions = []
        app.syno_sessions = []
        app.immich_clients = []

    def progress():
        try:
            _reset_progress()
            status.configure(text="Migration progress reset.",
                             text_color=W.GREEN)
        except Exception as e:  # noqa: BLE001
            status.configure(text=f"Failed: {e}", text_color=W.RED)

    def tokens():
        try:
            _reset_tokens()
            status.configure(text="Saved 2FA devices forgotten - the code "
                             "will be asked again next time.",
                             text_color=W.GREEN)
        except Exception as e:  # noqa: BLE001
            status.configure(text=f"Failed: {e}", text_color=W.RED)

    def config():
        _reset_config()
        dlg.destroy()
        app.reload()

    def everything():
        for fn in (_reset_progress, _reset_tokens):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        _reset_config()
        dlg.destroy()
        app.reload()

    _card("Migration progress",
          "Forget what has already been migrated. The next run re-checks "
          "every photo. Your servers and accounts are kept.",
          "Reset progress", W.ORANGE, W.ORANGE_DK, progress)
    _card("Two-factor (saved devices)",
          "Forget the saved 2FA device tokens. Accounts with 2-step "
          "verification will ask for a code again next time.",
          "Reset 2FA devices", W.ORANGE, W.ORANGE_DK, tokens)
    _card("Configuration",
          "Remove your Synology/Immich addresses and all accounts. You will "
          "set them up again. Saved progress is kept.",
          "Reset configuration", W.RED, W.RED_DK, config)
    _card("Everything",
          "Reset all of the above at once: progress, 2FA devices and "
          "configuration - a clean start. (Still no photos touched.)",
          "Reset everything", W.RED, W.RED_DK, everything)

    status.pack(fill="x", padx=22, pady=(4, 0))
    W.primary_button(dlg, "Close", dlg.destroy, color=W.GREY, hover=W.GREY_DK,
                     width=120).pack(pady=10)
    W.fix_wrapping(dlg)


def _check_row(parent, label):
    """A diagnostic row: bold label + status on the right + detail below."""
    row = ctk.CTkFrame(parent, fg_color=W.CARD, corner_radius=0)
    row.pack(fill="x", pady=3)
    head = ctk.CTkFrame(row, fg_color="transparent")
    head.pack(fill="x", padx=12, pady=(8, 0))
    ctk.CTkLabel(head, text=label, text_color=W.TEXT, anchor="w",
                 font=W.font(13, "bold")).pack(side="left")
    st = ctk.CTkLabel(head, text="...", text_color=W.MUTED,
                      font=W.font(13, "bold"))
    st.pack(side="right")
    detail = ctk.CTkLabel(row, text="", text_color=W.MUTED, font=W.font(11),
                          wraplength=480, justify="left", anchor="w")
    detail.pack(fill="x", padx=12, pady=(0, 8))
    return st, detail


def show_doctor(app):
    """Thorough diagnostic: servers, config (with reasons), per-account
    login (Synology + Immich), and free disk space."""
    dlg = _modal(app, "Doctor", w=580, h=560)
    scroll = W.scroll_frame(dlg, fg="transparent")
    scroll.pack(fill="both", expand=True, padx=14, pady=4)
    btns = ctk.CTkFrame(dlg, fg_color="transparent")
    btns.pack(pady=12)
    W.primary_button(btns, "Reset...", lambda: show_reset(app), color=W.GREY,
                     hover=W.GREY_DK, width=140).pack(side="left", padx=6)
    W.primary_button(btns, "Close", dlg.destroy, width=120).pack(side="left",
                                                                 padx=6)

    rows = {}
    for key, label in [("syno", "Synology server"),
                       ("immich", "Immich server"),
                       ("cfg", "Configuration"),
                       ("accounts", "Account logins"),
                       ("disk", "Free disk space")]:
        rows[key] = _check_row(scroll, label)

    def set_row(key, state, detail=""):
        st, dt = rows[key]
        colors = {"ok": W.GREEN, "fail": W.RED, "warn": W.ORANGE}
        st.configure(text=state.upper(), text_color=colors.get(state, W.MUTED))
        dt.configure(text=detail,
                     text_color=W.MUTED if state == "ok" else colors.get(state))

    def after(key, state, detail=""):
        try:
            dlg.after(0, lambda: set_row(key, state, detail))
        except Exception:  # noqa: BLE001
            pass

    def worker():
        import shutil
        from pathlib import Path

        import requests
        import urllib3
        urllib3.disable_warnings()
        from synmich.core.immich import ImmichClient
        from synmich.core.synology import SynologyClient

        cfg = app.cfg

        def reach(url):
            try:
                return requests.get(url, timeout=5,
                                    verify=False).status_code < 500
            except Exception:  # noqa: BLE001
                return False

        syno_url = cfg.get("synology", {}).get("url", "")
        immich_url = cfg.get("immich", {}).get("url", "")
        verify = cfg.get("synology", {}).get("verify_ssl", False)

        if not syno_url:
            after("syno", "fail", "No Synology address set in Settings.")
        else:
            after("syno", "ok" if reach(syno_url) else "fail",
                  syno_url if reach(syno_url) else f"Cannot reach {syno_url}.")

        if not immich_url:
            after("immich", "warn", "No Immich address (only needed for "
                                    "Synology to Immich).")
        else:
            after("immich", "ok" if reach(immich_url) else "fail",
                  immich_url if reach(immich_url)
                  else f"Cannot reach {immich_url}.")

        issues = W.friendly_config(cfg)
        after("cfg", "ok" if not issues else "fail",
              "All required fields are set." if not issues
              else "\n".join("- " + i for i in issues))

        users = cfg.get("users", [])
        backups = cfg.get("backup_accounts", [])
        if not users and not backups:
            after("accounts", "fail", "No account configured.")
        else:
            details, all_ok = [], True

            def check_syno(u, who):
                sc = SynologyClient(syno_url, verify_ssl=verify)
                return sc.login(u.get("syno_username", ""),
                                u.get("syno_password", ""))

            if users:
                details.append("Synology to Immich:")
            for u in users:
                who = u.get("syno_username") or u.get("name") or "user"
                try:
                    if not check_syno(u, who):
                        details.append(f"  {who}: Synology login failed")
                        all_ok = False
                        continue
                    key = u.get("immich_api_key", "")
                    if key and immich_url:
                        try:
                            ImmichClient(immich_url, key).me()
                            details.append(f"  {who}: OK (Synology + Immich)")
                        except Exception:  # noqa: BLE001
                            details.append(f"  {who}: Immich API key invalid")
                            all_ok = False
                    else:
                        details.append(f"  {who}: no Immich API key")
                        all_ok = False
                except Exception as e:  # noqa: BLE001
                    details.append(f"  {who}: {e}")
                    all_ok = False

            if backups:
                details.append("Synology to local:")
            for u in backups:
                who = u.get("syno_username") or u.get("name") or "account"
                try:
                    if check_syno(u, who):
                        details.append(f"  {who}: OK (Synology)")
                    else:
                        details.append(f"  {who}: Synology login failed")
                        all_ok = False
                except Exception as e:  # noqa: BLE001
                    details.append(f"  {who}: {e}")
                    all_ok = False
            after("accounts", "ok" if all_ok else "fail", "\n".join(details))

        try:
            free = shutil.disk_usage(str(Path.home())).free / (1024 ** 3)
            after("disk", "ok" if free > 5 else "warn",
                  f"{free:.1f} GB free at {Path.home()}")
        except Exception:  # noqa: BLE001
            after("disk", "warn", "Cannot read disk usage.")

    W.fix_wrapping(dlg)
    threading.Thread(target=worker, daemon=True).start()
