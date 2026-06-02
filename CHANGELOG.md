# Changelog

## [2.2.0] - 2026-06-02

### Added

- **External library mode** (`migration.external_library_mode`). For setups
  where the photos already live in Immich via an *external library*, synmich
  now matches each Synology photo to the existing Immich asset by filename +
  capture date and adds it straight to the album — no download, no re-upload —
  instead of creating a duplicate copy in the upload library. Unmatched photos
  still upload normally so nothing is dropped, and matched photos are counted
  under a new **Linked (external)** stat in the summaries and checkpoint.
  Resolves the duplication reported with external libraries (#1, #2): Immich
  can't dedup external assets because it stores a dummy path-based checksum for
  them ([immich-app/immich#7804](https://github.com/immich-app/immich/discussions/7804)),
  so a content-checksum skip could never catch them.

## [2.1.0] - 2026-05-21

### Added

- **Synology to local: full-timeline backup.** A checkbox (on by default, same
  style as the migration tab) downloads each account's entire timeline - every
  photo, including those in no album - into `<destination>/<user>/timeline/`,
  after the albums.
- **App icon.** The window / taskbar icon is now the brand "S" gradient instead
  of the default Python icon.
- **Colour-coded top tabs.** The three main tabs each have their own colour
  (green = Synology to Immich, blue = Synology to local, amber = Immich Album
  Manager) so the modes read as distinct at a glance.
- **Reliable long migrations.** Each user's Synology session is now kept alive
  for the whole run — a background thread pings every 30 min and silently
  re-logs in (via the saved device token) if the session expires — so
  multi-hour migrations don't fail on a Synology session timeout.

### Changed

- **Account dialog is now per-mode.** *Synology to Immich* adds a **user to
  migrate** (Synology login + that same user's Immich API key); the **Immich
  Album Manager** adds an **Immich user** (Immich API key only - no Synology
  login); *Synology to local* adds a **Synology account**. Wording and fields
  are tailored to each, and the Immich API key is clearly described as belonging
  to that same user's Immich account.
- **Docs.** Simplified cross-platform install (Linux/macOS/Windows) with a
  collapsible troubleshooting section; the tagline now mentions local backup.

### Fixed

- **Account changes are saved immediately.** Adding, editing or removing a
  user/account now writes to the config right away, so a removed user no longer
  reappears after restarting the app (previously it needed a manual "Save
  settings"). Applies to every tab.

## [2.0.4] - 2026-05-20

### Fixed

- GUI: the 2FA code field now grabs focus on the **first** prompt, so the code
  can be typed immediately (previously it only worked on a second prompt).

## [2.0.3] - 2026-05-20

### Changed

- GUI: the top-left brand is now the blue->cyan gradient logo (same design as
  the README and CLI banner), with a large text fallback.

### Fixed

- Packaging: include the `synmich.gui` and `synmich.commands` packages and the
  GUI logo asset (a pip install previously shipped without the GUI). Declare a
  `gui` extra (`customtkinter`, `Pillow`) and fix the repository URLs.

## [2.0.2] - 2026-05-20

### Changed

- GUI now uses the **Inter** font for better readability (configurable via
  `FONT_FAMILY` in `widgets.py`, with a Tk-default fallback).

### Docs

- README logo is now a blue->cyan gradient image matching the CLI banner.

## [2.0.1] - 2026-05-20

### Changed

- GUI: the three main tabs are now spaced apart and use a distinct colour, so
  they clearly read as the app's primary navigation.

### Docs

- README: richer Features with a fuller 2FA explanation, PhotoMigrator added to
  the comparison, centered logo, and capitalization/wording polish.

## [2.0.0] - 2026-05-20

### Major release: graphical app + local backup

synmich 2.0 adds a full graphical application alongside the CLI, plus a
local-backup mode. The GUI is now the primary tool for choosing which albums
to migrate.

### Added

#### Graphical app (`synmich gui`)

A CustomTkinter desktop app, dark-themed and beginner-friendly:

- Three operations as top tabs — **Synology to Immich**, **Synology to local**,
  **Immich Album Manager** — each with a short description.
- One **sub-tab per user** for album lists, so albums are never mixed; shared
  albums show **who they are shared with** (in colour).
- **Check all / Uncheck all** and a live **selected count**.
- Live panel: counters, progress bar, ETA, throughput and a clean log
  (durations formatted like the CLI).
- **Settings** with separate account lists — Immich-migration users (with API
  key) vs local-backup accounts (Synology only) — a configured-users counter
  and a **Check NAS users** helper that hides system accounts.
- **Stats** (last run + saved cumulative), **Doctor** (servers, accounts, disk,
  config for both lists) and a scoped **Reset** (progress / 2FA device tokens /
  configuration / everything), reachable from Settings and Doctor.
- Opens maximized for readability; addresses accept a bare IP or host (with
  port).

#### Synology to local backup

Download a user's Synology Photos albums to a folder on the computer (no Immich
needed), with an "all photos" / "owner only" mode for shared albums.

### Changed

- The CLI no longer has an interactive album picker — choosing albums lives in
  the GUI. The CLI migrates everything (optionally filtered by
  `filters.include_albums_regex`) and still honours a GUI-made selection.
- The Immich Album Manager talks to Immich with each user's API key only (no
  Synology login) and shows which Immich account each key maps to.

### Fixed

- `user_id` was not populated after a 2FA login, which could mark an album done
  with 0 items uploaded.
- `synmich reset` could hang on a lock/save deadlock.

### Notes

- The Synology NAS is still only ever read, never written.
- Config and checkpoint files stay local and are git-ignored.

## [1.1.0] - 2026-05-20

### Major improvements: Multi-checkpoint + CLI relooked

This release fixes a critical design flaw where all configurations shared a single checkpoint file. It also adds a polished CLI with new commands.

### Added

#### Config-aware checkpoints (CRITICAL fix)

Each unique configuration (Synology URL + Immich URL + users) now has its own checkpoint:

```
~/.config/synmich/checkpoints/
├── d4a3b2.json   ← config for Jeffrey/Roberta
├── f8e7c1.json   ← config for testtest
└── index.json    ← metadata
```

This prevents the situation where running with a test config would pollute or overwrite the checkpoint of a production migration.

**Auto-migration**: any existing `~/.config/synmich/checkpoint.json` is automatically moved to the new format on the first run.

#### Config/checkpoint mismatch detection

Before starting a migration, synmich now checks if the checkpoint matches the current config. If a mismatch is detected (e.g. checkpoint has more users than config), the user is warned and given three options:
- Continue anyway
- Start fresh with an empty checkpoint
- Abort to check the config

#### Clean migration output

Resumed migrations no longer spam "already done" for thousands of items. Instead, a clean summary is shown:

```
ℹ Resume from checkpoint
  Already migrated   67,844 items
  Albums done        96 albums
  Users              Jeffrey, Roberta

ℹ Items already migrated will be skipped silently.
ℹ Only new or failed items will be processed.
```

#### New CLI commands

- `synmich doctor` — Full system diagnostic (Python, OS, disk, config, connections, queues)
- `synmich stats` — Detailed Immich + checkpoint statistics
- `synmich checkpoints list/show/delete/migrate` — Manage checkpoints
- `synmich albums list/delete-empty` — Manage Immich albums with filters

#### CLI relooked with Rich

- Colored tables for albums, users, stats, checkpoints
- Clear error panels instead of Python tracebacks
- Help organized by category
- Consistent color palette across all output

### Wizard improvements

- HTTP security warning: when an HTTP URL is provided, the wizard warns about unencrypted credentials and recommends HTTPS
- All v1.0.4 fixes (retry loops, recommendations) preserved

### Internal

- New module: `synmich/core/migrator_helpers.py`
- New module: `synmich/ui/cli_helpers.py`
- New package: `synmich/cli/` with `doctor.py`, `stats.py`, `checkpoints.py`, `albums.py`
- Checkpoint hash: sha256 of `(synology_url, immich_url, sorted_user_names)[:12]`

### Notes

- Backward compatible: legacy single `checkpoint.json` is auto-migrated, never deleted (kept as `.legacy-backup`).
- The `synmich reset` command now only resets the current config's checkpoint, not all of them.
- 2FA device tokens (v1.0.4) are not affected by this change.

## [1.0.4] - 2026-05-20

### Added — Synology 2FA support

Synmich now supports Synology accounts with 2-step verification enabled. Device tokens saved at `~/.config/synmich/device_tokens.json` (chmod 600).

### Added — Session keepalive

Pings Synology every 30 min during long migrations, re-logs in if session expired.

## [1.0.3] - 2026-05-19

### Fixed
- Critical: non-shared personal albums of non-admin users were silently skipped.

## [1.0.2] - 2026-05-19

### Fixed
- Shared album add_to_album retry with owner's API key.

## [1.0.1] - 2026-05-19

### Fixed
- Items in Shared Space silently skipped.
- Log dashboard stopped after 100 messages.

## [1.0.0] - 2026-05-19

Initial release.
