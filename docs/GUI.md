# synmich GUI (`synmich gui`)

A beginner-friendly desktop GUI built with **CustomTkinter**, exposing the
core CLI workflow without a terminal.

## Launch

```bash
synmich gui
```

Requires `customtkinter` (`pip install customtkinter`) and Tk
(`python3-tkinter` on Fedora/Nobara, `python3-tk` on Debian/Ubuntu).

## Layout

VSCode-style: a colored navigation **sidebar** on the left (monochrome glyph
+ label), a large **work area** on the right that swaps views. Dark theme by
default (light theme toggle at the bottom of the sidebar).

```
┌────────────────┬─────────────────────────────────────────────┐
│  synmich       │  Migration                                    │
│  Synology→Immich│ ──────────────────────────────────────────── │
│                │  Albums: [All|Pick]   Shared: mirror-syno     │
│ ▶  Migration   │  [ Load albums ]  ...checklist...             │
│ ⬇  Backup local│  START MIGRATION                              │
│ ▤  Albums      │   6 UPLOADED   0 DUPLICATE   0 FAILED          │
│ ▦  Stats       │   ▰▰▰▰▰▱▱  testtest (6/9)                      │
│ ✚  Doctor      │   [Pause] [Stop]                              │
│ ⚙  Settings    │   ── logs ──                                  │
│ ● Connected    │                                               │
│ ◐ Light theme  │                                               │
└────────────────┴─────────────────────────────────────────────┘
```

Glyphs are monochrome Unicode (`▶ ⬇ ▤ ▦ ✚ ⚙`) on purpose: Tk does not render
color emoji on Linux (they show up as the "uffd" replacement box).

## Palette

| Role | Color |
|------|-------|
| Primary (green) | `#1D9E75` |
| Accent (orange) | `#EF9F27` |
| Error (red) | `#E94560` |
| Info (blue) | `#3d82d1` |

## Tabs

| Tab | Status | What it does |
|-----|--------|--------------|
| **Migration** | ✅ MVP | options (all/pick, shared mode, timeline), album checklist, Start, live counters/progress/log, pause/stop |
| **Settings** | ✅ MVP | servers (URLs, SSL), users (add/edit/remove), Test connection, Save config |
| Backup local | placeholder | hierarchical album backup to a local folder |
| Albums | placeholder | browse / rename / delete-empty Immich albums |
| Stats | placeholder | Immich + checkpoint statistics |
| Doctor | placeholder | system diagnostic (like `synmich doctor`) |

**First launch** (no usable config): an onboarding modal collects the
servers + first user, then the app reloads.

## Architecture

```
synmich/gui/
├── app.py            # SynmichApp (CTk): sidebar + view switching + connect()
├── widgets.py        # palette, NAV, card(), build_sessions()
├── dialogs.py        # prompt_user() modal
├── wizard_modal.py   # first-launch onboarding
└── views/
    ├── migration.py  # Migration tab
    ├── settings.py   # Settings tab
    └── placeholder.py# "coming soon" tabs
```

`synmich/cli.py::cmd_gui` lazily imports `synmich.gui.app.run_gui`.

## Threading

Network/migration work runs on worker threads; the UI thread only reads
`MigrationStats` (polled every 300 ms via `after()`) and is updated through
`app.after(0, …)`. The window stays responsive; `MigrationControl` drives
pause/stop.

## Reused core (same behaviour as the CLI)

`config` (load/save/validate), `SynologyClient`, `ImmichClient`,
`Migrator` + `MigrationStats` + `MigrationControl`, `album_selector._build_records`.

> Screenshots: TODO — capture from a running `synmich gui`.
