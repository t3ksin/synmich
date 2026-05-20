"""Small modal dialogs for the synmich GUI."""

from __future__ import annotations

import threading

import customtkinter as ctk

from synmich.gui import widgets as W


def _test_account(syno_url, verify, immich_url, vals, with_immich,
                  otp_provider=None):
    """Try to log in with the given credentials. Returns (ok, message)."""
    from synmich.core.synology import SynologyClient
    from synmich.gui.widgets import normalize_url

    syno_url = normalize_url(syno_url)
    immich_url = normalize_url(immich_url)
    if not syno_url:
        return False, "Enter the Synology address or IP in Settings first."
    # With no OTP provider, a 2FA prompt fails fast instead of hanging; when
    # one is supplied (from the app), 2FA accounts can be added graphically.
    otp_provider = otp_provider or (lambda _u: "")
    try:
        sc = SynologyClient(syno_url, verify_ssl=verify)
        if not sc.login(vals.get("syno_username", ""),
                        vals.get("syno_password", ""),
                        otp_provider=otp_provider):
            return False, ("Synology login failed - check the username and "
                           "password. If this account uses 2-step "
                           "verification, enter the code when prompted.")
    except Exception as e:  # noqa: BLE001
        return False, f"Synology error: {e}"

    if with_immich:
        key = vals.get("immich_api_key", "")
        if not key:
            return False, "Immich API key is required for migration."
        if immich_url:
            from synmich.core.immich import ImmichClient
            try:
                ImmichClient(immich_url, key).me()
            except Exception:  # noqa: BLE001
                return False, ("Immich API key invalid - check the key and "
                               "the Immich address.")
    return True, ""


def prompt_user(parent, existing=None, with_immich=True, syno_url="",
                verify=False, immich_url="", otp_provider=None) -> dict | None:
    """Modal form to add/edit an account; tests the connection on OK.

    The account is only accepted once Synology (and Immich, if with_immich)
    log in successfully. with_immich=False hides the Immich API key field.
    """
    kind = "Immich account" if with_immich else "Synology account"
    add_label = "Save" if existing else "Add account"
    dlg = ctk.CTkToplevel(parent)
    dlg.title(("Edit " if existing else "Add ") + ("an " if with_immich
              else "a ") + kind)
    dlg.geometry("470x460" if with_immich else "470x390")
    dlg.transient(parent)
    dlg.lift()
    # Delayed grab_set: calling it immediately on a CTkToplevel greys out
    # the window (known CustomTkinter rendering bug).
    dlg.after(150, dlg.grab_set)

    ctk.CTkLabel(dlg, text=("Edit " if existing else "Add ") + ("an "
                 if with_immich else "a ") + kind,
                 font=W.font(18, "bold"), text_color=W.GREEN).pack(pady=(18, 2))
    hint = ("Synology login + this user's Immich API key (used to migrate "
            "their photos to Immich)." if with_immich
            else "Synology login only - no Immich key needed for local backup.")
    ctk.CTkLabel(dlg, text=hint, text_color=W.MUTED, font=W.font(11),
                 wraplength=420, justify="left").pack(padx=22, pady=(0, 8))
    fields = [
        ("Synology username", "syno_username", False),
        ("Synology password", "syno_password", True),
    ]
    if with_immich:
        fields.append(("Immich API key", "immich_api_key", True))
    entries: dict = {}
    for label, key, secret in fields:
        ctk.CTkLabel(dlg, text=label, anchor="w",
                     text_color=W.MUTED).pack(fill="x", padx=22)
        e = ctk.CTkEntry(dlg, corner_radius=0, show="*" if secret else "")
        e.pack(fill="x", padx=22, pady=(2, 8))
        if existing and existing.get(key):
            e.insert(0, existing[key])
        entries[key] = e

    status = ctk.CTkLabel(dlg, text="", text_color=W.MUTED, font=W.font(11),
                          wraplength=410, justify="left")
    status.pack(padx=22, pady=(2, 0))
    result: dict = dict(existing) if existing else {}
    btn_holder: dict = {}

    def ok():
        vals = {k: e.get().strip() for k, e in entries.items()}
        if not vals.get("syno_username") or not vals.get("syno_password"):
            status.configure(text="Synology username and password required.",
                             text_color=W.RED)
            return
        btn_holder["b"].configure(state="disabled", text="Testing...")
        status.configure(text="Testing the connection...", text_color=W.MUTED)

        def worker():
            ok_, msg = _test_account(syno_url, verify, immich_url, vals,
                                     with_immich, otp_provider)

            def done():
                if ok_:
                    result.update(vals)
                    result["name"] = vals.get("syno_username", "")
                    dlg.destroy()
                else:
                    btn_holder["b"].configure(state="normal", text=add_label)
                    status.configure(text=msg, text_color=W.RED)
            try:
                dlg.after(0, done)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=worker, daemon=True).start()

    btn_holder["b"] = W.primary_button(dlg, add_label, ok)
    btn_holder["b"].pack(pady=12)
    W.fix_wrapping(dlg)
    parent.wait_window(dlg)
    return result if result.get("syno_username") else None


def prompt_rename(parent, current: str, suggestion: str) -> str | None:
    """Rename dialog: shows the current name + an editable clean suggestion."""
    dlg = ctk.CTkToplevel(parent)
    dlg.title("Rename album")
    dlg.geometry("460x270")
    dlg.transient(parent)
    dlg.lift()
    dlg.after(150, dlg.grab_set)

    ctk.CTkLabel(dlg, text="Rename album", font=W.font(17, "bold"),
                 text_color=W.GREEN).pack(pady=(18, 4))
    ctk.CTkLabel(dlg, text=f"Current name:  {current}", text_color=W.MUTED,
                 wraplength=410, justify="left").pack(padx=24)
    ctk.CTkLabel(dlg, text="New name (suggestion, edit if needed):",
                 text_color=W.MUTED, anchor="w").pack(fill="x", padx=24,
                                                      pady=(12, 0))
    e = ctk.CTkEntry(dlg, corner_radius=0)
    e.pack(fill="x", padx=24, pady=(2, 8))
    e.insert(0, suggestion)
    out: dict = {}

    def ok():
        out["name"] = e.get().strip()
        dlg.destroy()

    e.bind("<Return>", lambda _ev: ok())
    btns = ctk.CTkFrame(dlg, fg_color="transparent")
    btns.pack(pady=10)
    W.primary_button(btns, "Apply", ok, width=120).pack(side="left", padx=6)
    W.primary_button(btns, "Cancel", dlg.destroy, color=W.GREY,
                     hover=W.GREY_DK, width=120).pack(side="left", padx=6)
    dlg.after(250, e.focus)
    W.fix_wrapping(dlg)
    parent.wait_window(dlg)
    return out.get("name") or None


def prompt_folder(parent, start=None) -> str | None:
    """Themed folder browser (replaces the native, off-theme file dialog).

    Navigate with the folder buttons / Up, or type a path and press Enter.
    "Use this folder" returns the current directory.
    """
    from pathlib import Path

    dlg = ctk.CTkToplevel(parent)
    dlg.title("Choose a folder")
    dlg.geometry("600x560")
    dlg.transient(parent)
    dlg.lift()
    dlg.after(150, dlg.grab_set)

    try:
        state = {"path": Path(start).expanduser() if start else Path.home()}
    except Exception:  # noqa: BLE001
        state = {"path": Path.home()}
    out: dict = {}

    ctk.CTkLabel(dlg, text="Choose a destination folder",
                 font=W.font(17, "bold"), text_color=W.GREEN).pack(pady=(16, 8))
    bar = ctk.CTkFrame(dlg, fg_color="transparent")
    bar.pack(fill="x", padx=18)
    W.primary_button(bar, "Up", lambda: go(state["path"].parent),
                     color=W.GREY, hover=W.GREY_DK, width=64).pack(side="left")
    path_entry = ctk.CTkEntry(bar, corner_radius=0)
    path_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

    listf = W.scroll_frame(dlg)
    listf.pack(fill="both", expand=True, padx=18, pady=10)
    status = ctk.CTkLabel(dlg, text="", text_color=W.MUTED, font=W.font(11),
                          wraplength=560, justify="left")
    status.pack(padx=18)

    def render():
        path_entry.delete(0, "end")
        path_entry.insert(0, str(state["path"]))
        for w in listf.winfo_children():
            w.destroy()
        try:
            subs = sorted(
                (p for p in state["path"].iterdir()
                 if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name.lower())
        except Exception as e:  # noqa: BLE001
            ctk.CTkLabel(listf, text=f"Cannot open this folder: {e}",
                         text_color=W.RED, wraplength=520,
                         justify="left").pack(anchor="w", padx=6, pady=6)
            return
        if not subs:
            ctk.CTkLabel(listf, text="(no sub-folder here)",
                         text_color=W.MUTED).pack(anchor="w", padx=6, pady=6)
        for p in subs:
            ctk.CTkButton(
                listf, text=f"  {p.name}", anchor="w", fg_color=W.CARD,
                hover_color=W.HOVER, text_color=W.TEXT, corner_radius=0,
                height=30, font=W.font(12),
                command=lambda pp=p: go(pp)).pack(fill="x", pady=2)

    def go(p):
        p = Path(p)
        if p.is_dir():
            state["path"] = p
            status.configure(text="")
            render()
        else:
            status.configure(text="That path is not an existing folder.",
                             text_color=W.ORANGE)

    path_entry.bind("<Return>", lambda _e: go(path_entry.get().strip()))

    btns = ctk.CTkFrame(dlg, fg_color="transparent")
    btns.pack(pady=12)

    def use():
        out["path"] = str(state["path"])
        dlg.destroy()

    W.primary_button(btns, "Use this folder", use, width=170).pack(
        side="left", padx=6)
    W.primary_button(btns, "Cancel", dlg.destroy, color=W.GREY,
                     hover=W.GREY_DK, width=120).pack(side="left", padx=6)
    render()
    W.fix_wrapping(dlg)
    parent.wait_window(dlg)
    return out.get("path") or None


def prompt_otp(parent, username: str) -> str | None:
    """Ask for a 2FA code (used when an account has 2-step verification)."""
    dlg = ctk.CTkToplevel(parent)
    dlg.title("Two-factor authentication")
    dlg.geometry("430x310")
    dlg.transient(parent)
    dlg.lift()

    ctk.CTkLabel(dlg, text="Two-factor authentication",
                 font=W.font(17, "bold"), text_color=W.GREEN).pack(pady=(22, 4))
    ctk.CTkLabel(dlg, text=f"Enter the 6-digit code for '{username}'",
                 text_color=W.MUTED).pack()
    ctk.CTkLabel(dlg, text="This device will be remembered, so you won't be "
                 "asked for a code next time.", text_color=W.GREEN,
                 font=W.font(10), wraplength=320, justify="center").pack(
        padx=20, pady=(4, 0))
    entry = ctk.CTkEntry(dlg, justify="center", font=W.font(22),
                         corner_radius=0)
    entry.pack(pady=14, padx=50, fill="x")
    out: dict = {}

    def ok():
        out["code"] = entry.get().strip()
        dlg.destroy()

    entry.bind("<Return>", lambda _e: ok())
    W.primary_button(dlg, "Validate", ok).pack(pady=6)

    def _grab_and_focus():
        # On the first open the new toplevel often doesn't hold the WM's
        # keyboard focus, so a plain entry.focus() does nothing. focus_force()
        # pulls focus to the dialog, then we put the cursor in the code field.
        try:
            dlg.grab_set()
        except Exception:  # noqa: BLE001
            pass
        dlg.lift()
        dlg.focus_force()
        entry.focus_set()

    dlg.after(200, _grab_and_focus)
    W.fix_wrapping(dlg)
    parent.wait_window(dlg)
    return out.get("code") or None
