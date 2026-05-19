"""synmich CLI — main entry point."""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from rich.table import Table

from synmich import __version__
from synmich.config import (
    get_config_file,
    get_checkpoint_file,
    get_log_file,
    load_config,
    save_config,
    validate_config,
)
from synmich.core.checkpoint import Checkpoint
from synmich.core.immich import ImmichClient
from synmich.core.migrator import (
    Migrator,
    MigrationControl,
    MigrationStats,
    UserSession,
)
from synmich.core.synology import SynologyClient
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
from synmich.ui.wizard import run_wizard


def setup_logging(verbose: bool = False) -> None:
    log_file = get_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        )
    )

    logger = logging.getLogger("synmich")
    logger.setLevel(
        logging.DEBUG if verbose else logging.INFO
    )
    logger.handlers.clear()
    logger.addHandler(fh)


def cmd_init(args) -> int:
    """synmich init — Interactive wizard."""
    return run_wizard()


def cmd_config(args) -> int:
    """synmich config — Affiche le chemin de la config."""
    print_banner()
    path = get_config_file()
    muted(f"  Config file: {path}")
    muted(f"  Checkpoint:  {get_checkpoint_file()}")
    muted(f"  Log:         {get_log_file()}")
    console.print()
    if not path.exists():
        warn(
            f"Config not found. Run [bold]synmich init[/] to create."
        )
        return 1
    config = load_config()
    errors = validate_config(config)
    if errors:
        error("Config has errors:")
        for e in errors:
            console.print(f"    [red]- {e}[/]")
        return 1
    success("Config valid")
    return 0


def _build_sessions(
    config: dict,
) -> Optional[List[UserSession]]:
    """Login Synology + Immich pour chaque user."""

    syno_url = config["synology"]["url"]
    verify_ssl = config["synology"].get(
        "verify_ssl", False
    )
    immich_url = config["immich"]["url"]
    exec_cfg = config.get("execution", {})
    max_retries = int(exec_cfg.get("max_retries", 5))
    backoff = int(
        exec_cfg.get("retry_backoff_seconds", 3)
    )

    sessions = []
    for u in config["users"]:
        info(f"Login Synology: {u['name']}...")
        syno = SynologyClient(
            syno_url,
            verify_ssl=verify_ssl,
            max_retries=max_retries,
            retry_backoff_s=backoff,
        )
        ok = syno.login(
            u["syno_username"], u["syno_password"]
        )
        if not ok:
            error(f"Synology login failed: {u['name']}")
            return None

        try:
            syno_id = syno.me()
        except Exception as e:
            error(f"syno.me() failed: {e}")
            return None

        if syno_id is None:
            warn(
                f"{u['name']}: syno_user_id unavailable, "
                f"using fallback index"
            )
            syno_id = (
                len(sessions) + 1
            )  # fallback simple

        success(
            f"  ✓ {u['name']} → syno_id={syno_id}"
        )

        immich = ImmichClient(
            immich_url,
            u["immich_api_key"],
            max_retries=max_retries,
            retry_backoff_s=backoff,
        )
        try:
            me = immich.me()
        except Exception as e:
            error(f"Immich /me failed for {u['name']}: {e}")
            return None
        success(
            f"  ✓ Immich {u['name']} → {me.get('email')}"
        )

        sessions.append(
            UserSession(
                name=u["name"],
                syno=syno,
                immich=immich,
                syno_user_id=syno_id,
                immich_user_id=me["id"],
            )
        )

    return sessions


def cmd_migrate(args) -> int:
    """synmich migrate — Run the migration."""

    print_banner()

    config = load_config()
    errs = validate_config(config)
    if errs:
        error("Invalid config:")
        for e in errs:
            console.print(f"    [red]- {e}[/]")
        muted("\n  Run: [bold]synmich init[/] first")
        return 1

    # CLI overrides
    if args.albums_only:
        config["migration"]["include_timeline"] = False
    if args.timeline_only:
        config["migration"]["include_albums"] = False
    if args.sequential:
        config["execution"]["mode"] = "sequential"
    if args.workers:
        config["execution"]["workers"] = args.workers

    if args.reset:
        cp = Checkpoint(get_checkpoint_file())
        cp.reset()
        success("Checkpoint reset")

    print_section("Connection")

    sessions = _build_sessions(config)
    if not sessions:
        return 1

    if args.dry_run:
        print_section("Migration (DRY RUN)")
        info(
            "Dry run mode: no files will be downloaded, "
            "no albums will be created, no assets will be "
            "uploaded to Immich."
        )
    else:
        print_section("Migration")

    stats = MigrationStats()
    control = MigrationControl()
    checkpoint = Checkpoint(get_checkpoint_file())

    setup_logging(
        verbose=config.get("execution", {}).get(
            "verbose", False
        )
        or args.verbose
    )

    migrator = Migrator(
        config=config,
        sessions=sessions,
        checkpoint=checkpoint,
        stats=stats,
        control=control,
        dry_run=args.dry_run,
    )

    # If --no-tui or --dry-run: run without dashboard
    if args.no_tui or args.dry_run:
        try:
            migrator.run()
        except KeyboardInterrupt:
            control.stop()
            warn("Interrupted")
        s = stats
        if args.dry_run:
            success(
                f"Dry run done. Would upload={s.uploaded} "
                f"items across {s.albums_done} albums"
            )
        else:
            success(
                f"Done. Uploaded={s.uploaded} "
                f"Duplicate={s.duplicate} Failed={s.failed}"
            )
        return 0

    # Otherwise: Textual dashboard
    from synmich.ui.dashboard import MigrationApp

    app = MigrationApp(
        stats=stats,
        control=control,
        migrate_callable=migrator.run,
    )
    app.run()
    return 0


def cmd_users(args) -> int:
    """synmich users — List configured users + status."""
    print_banner()
    config = load_config()
    if not config:
        error("No config. Run synmich init.")
        return 1

    table = Table(
        title="Users",
        title_style=f"bold {COLOR_PRIMARY}",
        border_style="cyan",
    )
    table.add_column("Name", style="bold")
    table.add_column("Synology user")
    table.add_column("Synology status")
    table.add_column("Immich status")

    syno_url = config["synology"]["url"]
    verify_ssl = config["synology"].get(
        "verify_ssl", False
    )
    immich_url = config["immich"]["url"]

    for u in config["users"]:
        syno = SynologyClient(syno_url, verify_ssl=verify_ssl)
        syno_status = (
            "[green]✓[/]"
            if syno.login(
                u["syno_username"], u["syno_password"]
            )
            else "[red]✗[/]"
        )
        if "✓" in syno_status:
            syno.logout()

        immich = ImmichClient(
            immich_url, u["immich_api_key"]
        )
        try:
            immich.me()
            imm_status = "[green]✓[/]"
        except Exception:
            imm_status = "[red]✗[/]"

        table.add_row(
            u["name"],
            u["syno_username"],
            syno_status,
            imm_status,
        )

    console.print(table)
    return 0


def cmd_albums(args) -> int:
    """synmich albums — List detected albums."""
    print_banner()
    config = load_config()
    if not config:
        error("No config.")
        return 1

    syno_url = config["synology"]["url"]
    verify_ssl = config["synology"].get(
        "verify_ssl", False
    )

    all_albums = {}
    for u in config["users"]:
        syno = SynologyClient(syno_url, verify_ssl=verify_ssl)
        if not syno.login(
            u["syno_username"], u["syno_password"]
        ):
            warn(f"Skipped {u['name']}: login failed")
            continue
        try:
            albums = syno.list_albums()
        except Exception as e:
            warn(f"{u['name']}: {e}")
            syno.logout()
            continue

        for a in albums:
            pp = (
                a.get("passphrase")
                or f"local-{u['name']}-{a['id']}"
            )
            if pp not in all_albums:
                all_albums[pp] = {
                    "name": a["name"],
                    "items": a.get("item_count", 0),
                    "shared": a.get("shared", False),
                    "owner": (
                        a.get("additional", {})
                        .get("sharing_info", {})
                        .get("owner", {})
                        .get("name", "?")
                    ),
                    "visible_by": [u["name"]],
                }
            else:
                all_albums[pp]["visible_by"].append(
                    u["name"]
                )
        syno.logout()

    table = Table(
        title=f"Albums ({len(all_albums)} uniques)",
        title_style=f"bold {COLOR_PRIMARY}",
        border_style="cyan",
    )
    table.add_column("Album", style="bold")
    table.add_column("Items", justify="right")
    table.add_column("Shared", justify="center")
    table.add_column("Owner")
    table.add_column("Visible by")

    for pp, a in sorted(
        all_albums.items(), key=lambda x: x[1]["name"]
    ):
        table.add_row(
            a["name"],
            str(a["items"]),
            "🤝" if a["shared"] else "",
            a["owner"],
            ", ".join(a["visible_by"]),
        )

    console.print(table)
    return 0


def cmd_verify(args) -> int:
    """synmich verify — Compare Syno vs Immich."""
    print_banner()
    config = load_config()
    if not config:
        error("No config.")
        return 1

    immich_url = config["immich"]["url"]

    table = Table(
        title="Verification",
        title_style=f"bold {COLOR_PRIMARY}",
    )
    table.add_column("User", style="bold")
    table.add_column("Immich albums", justify="right")
    table.add_column("Immich assets", justify="right")

    for u in config["users"]:
        immich = ImmichClient(
            immich_url, u["immich_api_key"]
        )
        try:
            albums = immich.list_albums()
            assets = immich.search_assets(size=1)
        except Exception as e:
            warn(f"{u['name']}: {e}")
            continue

        total_album_assets = sum(
            a.get("assetCount", 0) for a in albums
        )
        total_assets = (
            assets.get("assets", {}).get("total", 0)
        )

        table.add_row(
            u["name"],
            f"{len(albums)} ({total_album_assets} in albums)",
            str(total_assets),
        )

    console.print(table)
    return 0


def cmd_logs(args) -> int:
    """synmich logs — Affiche le dernier log."""
    log_file = get_log_file()
    if not log_file.exists():
        warn("No log file yet.")
        return 1
    with open(log_file) as f:
        lines = f.readlines()
    tail = lines[-args.lines :]
    for ln in tail:
        console.print(ln.rstrip())
    return 0


def cmd_stats(args) -> int:
    """synmich stats — Stats du checkpoint."""
    print_banner()
    cp = Checkpoint(get_checkpoint_file())
    s = cp.stats()

    table = Table(
        title="Checkpoint stats",
        title_style=f"bold {COLOR_PRIMARY}",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row(
        "Uploaded (new)",
        f"[green]{s['uploaded']}[/]",
    )
    table.add_row(
        "Duplicate (skipped)",
        f"[yellow]{s['duplicate']}[/]",
    )
    table.add_row(
        "Failed",
        f"[red]{s['failed']}[/]",
    )
    table.add_row(
        "Total assets in Immich",
        str(s["total_in_immich"]),
    )
    table.add_row(
        "Albums marked done",
        str(s["albums_done"]),
    )
    table.add_row(
        "Users with uploads",
        str(s["users_with_uploads"]),
    )

    console.print(table)
    return 0


def cmd_reset(args) -> int:
    """synmich reset — Reset checkpoint."""
    cp = Checkpoint(get_checkpoint_file())
    cp.reset()
    success("Checkpoint reset")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="synmich",
        description=(
            f"synmich v{__version__} — "
            "Synology Photos → Immich migration"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"synmich {__version__}",
    )

    sub = parser.add_subparsers(
        dest="command", required=True
    )

    # init
    p_init = sub.add_parser(
        "init", help="Interactive setup wizard"
    )
    p_init.set_defaults(func=cmd_init)

    # config
    p_cfg = sub.add_parser(
        "config", help="Show config paths and validate"
    )
    p_cfg.set_defaults(func=cmd_config)

    # migrate
    p_mig = sub.add_parser(
        "migrate", help="Run migration"
    )
    p_mig.add_argument(
        "--albums-only", action="store_true"
    )
    p_mig.add_argument(
        "--timeline-only", action="store_true"
    )
    p_mig.add_argument(
        "--sequential", action="store_true"
    )
    p_mig.add_argument("--workers", type=int)
    p_mig.add_argument(
        "--reset",
        action="store_true",
        help="Reset checkpoint",
    )
    p_mig.add_argument(
        "--no-tui",
        action="store_true",
        help="Don't show Textual dashboard",
    )
    p_mig.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Simulate the migration without "
            "downloading or uploading anything"
        ),
    )
    p_mig.add_argument(
        "-v", "--verbose", action="store_true"
    )
    p_mig.set_defaults(func=cmd_migrate)

    # users
    p_usr = sub.add_parser(
        "users", help="List configured users + status"
    )
    p_usr.set_defaults(func=cmd_users)

    # albums
    p_alb = sub.add_parser(
        "albums", help="List detected albums"
    )
    p_alb.set_defaults(func=cmd_albums)

    # verify
    p_ver = sub.add_parser(
        "verify", help="Verify Immich state"
    )
    p_ver.set_defaults(func=cmd_verify)

    # logs
    p_log = sub.add_parser(
        "logs", help="Show recent log lines"
    )
    p_log.add_argument(
        "-n", "--lines", type=int, default=50
    )
    p_log.set_defaults(func=cmd_logs)

    # stats
    p_st = sub.add_parser(
        "stats", help="Show checkpoint stats"
    )
    p_st.set_defaults(func=cmd_stats)

    # reset
    p_rs = sub.add_parser(
        "reset", help="Reset checkpoint"
    )
    p_rs.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
