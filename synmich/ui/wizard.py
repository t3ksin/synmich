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

    # v1.0.4: real URL validation
    import requests, urllib3
    urllib3.disable_warnings()

    for url_attempt in range(3):
        syno_url = _ask(
            "Synology URL (https://IP:PORT)",
        )
        if not syno_url or not syno_url.startswith(("http://", "https://")):
            warn("Please enter a valid URL starting with http:// or https://")
            continue

        verify_ssl = _confirm(
            "Verify SSL certificate?", default=False
        )

        info("Testing connection...")
        try:
            r = requests.get(
                f"{syno_url.rstrip('/')}/webapi/query.cgi",
                params={"api": "SYNO.API.Info", "version": "1",
                        "method": "query", "query": "SYNO.API.Auth"},
                verify=verify_ssl, timeout=10,
            )
            if r.status_code == 200 and r.json().get("success"):
                success(f"Synology API reachable at {syno_url}")
                if syno_url.startswith("http://"):
                    warn(
                        "Using HTTP - credentials will be sent unencrypted."
                    )
                    muted(
                        "  For better security, use HTTPS (port 5001 by default)."
                    )
                config["synology"]["url"] = syno_url
                config["synology"]["verify_ssl"] = verify_ssl
                break
            else:
                warn(f"Server responded but API not found. Check URL/port.")
        except requests.exceptions.SSLError:
            warn("SSL error. Try answering 'n' to 'Verify SSL certificate?'")
        except requests.exceptions.ConnectTimeout:
            warn(f"Cannot reach {syno_url}. Check IP/port/network.")
        except requests.exceptions.ConnectionError as e:
            warn(f"Connection refused or unreachable: {e}")
        except Exception as e:
            warn(f"Error: {e}")

        if url_attempt < 2:
            info(f"Please try again (attempt {url_attempt + 2}/3)")
    else:
        error("Cannot reach Synology after 3 attempts. Aborting.")
        return 1

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

    # v1.0.4: real URL validation for Immich
    import requests
    for immich_attempt in range(3):
        immich_url = _ask(
            "Immich URL (http://IP:PORT)",
        )
        if not immich_url or not immich_url.startswith(("http://", "https://")):
            warn("Please enter a valid URL starting with http:// or https://")
            continue
        try:
            r = requests.get(
                f"{immich_url.rstrip('/')}/api/server/ping",
                timeout=10,
            )
            if r.status_code == 200:
                success(f"Immich reachable at {immich_url}")
                break
            else:
                warn(f"Server returned {r.status_code}. Check URL.")
        except Exception as e:
            warn(f"Cannot reach Immich: {e}")
        if immich_attempt < 2:
            info(f"Please try again (attempt {immich_attempt + 2}/3)")
    else:
        error("Cannot reach Immich after 3 attempts. Aborting.")
        return 1
    config["immich"]["url"] = immich_url

    info("Testing Immich connection per user...")
    for u in users:
        # v1.0.4: retry loop for Immich API key
        api_ok = False
        for attempt in range(3):
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
                api_ok = True
                break
            except Exception as e:
                if attempt < 2:
                    warn(
                        f"Invalid API key for {u['name']}. "
                        f"Attempt {attempt + 1}/3 - please retry."
                    )
                    u["immich_api_key"] = ""
                else:
                    error(
                        f"API key for {u['name']} invalid after 3 attempts. "
                        f"You can fix in config later."
                    )

    # ============ Step 4: Options ============
    print_section("Step 4/4 · Options")

    # v1.0.4: migrate everything by default (advanced users can edit YAML)
    config["migration"]["include_albums"] = True
    config["migration"]["include_timeline"] = True

    # Which albums to migrate ("what" axis, independent of the shared mode)
    if config["migration"]["include_albums"]:
        console.print()
        muted("  Which albums do you want to migrate?")
        console.print()
        muted("    [bold]all[/]     Every album (default)")
        muted("    [bold]select[/]  Pick albums interactively")
        muted("                  A picker opens right after setup.")
        console.print()
        scope = Prompt.ask(
            "  [bold]Albums to migrate[/]",
            choices=["all", "select"],
            default="all",
        )
        config["migration"]["albums_mode"] = scope
        if scope == "select":
            config["migration"].setdefault("selected_albums", [])
            success(
                "Noted — an album picker will open right after setup."
            )

    # Shared albums mode (the "how": SHARED albums ONLY)
    if config["migration"]["include_albums"]:
        console.print()
        muted("  How should SHARED albums be organized in Immich?")
        console.print()
        muted("    [bold]mirror-syno[/]  Same as Synology (recommended)")
        muted("                  Personal albums stay personal.")
        muted("                  Shared albums stay shared, with the same permissions.")
        console.print()
        muted("    [bold]separate[/]     Each user keeps only their own photos")
        muted("                  If a shared album has photos from multiple users,")
        muted("                  each user gets an album with only their photos.")
        muted("                  Albums are independent, no sharing in Immich.")
        console.print()
        muted("    [bold]skip[/]         No albums in Immich")
        muted("                  Photos still uploaded to each user\'s library.")
        muted("                  Visible in timeline but not grouped in albums.")
        console.print()
        mode = Prompt.ask(
            "  [bold]Shared albums mode[/]",
            choices=["mirror-syno", "separate", "skip"],
            default="mirror-syno",
        )
        # Map user-facing names to internal config values (backward compat)
        _mode_map = {"mirror-syno": "link", "separate": "duplicate", "skip": "ignore"}
        config["migration"]["shared_albums_mode"] = _mode_map[mode]

    config["migration"]["include_shared_space"] = _confirm(
        "Migrate Shared Space photos? (recommended if you use it)",
    )

    if config["migration"]["include_shared_space"]:
        names = [u["name"] for u in users]
        muted("  Who should own these photos in Immich? (recommended: your main account)")
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
    muted("  Setup complete — starting the migration now.")
    muted(
        f"  (next time, just run "
        f"[bold {COLOR_ACCENT}]synmich migrate[/])"
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
    # v1.0.4: validate numeric input with retry
    n = None
    while n is None:
        try:
            n = IntPrompt.ask(
                "  [bold]How many users to migrate?[/]",
                default=2,
            )
            if n < 1:
                warn("Please enter a number greater than 0.")
                n = None
            elif n > 20:
                warn("Maximum 20 users supported. Please enter a smaller number.")
                n = None
        except (ValueError, TypeError):
            warn("Please enter a valid number (digits only).")
            n = None
        except Exception:
            warn("Invalid input. Please enter a number between 1 and 20.")
            n = None

    for i in range(n):
        console.print(
            f"\n  [bold {COLOR_PRIMARY}]User {i+1}/{n}[/]"
        )
        # v1.0.4: force non-empty display name
        name = ""
        while not name or not name.strip():
            name = _ask("Display name (e.g. Jeffrey)")
            if not name or not name.strip():
                warn("Display name cannot be empty.")
        name = name.strip()
        username = _ask(
            "Synology username", default=name.lower()
        )
        password = _ask("Synology password", password=True)

        # v1.0.4: Test login with retry loop
        login_ok = False
        for attempt in range(3):
            info(f"Testing login for {username}...")
            client = SynologyClient(
                syno_url, verify_ssl=verify_ssl
            )
            if client.login(username, password):
                success(f"{username} login OK")
                client.logout()
                login_ok = True
                break
            else:
                if attempt < 2:
                    warn(
                        f"Login failed. Attempt {attempt + 1}/3 - please retry."
                    )
                    # No default username this time (it was wrong)
                    new_username = ""
                    while not new_username or not new_username.strip():
                        new_username = _ask("Synology username")
                        if not new_username or not new_username.strip():
                            warn("Username cannot be empty.")
                    username = new_username.strip()
                    password = _ask("Synology password", password=True)
                else:
                    error(
                        f"Login failed after 3 attempts. Skipping {username}."
                    )

        if login_ok:
            users.append(
                {
                    "name": name,
                    "syno_username": username,
                    "syno_password": password,
                    "immich_api_key": "",
                }
            )

    return users
