# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-05-19

### Fixed

- **Critical**: items in the Synology Shared Space (owner_user_id=0) were silently skipped during migration when present in personal albums. The download API was hardcoded to `SYNO.Foto.Download` which does not work for shared-space items — it should use `SYNO.FotoTeam.Download`. This caused personal albums containing photos from the Shared Space to be created in Immich but remain empty. The `download()` method now automatically routes to the correct API based on `owner_user_id`.
- **Log dashboard**: the live log panel would stop displaying new messages after the 100th entry. The poll logic was comparing against the bounded buffer length instead of a monotonic counter. Now tracks `total_messages_logged` so the log continues to scroll indefinitely.
- **Better error handling**: when the Synology API returns JSON/HTML instead of binary data (e.g. wrong API selected for an item), the download now fails closed instead of writing a corrupted file.

### Added

- New method `SynologyClient.list_shared_space_items()` to enumerate items in the Synology Shared Space (Team library).
- New method `SynologyClient.count_shared_space_items()` to count items in the Shared Space.

### Notes

- If you previously migrated with v1.0.0 and have personal albums that appear empty in Immich, the items are most likely Shared Space items that were silently skipped. After upgrading to v1.0.1, you can either restart the migration from scratch or run a manual repair script (see Troubleshooting in the README).
- Shared Space items continue to be attributed in Immich to the user configured as `shared_space_owner` in the config (default: first configured user).

## [1.0.0] - 2026-05-19

### Added

- Interactive wizard (`synmich init`) with auto-detection of DSM users
- Full migration command (`synmich migrate`) with live Textual dashboard
- Shared albums migration with correct owner preservation and per-user permissions
- Three shared album handling modes:
  - `link` (default): one shared album in Immich, preserves owner + cross-user permissions
  - `duplicate`: each user gets their own separate copy of the album
  - `ignore`: skip shared albums entirely (photos still in timeline)
- Shared Space (Synology common photos) support
- Multi-user support (N users, not limited to 2)
- Resume from checkpoint after interruption (Ctrl+C, crash, or `Q` in dashboard)
- Parallel and sequential execution modes
- `--dry-run` mode to simulate the migration without downloading or uploading
- Persistent counters for uploaded/duplicate/failed in `synmich stats`
- Pause/Resume hotkeys (`P`) and graceful quit (`Q`) in the dashboard
- Filters: regex include/exclude albums, max file size, video toggle
- Commands: `users`, `albums`, `verify`, `stats`, `logs`, `config`, `reset`
- Docker image with config volume support
