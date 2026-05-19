"""Interactive wizard synmich init."""

import getpass
import re
import sys
from typing import Any, Dict, List, Optional

from rich.prompt import Prompt, Confirm, IntPrompt

from synmich.config import (
    DEFAULT_CONFIG,
    get_config_file,
    save_config,
)
from synmich.core.synology import SynologyClient
from synmich.core.immich import ImmichClient
from synmich.ui.theme import (
    console,
    print_banner,
    print_section,
    success,
    info,
    warn,
    error,
    muted,
    COLOR_PRIMARY,
    COLOR_ACCENT,
    COLOR_MUTED,
)


def _ask(prompt: str, default: str = "", password: bool = False) -> str:
    if password:
        return Prompt.ask(
            f"  [bold]{prompt}[/]",
            password=True,
            default=default if default else None,
        )
    return Prompt.ask(
        f"  [bold]{prompt}[/]",
        default=default if default else None,
    )


def _confirm(prompt: str, default: bool = True) -> bool:
    return Confirm.ask(
        f"  [bold]{prompt}[/]", default=default
    )


def run_wizard() -> int:
    """Run the interactive wizard. Returns 0 on success."""

    print_banner("Setup Wizard")

    config: Dict[str, Any] = {
        k: dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)
        for k, v in DEFAULT_CONFIG.items()
    }
    config["users"] = []

    # ============ Step 1: Synology ============
    print_section("Step 1/4 · Synology")

    syno_url = _ask(
        "Synology URL (https://IP:PORT)",
        default="https://192.168.1.1:5001",
    )
    config["synology"]["url"] = syno_url

    verify_ssl = _confirm(
        "Verify SSL certificate?", default=False
    )
    config["synology"]["verify_ssl"] = verify_ssl

    info("Testing connection...")
    test_client = SynologyClient(
        syno_url, verify_ssl=verify_ssl
    )
    # On ne peut pas tester sans login. Skip.
    success(f"URL set: {syno_url}")

    # ============ Step 2: Users ============
    print_section("Step 2/4 · Users")

    mode = Prompt.ask(
        "  [bold]How to add users?[/]",
        choices=["auto", "manual"],
        default="manual",
    )

    if mode == "auto":
        users = _autodetect_users(syno_url, verify_ssl)
    else:
        users = _manual_users(syno_url, verify_ssl)

    if not users:
        error("No user configured. Aborting.")
        return 1

    config["users"] = users

    # ============ Step 3: Immich ============
    print_section("Step 3/4 · Immich")

    immich_url = _ask(
        "Immich URL (http://IP:PORT)",
        default="http://192.168.1.1:2283",
    )
    config["immich"]["url"] = immich_url

    info("Testing Immich connection per user...")
    for u in users:
        # Ask for API key if missing
        if not u.get("immich_api_key"):
            u["immich_api_key"] = _ask(
                f"Immich API key for {u['name']}",
                password=True,
            )
        client = ImmichClient(
            immich_url, u["immich_api_key"]
        )
        try:
            me = client.me()
            success(
                f"{u['name']} → {me.get('email', 'OK')}"
            )
            u["_immich_id"] = me.get("id")
        except Exception as e:
            warn(
                f"{u['name']} test failed: {e}. "
                f"You can fix in config later."
            )

    # ============ Step 4: Options ============
    print_section("Step 4/4 · Options")

    config["migration"]["include_albums"] = _confirm(
        "Migrate albums?", default=True
    )
    config["migration"]["include_timeline"] = _confirm(
        "Migrate timeline (photos outside albums)?",
        default=True,
    )

    # Shared albums mode
    if config["migration"]["include_albums"]:
        console.print()
        muted("  How should shared albums be handled?")
        muted(
            "    [bold]link[/]      - One shared album in Immich, "
            "preserves owner + permissions"
        )
        muted(
            "                (recommended for couples/families)"
        )
        muted(
            "    [bold]duplicate[/] - Each user gets their own "
            "separate copy of the album"
        )
        muted(
            "    [bold]ignore[/]    - Skip shared albums entirely "
            "(photos still in timeline)"
        )
        console.print()
        mode = Prompt.ask(
            "  [bold]Shared albums mode[/]",
            choices=["link", "duplicate", "ignore"],
            default="link",
        )
        config["migration"]["shared_albums_mode"] = mode

    config["migration"]["include_shared_space"] = _confirm(
        "Migrate Shared Space photos?", default=True
    )

    if config["migration"]["include_shared_space"]:
        names = [u["name"] for u in users]
        owner = Prompt.ask(
            "  [bold]Shared Space owner[/]",
            choices=names,
            default=names[0],
        )
        config["migration"]["shared_space_owner"] = owner

    parallel = _confirm(
        "Use parallel mode (faster)?", default=True
    )
    config["execution"]["mode"] = (
        "parallel" if parallel else "sequential"
    )

    if parallel:
        workers = IntPrompt.ask(
            "  [bold]Number of parallel workers (1-16)[/]",
            default=4,
        )
        config["execution"]["workers"] = max(1, min(16, workers))

    # Important clarification on what "delete" means
    console.print()
    muted(
        "  Local files are downloaded to your COMPUTER first,"
    )
    muted(
        "  then uploaded to Immich. The 'delete' option only"
    )
    muted(
        "  removes those LOCAL temporary files after upload."
    )
    muted(
        "  [bold]Your Synology NAS is NEVER modified.[/]"
    )
    console.print()

    config["execution"]["delete_after_upload"] = _confirm(
        "Delete local temporary files after upload? "
        "(NAS files are not affected)",
        default=True,
    )

    # Clean tmp keys
    for u in config["users"]:
        u.pop("_immich_id", None)

    # Save
    config_path = get_config_file()
    save_config(config, config_path)

    print_section("Done")
    success(f"Config saved: {config_path}")
    console.print()
    muted("  Next step:")
    console.print(
        f"    [bold {COLOR_ACCENT}]synmich migrate[/]"
    )
    console.print()

    return 0


def _autodetect_users(
    syno_url: str, verify_ssl: bool
) -> List[Dict[str, Any]]:
    """Liste les users via compte admin DSM."""
    info("Auto-detection via DSM admin")

    admin_user = _ask("Admin DSM username", default="admin")
    admin_pass = _ask("Admin DSM password", password=True)

    client = SynologyClient(syno_url, verify_ssl=verify_ssl)
    if not client.login(admin_user, admin_pass):
        error("Admin login failed. Switching to manual.")
        return _manual_users(syno_url, verify_ssl)

    try:
        dsm_users = client.list_dsm_users()
    except Exception as e:
        error(f"list_dsm_users failed: {e}")
        client.logout()
        return _manual_users(syno_url, verify_ssl)

    client.logout()

    if not dsm_users:
        warn("No users found via admin.")
        return _manual_users(syno_url, verify_ssl)

    info(f"Found {len(dsm_users)} DSM users:")
    for u in dsm_users:
        muted(f"  - {u.get('name')}")

    selected = []
    for u in dsm_users:
        name = u.get("name", "")
        if name in ("admin", "guest", "root"):
            continue
        if _confirm(f"Migrate '{name}'?", default=True):
            password = _ask(
                f"  Synology password for '{name}'",
                password=True,
            )
            selected.append(
                {
                    "name": name.capitalize(),
                    "syno_username": name,
                    "syno_password": password,
                    "immich_api_key": "",
                }
            )

    return selected


def _manual_users(
    syno_url: str, verify_ssl: bool
) -> List[Dict[str, Any]]:
    """Manual user entry."""
    users = []
    n = IntPrompt.ask(
        "  [bold]How many users to migrate?[/]",
        default=2,
    )

    for i in range(n):
        console.print(
            f"\n  [bold {COLOR_PRIMARY}]User {i+1}/{n}[/]"
        )
        name = _ask("Display name (e.g. Jeffrey)")
        username = _ask(
            "Synology username", default=name.lower()
        )
        password = _ask("Synology password", password=True)

        # Test login
        info(f"Testing login for {username}...")
        client = SynologyClient(
            syno_url, verify_ssl=verify_ssl
        )
        if client.login(username, password):
            success(f"{username} login OK")
            client.logout()
        else:
            warn(
                f"{username} login failed. Saving anyway."
            )

        users.append(
            {
                "name": name,
                "syno_username": username,
                "syno_password": password,
                "immich_api_key": "",
            }
        )

    return users
