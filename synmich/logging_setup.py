"""Shared logging setup for CLI and GUI entry points."""

import logging

from synmich.config import get_log_file


def setup_logging(verbose: bool = False) -> None:
    """Write synmich logs to ~/.config/synmich/migration.log."""
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
