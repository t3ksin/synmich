"""synmich configuration management."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def get_config_dir() -> Path:
    """Return the config dir based on OS."""
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", "~/.config"))
    else:
        base = Path(
            os.environ.get("XDG_CONFIG_HOME", "~/.config")
        )
    path = base.expanduser() / "synmich"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_file() -> Path:
    return get_config_dir() / "config.yaml"


def get_checkpoint_file() -> Path:
    return get_config_dir() / "checkpoint.json"


def get_log_file() -> Path:
    return get_config_dir() / "migration.log"


DEFAULT_CONFIG: Dict[str, Any] = {
    "synology": {
        "url": "",
        "verify_ssl": False,
    },
    "immich": {
        "url": "",
    },
    # List of {name, syno_username, syno_password, immich_api_key}
    "users": [],
    "migration": {
        "include_albums": True,
        "include_timeline": True,
        # How to handle shared Synology albums:
        #   link      - one shared album in Immich, preserves owner +
        #               cross-user permissions (default, recommended)
        #   duplicate - each user gets their own copy of the album
        #               with only their own photos
        #   ignore    - skip shared albums entirely
        "shared_albums_mode": "link",
        "include_shared_space": True,
        # Name of the user who becomes owner of Shared Space photos
        "shared_space_owner": "",
        # Default Immich role for users with "view" permission on Syno
        # (users with "upload" permission always become "editor")
        "share_role": "editor",
    },
    "execution": {
        "mode": "parallel",  # parallel | sequential
        "workers": 4,
        "max_retries": 5,
        "retry_backoff_seconds": 3,
        # Only deletes LOCAL temporary files after upload.
        # Synology NAS files are NEVER modified.
        "delete_after_upload": True,
        "verbose": False,
    },
    "filters": {
        "include_albums_regex": "",
        "exclude_albums_regex": "",
        "min_date": "",
        "max_date": "",
        "include_videos": True,
        "max_file_size_mb": 0,  # 0 = no limit
    },
    "paths": {
        "work_dir": "./synmich_backup",
    },
}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load YAML config, merged with defaults."""
    if path is None:
        path = get_config_file()
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data


def save_config(
    data: Dict[str, Any], path: Optional[Path] = None
) -> None:
    """Save config as YAML."""
    if path is None:
        path = get_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(
            data,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )


def validate_config(data: Dict[str, Any]) -> List[str]:
    """Return the list of validation errors."""
    errors = []

    if not data.get("synology", {}).get("url"):
        errors.append("synology.url is missing")
    if not data.get("immich", {}).get("url"):
        errors.append("immich.url is missing")

    users = data.get("users", [])
    if not users:
        errors.append("No user configured")

    for i, u in enumerate(users):
        prefix = f"users[{i}]"
        if not u.get("name"):
            errors.append(f"{prefix}.name is missing")
        if not u.get("syno_username"):
            errors.append(f"{prefix}.syno_username is missing")
        if not u.get("syno_password"):
            errors.append(f"{prefix}.syno_password is missing")
        if not u.get("immich_api_key"):
            errors.append(f"{prefix}.immich_api_key is missing")

    mig = data.get("migration", {})

    # Validate shared_albums_mode
    sam = mig.get("shared_albums_mode", "link")
    if sam not in ("link", "duplicate", "ignore"):
        errors.append(
            f"migration.shared_albums_mode='{sam}' "
            f"must be 'link', 'duplicate', or 'ignore'"
        )

    if mig.get("include_shared_space"):
        owner = mig.get("shared_space_owner")
        if owner and owner not in [u.get("name") for u in users]:
            errors.append(
                f"migration.shared_space_owner='{owner}' "
                f"not found in users"
            )

    return errors

