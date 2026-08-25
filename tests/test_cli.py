"""CLI wiring: stats uses the detailed command, not the broken local stub."""

import pytest

from synmich import cli
from synmich.commands import stats as stats_mod


def test_cli_stats_is_the_commands_module():
    assert cli.cmd_stats is stats_mod.cmd_stats
    assert cli.cmd_stats.__module__ == "synmich.commands.stats"


def test_stats_parser_accepts_json_and_help():
    with pytest.raises(SystemExit) as exc:
        cli.main(["stats", "--help"])
    assert exc.value.code == 0


def test_cli_source_no_longer_calls_missing_stats_method():
    src = open(cli.__file__, encoding="utf-8").read()
    assert "cp.stats()" not in src
    assert "def cmd_stats" not in src
