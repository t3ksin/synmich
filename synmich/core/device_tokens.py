"""Synology device token management for 2FA.

A device token is issued by Synology on the first login with OTP.
It allows reconnecting later without prompting for the OTP again, as
long as Synology considers the device "trusted".

Storage:
    ~/.config/synmich/device_tokens.json
    Permissions 600 (owner read-only).

Format:
    {
      "username@base_url": "device_id_token",
      ...
    }
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Optional

log = logging.getLogger("synmich")


def _tokens_path() -> Path:
    """Path of the device tokens storage file."""
    return Path.home() / ".config" / "synmich" / "device_tokens.json"


def _safe_load() -> dict:
    """Load the tokens file. Returns {} if missing or corrupted."""
    p = _tokens_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not read device_tokens.json: %s", e)
        return {}


def _safe_save(data: dict) -> None:
    """Save the tokens file with 600 permissions."""
    p = _tokens_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file then rename (atomic)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Restrictive permissions (before the rename so it takes effect)
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Non-fatal on Windows

    tmp.replace(p)


def _key(username: str, base_url: str) -> str:
    """Build the storage key."""
    return f"{username}@{base_url}"


def get_device_token(username: str, base_url: str) -> Optional[str]:
    """Retrieve the saved device token for this user.

    Returns None if no token is known (first connection).
    """
    tokens = _safe_load()
    return tokens.get(_key(username, base_url))


def save_device_token(
    username: str, base_url: str, device_token: str
) -> None:
    """Save a new device token."""
    tokens = _safe_load()
    tokens[_key(username, base_url)] = device_token
    _safe_save(tokens)
    log.info(
        "Device token saved for %s@%s (no OTP needed next time)",
        username, base_url,
    )


def clear_device_token(username: str, base_url: str) -> None:
    """Remove a device token (useful if invalidated on the Synology side)."""
    tokens = _safe_load()
    tokens.pop(_key(username, base_url), None)
    _safe_save(tokens)


def list_devices() -> dict:
    """List all known device tokens (for the doctor/debug)."""
    return _safe_load()
