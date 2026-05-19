# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-05-19

### Added
- Interactive wizard (`synmich init`) with auto-detection of DSM users
- Full migration command (`synmich migrate`) with live Textual dashboard
- **Shared albums migration** with correct owner preservation and per-user permissions
- **Three shared album handling modes**:
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

### Fixed (during development)
- Thread-safety bug: `requests.Session` shared across worker threads could cause stream mixing
- Filename collision bug: items with same name in shared albums could overwrite each other on local disk
- Live Photos incorrectly filtered: iPhone Live Photo type "live" no longer treated as video
