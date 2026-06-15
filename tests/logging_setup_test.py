import logging

from synmich.logging_setup import setup_logging


def test_setup_logging_creates_migration_log(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    setup_logging()
    logging.getLogger("synmich").error("test log entry")

    log_file = tmp_path / "synmich" / "migration.log"
    assert log_file.exists()
    assert "test log entry" in log_file.read_text(encoding="utf-8")
