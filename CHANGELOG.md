# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2026-05-19

### Fixed

- **Critical: non-shared personal albums of users other than the configured admin/owner were silently skipped.** When a non-owner user listed their own personal albums via the Synology API, the `sharing_info.owner.id` field returned `-1` instead of the user's actual ID. The migrator was using `sharing.owner.id` in priority over the album's own `owner_user_id` field with a truthy `or` fallback — but `-1` is truthy in Python, so the fallback never triggered. The mapping then failed with `owner_syno_id=-1 not mapped`. Fixed by explicitly requiring `sharing.owner.id > 0` before using it, falling back to `album.owner_user_id` otherwise.

### Added

- **Elapsed time, ETA, and rate displayed in the dashboard stats panel**, alongside the existing counters:
  - Elapsed time since migration start (h:mm:ss)
  - Estimated time remaining (based on rate of items processed)
  - Current rate in items per minute or per second

### Notes

- This release is purely a bug fix and quality-of-life improvement. No breaking changes.
- If you migrated with v1.0.2 and notice missing personal albums of non-first users, upgrade to v1.0.3 and rerun the migration — the checkpoint will skip already-migrated items, and the previously skipped albums will now be processed.

## [1.0.2] - 2026-05-19

### Fixed

- **Shared album add_to_album failures**: when the parallel pipeline produced assets attributed to the wrong uploader under heavy load, the final `add_to_album` call would fail with `no_permission`. The migrator now retries failed adds using the album owner's API key.
- **Better error logging** distinguishing fresh adds from owner-retry recoveries.

## [1.0.1] - 2026-05-19

### Fixed

- **Critical**: items in the Synology Shared Space (owner_user_id=0) were silently skipped during migration when present in personal albums.
- **Log dashboard** no longer stops displaying new messages after 100 entries.
- **Better error handling** when the Synology API returns JSON/HTML instead of binary.

### Added

- `SynologyClient.list_shared_space_items()` and `count_shared_space_items()`.

## [1.0.0] - 2026-05-19

Initial release. Synology Photos → Immich migrator with multi-user support, shared albums, owner preservation, and resumable migrations.
