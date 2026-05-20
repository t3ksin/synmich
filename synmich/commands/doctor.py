"""synmich doctor — Full system diagnostic (v1.1.0).

Checks:
- System (Python, OS, disk)
- Config (existence, validity)
- Synology connections (per user)
- Immich connection (per user)
- Immich state (queue, space)
- 2FA device tokens
- Current checkpoint
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from synmich.ui.cli_helpers import (
    console, info, success, warn, error, muted,
    section, COLOR_PRIMARY, COLOR_OK, COLOR_WARN, COLOR_ERROR, COLOR_MUTED,
)


def _check_system() -> List[tuple]:
    """System checks."""
    results = []

    py_version = ".".join(map(str, sys.version_info[:3]))
    results.append(("ok", "Python", py_version))

    if sys.platform.startswith("linux"):
        results.append(("ok", "OS", "Linux"))
    elif sys.platform == "darwin":
        results.append(("ok", "OS", "macOS"))
    elif sys.platform == "win32":
        results.append(("ok", "OS", "Windows"))
    else:
        results.append(("warn", "OS", f"Unknown ({sys.platform})"))

    # Disk space
    home = Path.home()
    total, used, free = shutil.disk_usage(home)
    free_gb = free / (1024 ** 3)
    if free_gb < 1:
        results.append(("error", "Free disk", f"{free_gb:.1f} GB (critically low)"))
    elif free_gb < 10:
        results.append(("warn", "Free disk", f"{free_gb:.1f} GB"))
    else:
        results.append(("ok", "Free disk", f"{free_gb:.1f} GB"))

    return results


def _check_config() -> List[tuple]:
    """Config checks."""
    results = []

    from synmich.config import load_config, get_config_file

    config_file = get_config_file()
    if not config_file.exists():
        results.append(("error", "Config file", f"Missing: {config_file}"))
        results.append(("error", "Hint", "Run 'synmich init' to create it"))
        return results

    results.append(("ok", "Config file", str(config_file)))

    try:
        config = load_config()
        n_users = len(config.get("users", []))
        results.append(("ok", "Users", f"{n_users} configured"))
        for u in config.get("users", []):
            name = u.get("name", "?")
            has_api_key = bool(u.get("immich_api_key"))
            if has_api_key:
                results.append(("ok", f"  {name}", "API key set"))
            else:
                results.append(("error", f"  {name}", "Missing Immich API key"))
    except Exception as e:
        results.append(("error", "Config valid", f"Cannot load: {e}"))

    return results


def _check_synology(config: Dict[str, Any]) -> List[tuple]:
    """Test the Synology connection for each user."""
    results = []
    from synmich.core.synology import SynologyClient

    syno_url = (
        config.get("synology", {}).get("url")
        or config.get("synology", {}).get("base_url", "")
    )
    verify_ssl = config.get("synology", {}).get("verify_ssl", False)

    if not syno_url:
        results.append(("error", "Synology URL", "Not configured"))
        return results

    results.append(("ok", "Synology URL", syno_url))

    for u in config.get("users", []):
        name = u.get("name", "?")
        username = u.get("syno_username", u.get("synology", {}).get("username", ""))
        password = u.get("syno_password", u.get("synology", {}).get("password", ""))

        if not username or not password:
            results.append(("error", f"  {name}", "Missing credentials"))
            continue

        try:
            client = SynologyClient(syno_url, verify_ssl=verify_ssl)
            # Use lambda that returns empty to skip OTP prompt during doctor
            if client.login(username, password, otp_provider=lambda u: ""):
                results.append(("ok", f"  {name}", "Connected"))
                client.logout()
            else:
                # Maybe 2FA required and we provided empty OTP
                results.append((
                    "warn", f"  {name}",
                    "Login failed (2FA may be required - run migrate to test)",
                ))
        except Exception as e:
            results.append(("error", f"  {name}", str(e)[:60]))

    return results


def _check_immich(config: Dict[str, Any]) -> List[tuple]:
    """Test the Immich connection for each user."""
    results = []
    import requests

    immich_url = (
        config.get("immich", {}).get("url")
        or config.get("immich", {}).get("base_url", "")
    )

    if not immich_url:
        results.append(("error", "Immich URL", "Not configured"))
        return results

    # Server ping
    try:
        r = requests.get(
            f"{immich_url.rstrip('/')}/api/server/ping",
            timeout=10,
        )
        if r.status_code == 200:
            results.append(("ok", "Immich URL", immich_url))
        else:
            results.append((
                "error", "Immich URL",
                f"Unreachable (status {r.status_code})",
            ))
            return results
    except Exception as e:
        results.append(("error", "Immich URL", f"Unreachable: {e}"))
        return results

    # Version
    try:
        r = requests.get(
            f"{immich_url.rstrip('/')}/api/server/version",
            timeout=10,
        ).json()
        version = f"{r.get('major', '?')}.{r.get('minor', '?')}.{r.get('patch', '?')}"
        results.append(("ok", "Immich version", version))
    except Exception:
        pass

    # Test API key per user
    for u in config.get("users", []):
        name = u.get("name", "?")
        api_key = u.get("immich_api_key", "")
        if not api_key:
            results.append(("error", f"  {name}", "No API key"))
            continue

        try:
            r = requests.get(
                f"{immich_url.rstrip('/')}/api/users/me",
                headers={"x-api-key": api_key},
                timeout=10,
            )
            if r.status_code == 200:
                me = r.json()
                email = me.get("email", "?")
                is_admin = me.get("isAdmin", False)
                role = "admin" if is_admin else "user"
                results.append(("ok", f"  {name}", f"{email} ({role})"))
            else:
                results.append((
                    "error", f"  {name}",
                    f"Invalid API key (status {r.status_code})",
                ))
        except Exception as e:
            results.append(("error", f"  {name}", str(e)[:60]))

    # Check job queue
    admin_keys = [u.get("immich_api_key", "") for u in config.get("users", [])]
    for key in admin_keys:
        if not key:
            continue
        try:
            r = requests.get(
                f"{immich_url.rstrip('/')}/api/jobs",
                headers={"x-api-key": key},
                timeout=10,
            )
            if r.status_code == 200:
                jobs = r.json()
                active_jobs = sum(
                    j.get("jobCounts", {}).get("active", 0)
                    for j in jobs.values()
                ) if isinstance(jobs, dict) else 0
                if active_jobs > 100:
                    results.append((
                        "warn", "Immich queue",
                        f"{active_jobs} jobs active (busy)",
                    ))
                else:
                    results.append(("ok", "Immich queue", f"{active_jobs} jobs"))
                break
        except Exception:
            pass

    return results


def _check_devices() -> List[tuple]:
    """2FA device token checks."""
    results = []

    try:
        from synmich.core.device_tokens import list_devices
        devices = list_devices()
        if not devices:
            results.append(("ok", "Device tokens", "None (no 2FA accounts)"))
        else:
            results.append(("ok", "Device tokens", f"{len(devices)} saved"))
            for k in devices.keys():
                results.append(("ok", f"  {k}", "✓"))
    except ImportError:
        results.append(("warn", "Device tokens", "Not available (pre-v1.0.4)"))

    return results


def _check_checkpoints() -> List[tuple]:
    """Checkpoint checks."""
    results = []

    try:
        from synmich.core.checkpoint import list_all_checkpoints
        cps = list_all_checkpoints()
        if not cps:
            results.append(("ok", "Checkpoints", "None"))
        else:
            results.append(("ok", "Checkpoints", f"{len(cps)} found"))
            for cp in cps[:5]:
                counters = cp.get("counters", {})
                results.append((
                    "ok", f"  {cp['hash'][:8]}",
                    f"{counters.get('uploaded', 0):,} uploaded · {cp.get('albums_done', 0)} albums",
                ))
    except (ImportError, AttributeError):
        # Legacy checkpoint
        legacy = Path.home() / ".config/synmich/checkpoint.json"
        if legacy.exists():
            results.append(("warn", "Checkpoint", "Legacy format (will be migrated on next run)"))
        else:
            results.append(("ok", "Checkpoint", "None"))

    return results


def _print_results(results: List[tuple], section_name: str) -> int:
    """Print the results. Return the number of errors."""
    console.print(f"\n  [bold {COLOR_PRIMARY}]{section_name}[/]")
    errors = 0
    for status, label, value in results:
        if status == "ok":
            console.print(f"    [{COLOR_OK}]✓[/] {label:<22} [{COLOR_MUTED}]{value}[/]")
        elif status == "warn":
            console.print(f"    [{COLOR_WARN}]⚠[/] {label:<22} [{COLOR_WARN}]{value}[/]")
        elif status == "error":
            console.print(f"    [{COLOR_ERROR}]✗[/] {label:<22} [{COLOR_ERROR}]{value}[/]")
            errors += 1
    return errors


def cmd_doctor(args) -> int:
    """Run the full diagnostic."""
    console.print()
    console.rule(f"[bold {COLOR_PRIMARY}]synmich doctor[/]")
    console.print()

    total_errors = 0

    # System
    total_errors += _print_results(_check_system(), "System")

    # Config
    config_results = _check_config()
    total_errors += _print_results(config_results, "Configuration")

    # Skip the rest if there is no config
    config_ok = not any(s == "error" for s, _, _ in config_results)
    if not config_ok:
        console.print()
        console.rule(
            f"[bold {COLOR_ERROR}]Diagnostic failed - {total_errors} error(s)[/]",
            style=COLOR_ERROR,
        )
        return 1

    # Load config for further checks
    from synmich.config import load_config
    try:
        config = load_config()
    except Exception:
        return 1

    total_errors += _print_results(_check_synology(config), "Synology connections")
    total_errors += _print_results(_check_immich(config), "Immich connections")
    total_errors += _print_results(_check_devices(), "2FA device tokens")
    total_errors += _print_results(_check_checkpoints(), "Checkpoints")

    console.print()
    if total_errors == 0:
        console.rule(
            f"[bold {COLOR_OK}]All systems operational[/]",
            style=COLOR_OK,
        )
        return 0
    else:
        console.rule(
            f"[bold {COLOR_ERROR}]{total_errors} issue(s) found[/]",
            style=COLOR_ERROR,
        )
        return 1
