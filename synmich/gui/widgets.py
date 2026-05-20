"""Shared palette, helpers and session-building for the synmich GUI."""

from __future__ import annotations

import customtkinter as ctk
from customtkinter.windows.widgets.core_rendering.draw_engine import DrawEngine

from synmich.core.immich import ImmichClient
from synmich.core.migrator import UserSession
from synmich.core.synology import SynologyClient

# CustomTkinter draws checkmarks, dropdown arrows and rounded corners with a
# special "shapes" font. On this system that font doesn't load, so the check
# renders as a literal "Z", emojis as "uffd" and corners as chamfered cuts.
# Forcing vector (polygon) drawing makes everything draw with canvas lines
# instead of font glyphs - real checkmarks, no missing-glyph artefacts.
DrawEngine.preferred_drawing_method = "polygon_shapes"

# ---- Brand palette (dark theme) ------------------------------------------
GREEN = "#1D9E75"
GREEN_DK = "#157a5b"
ORANGE = "#EF9F27"
ORANGE_DK = "#c97f12"
RED = "#E94560"
RED_DK = "#bf3247"
BLUE = "#3d82d1"
BLUE_DK = "#2f66a8"

SIDEBAR = "#0e1620"
CONTENT = "#16202b"
CARD = "#1e2a36"
HOVER = "#1a2731"
NAV_ACTIVE = "#16323b"   # subtle green-tinted highlight for the active nav item
GREY = "#33424f"
GREY_DK = "#3d4d5b"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
LINE = "#2a3742"

# Plain-text nav labels (the CTk font has no icon-glyph coverage -> "uffd").
# Settings first: it's the most important / first thing to set up.
NAV = [
    ("settings", "Settings"),
    ("migration", "Syno to Immich"),
    ("backup", "Syno to local"),
    ("albums", "Albums"),
    ("stats", "Stats"),
    ("doctor", "Doctor"),
]

# Shared-album mode: friendly name, internal value, explanation (like the CLI)
SHARED_MODES = [
    ("mirror-syno", "link",
     "Same as Synology: personal albums stay personal, shared albums stay "
     "shared with the same people (recommended)."),
    ("separate", "duplicate",
     "Each user gets their own copy of a shared album, containing only their "
     "own photos. Albums are independent, no sharing in Immich."),
    ("skip", "ignore",
     "Shared albums are not recreated in Immich. Their photos still reach each "
     "user's library via the timeline."),
]
SHARED_TO_INTERNAL = {n: v for n, v, _ in SHARED_MODES}
INTERNAL_TO_SHARED = {v: n for n, v, _ in SHARED_MODES}


def font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def card(parent, title=None):
    """A flat card. Pack/grid the returned frame; add widgets to `.body`.

    corner_radius=0: CustomTkinter's corner draw-engine falls back to diagonal
    "chamfered" corners on this setup, so we keep everything square & clean.
    """
    outer = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=0)
    if title:
        ctk.CTkLabel(outer, text=title.upper(), text_color=GREEN,
                     font=font(12, "bold")).pack(anchor="w", padx=16,
                                                 pady=(14, 4))
    body = ctk.CTkFrame(outer, fg_color="transparent")
    # With a title the title label provides the top gap; without one, give the
    # body its own top padding so content isn't flush against the card edge.
    body.pack(fill="both", expand=True, padx=16,
              pady=(0, 14) if title else (14, 14))
    outer.body = body  # type: ignore[attr-defined]
    return outer


def primary_button(parent, text, command, color=GREEN, hover=GREEN_DK, **kw):
    """Solid, consistent button. Override height/width via **kw if needed."""
    opts = dict(text=text, command=command, fg_color=color, hover_color=hover,
                text_color="white", font=font(13, "bold"), corner_radius=0,
                height=38, border_width=0)
    opts.update(kw)
    return ctk.CTkButton(parent, **opts)


class SquareToggle(ctk.CTkFrame):
    """A flat, square segmented toggle built from buttons.

    Avoids CTk's rounded widgets (switch / segmented / radio) which render
    with ugly chamfered corners on this setup. The active option is green,
    the others grey.
    """

    def __init__(self, parent, options, default, command=None, width=130):
        super().__init__(parent, fg_color="transparent")
        self._value = default
        self._command = command
        self._btns = {}
        for opt in options:
            b = ctk.CTkButton(
                self, text=opt, corner_radius=0, border_width=0,
                width=width, height=32, font=font(12, "bold"),
                text_color="white", command=lambda o=opt: self.set(o))
            b.pack(side="left", padx=(0, 2))
            self._btns[opt] = b
        self._refresh()

    def _refresh(self):
        for o, b in self._btns.items():
            on = o == self._value
            b.configure(fg_color=GREEN if on else GREY,
                        hover_color=GREEN_DK if on else GREY_DK)

    def set(self, opt, fire=True):
        self._value = opt
        self._refresh()
        if fire and self._command:
            self._command(opt)

    def get(self):
        return self._value


def scroll_frame(parent, fg="#152029"):
    """A scrollable frame with a clean, square, subtle scrollbar."""
    sf = ctk.CTkScrollableFrame(
        parent, fg_color=fg, corner_radius=0,
        scrollbar_fg_color="transparent",
        scrollbar_button_color=GREY,
        scrollbar_button_hover_color=GREY_DK)
    # The internal scrollbar thumb is rounded by default and CTk renders the
    # rounding as ugly chamfered corners on this setup -> force square + thin.
    try:
        sf._scrollbar.configure(corner_radius=0, width=10)
    except Exception:  # noqa: BLE001
        pass
    return sf


def fmt_duration(seconds):
    """Human-readable duration like the CLI: '45s', '2m 03s', '1h 02m 03s'."""
    s = int(max(0, seconds or 0))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def normalize_url(url, default_scheme="http"):
    """Accept a bare IP/host (e.g. '192.168.0.2:5000') or a full URL.

    Prepends http:// when no scheme is given and trims a trailing slash, so the
    user can type the Synology/Immich address either way.
    """
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = f"{default_scheme}://{u}"
    return u.rstrip("/")


def build_sessions(cfg, otp_provider=None, with_immich=True,
                   accounts_key=None) -> list[UserSession]:
    """Log in every configured account. Raises on failure.

    `with_immich` controls whether an Immich client is built (and its API key
    required). `accounts_key` picks which config list to use; by default the
    Immich-migration users ("users", with API keys) when with_immich, else the
    local-backup accounts ("backup_accounts", Synology only). Migration listing
    passes accounts_key="users" with with_immich=False to log the migration
    users in via Synology only (no API key needed just to list albums).

    `otp_provider(username) -> code` is used when an account has 2FA enabled
    (the GUI passes a dialog-based provider so 2FA works graphically).
    """
    syno_url = normalize_url(cfg.get("synology", {}).get("url", ""))
    verify = cfg.get("synology", {}).get("verify_ssl", False)
    immich_url = normalize_url(cfg.get("immich", {}).get("url", ""))
    if not syno_url:
        raise RuntimeError(
            "Enter the Synology address or IP in Settings first "
            "(for example 192.168.0.2:5000).")
    sessions: list[UserSession] = []
    if accounts_key is None:
        accounts_key = "users" if with_immich else "backup_accounts"
    accounts = cfg.get(accounts_key, [])
    for u in accounts:
        name = u.get("name") or u.get("syno_username") or "user"
        syno = SynologyClient(syno_url, verify_ssl=verify)
        if not syno.login(u.get("syno_username", ""), u.get("syno_password", ""),
                          otp_provider=otp_provider):
            raise RuntimeError(
                f"Synology login failed for '{name}'. Check the username, "
                f"password and the Synology address.")
        syno_id = syno.me()
        immich = None
        immich_user_id = ""
        if with_immich:
            key = u.get("immich_api_key", "")
            if not key:
                raise RuntimeError(
                    f"'{name}' has no Immich API key. Edit this user in "
                    f"Settings to add it.")
            if not immich_url:
                raise RuntimeError(
                    "Immich address is missing. Add it in Settings.")
            immich = ImmichClient(immich_url, key)
            try:
                immich_user_id = immich.me().get("id", "")
            except Exception:  # noqa: BLE001
                raise RuntimeError(
                    f"Immich connection failed for '{name}'. Check the Immich "
                    f"address and the API key.")
        sessions.append(UserSession(
            name=name, syno=syno, immich=immich,
            syno_user_id=syno_id or (len(sessions) + 1),
            immich_user_id=immich_user_id))
    return sessions


def build_immich_clients(cfg):
    """Build Immich-only clients (no Synology login) from the migration users'
    API keys, for the Album Manager. Reuses the keys already entered in the
    Synology to Immich tab. Returns a list of (name, ImmichClient).

    Users without a key are skipped; raises only if none has a key.
    """
    immich_url = normalize_url(cfg.get("immich", {}).get("url", ""))
    if not immich_url:
        raise RuntimeError("Enter the Immich address or IP in Settings first.")
    users = cfg.get("users", [])
    if not users:
        raise RuntimeError("No Immich user yet. Add a user with an Immich API "
                           "key in the Synology to Immich tab.")
    clients = []
    for u in users:
        key = u.get("immich_api_key", "")
        if not key:
            continue
        name = u.get("name") or u.get("syno_username") or "user"
        client = ImmichClient(immich_url, key)
        try:
            client.me()
        except Exception:  # noqa: BLE001
            raise RuntimeError(
                f"Immich connection failed for '{name}'. Check the Immich "
                f"address and the API key.")
        clients.append((name, client))
    if not clients:
        raise RuntimeError("No Immich API key found. Add a key to a user in "
                           "the Synology to Immich tab.")
    return clients


def humanize_error(msg) -> str:
    """Turn a raw validation / internal error into a clear, friendly line."""
    import re
    m = str(msg)
    owner = re.search(r"shared_space_owner='([^']*)'", m)
    table = [
        ("synology.url", "Synology address is missing - set it in Settings."),
        ("immich.url", "Immich address is missing - set it in Settings."),
        ("No user configured", "No Immich migration user yet - add one in the "
                               "Synology to Immich tab (it needs an API key)."),
        ("immich_api_key", "A migration user has no Immich API key - edit it "
                           "in the Synology to Immich tab."),
        ("syno_username", "A user has no Synology username."),
        ("syno_password", "A user has no Synology password."),
        (".name is missing", "A user has no name."),
        ("shared_albums_mode", "The shared-albums mode is invalid."),
        ("albums_mode", "The albums mode is invalid."),
    ]
    if "shared_space_owner" in m and owner:
        return (f"Shared Space owner '{owner.group(1)}' is not one of your "
                f"migration users. Pick an existing user as the Shared Space "
                f"owner, or turn Shared Space off in Settings.")
    for needle, friendly in table:
        if needle in m:
            return friendly
    return m


def friendly_config(cfg) -> list[str]:
    """Friendly, human-readable list of what blocks a migration."""
    from synmich.config import validate_config
    return [humanize_error(e) for e in validate_config(cfg)]


def auto_wrap(label, margin=18):
    """Make a CTkLabel wrap to its CONTAINER's width and left-align its text,
    so it never clips on either side regardless of panel/window width.

    Sizing to the container (not the label itself) avoids the feedback loop a
    self-referential wraplength would cause on a shrink-to-fit label.
    """
    try:
        label.configure(anchor="w", justify="left")
    except Exception:  # noqa: BLE001
        pass

    def _fit(_e=None):
        try:
            w = label.master.winfo_width() - margin
            if w > 40 and abs(int(label.cget("wraplength")) - w) > 2:
                label.configure(wraplength=w)
        except Exception:  # noqa: BLE001
            pass

    label.bind("<Configure>", _fit, add="+")
    label.master.bind("<Configure>", _fit, add="+")
    return label


def fix_wrapping(root):
    """Apply auto_wrap to every wrap-enabled CTkLabel under `root` (the ones
    created with a wraplength). Call once after building a view or dialog."""
    def walk(w):
        for child in w.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                try:
                    if int(child.cget("wraplength")) > 0:
                        auto_wrap(child)
                except Exception:  # noqa: BLE001
                    pass
            walk(child)
    walk(root)


def sub_tabview(parent, fg=CARD):
    """A styled CTkTabview matching the app theme (square, green-selected),
    used to give each user their own tab inside a card."""
    return ctk.CTkTabview(
        parent, corner_radius=0, fg_color=fg,
        segmented_button_fg_color=SIDEBAR,
        segmented_button_selected_color=GREEN,
        segmented_button_selected_hover_color=GREEN_DK,
        segmented_button_unselected_color=CARD,
        segmented_button_unselected_hover_color=HOVER,
        text_color="white")


def render_album_groups(box, records, album_vars, preselected=None,
                        empty_text="No album found.", on_change=None):
    """Render the album checklist as one sub-tab per owner (user), so each
    user's albums are directly reachable instead of scrolling one long mixed
    list. Shared albums show who they are shared with. Fills
    album_vars[key]=BooleanVar; returns the album count.
    """
    import tkinter as tk
    preselected = preselected or set()
    for w in box.winfo_children():
        w.destroy()
    album_vars.clear()
    if not records:
        ctk.CTkLabel(box, text=empty_text, text_color=ORANGE, wraplength=560,
                     justify="left", anchor="w").pack(anchor="w", padx=8,
                                                      pady=8)
        return 0
    groups: dict = {}
    for key, r in records.items():
        groups.setdefault(r.get("owner_name", "?"), []).append((key, r))
    tv = sub_tabview(box)
    tv.pack(fill="both", expand=True)
    total = 0
    for owner in sorted(groups, key=str.lower):
        tab = tv.add(f"{owner} ({len(groups[owner])})")
        sf = scroll_frame(tab, fg="#152029")
        sf.pack(fill="both", expand=True)
        for key, r in sorted(
                groups[owner],
                key=lambda kv: (kv[0] not in preselected,
                                kv[1]["name"].lower())):
            var = tk.BooleanVar(value=key in preselected)
            album_vars[key] = var
            row = ctk.CTkFrame(sf, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=2)
            ctk.CTkCheckBox(
                row, variable=var, command=on_change, text=r["name"],
                fg_color=GREEN, hover_color=GREEN_DK, checkbox_width=20,
                checkbox_height=20, corner_radius=0, border_width=2,
                font=font(12)).pack(side="left")
            ctk.CTkLabel(row, text=f"  {r['items']} photos", text_color=MUTED,
                         font=font(11)).pack(side="left", padx=(6, 0))
            shared_with = sorted(
                set(r.get("viewers") or set()) - {r.get("owner_name")})
            if r.get("shared") and shared_with:
                ctk.CTkLabel(row, text=f"shared with {', '.join(shared_with)}",
                             text_color=ORANGE, font=font(11, "bold")).pack(
                    side="left", padx=(12, 0))
            elif r.get("shared"):
                ctk.CTkLabel(row, text="shared", text_color=ORANGE,
                             font=font(11, "bold")).pack(side="left",
                                                         padx=(12, 0))
            total += 1
    return total
