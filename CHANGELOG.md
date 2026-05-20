# Changelog

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
