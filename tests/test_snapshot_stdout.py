"""m6 regression: `tooldrift snapshot` (no -o, no -q) must keep stdout as clean,
pipeable JSON — the human rich table goes to stderr.

Before the fix the rich table was printed to stdout ahead of the snapshot JSON,
so `tooldrift snapshot ... | jq` (or `| python -m json.tool`) failed even though
the inline doc claimed stdout was pipeable. The --output and --quiet paths were
already fine; only the default stdout path was broken.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tooldrift.cli import app

ROOT = Path(__file__).resolve().parent.parent

# res.stdout is stdout-only and res.stderr is separate (click 9 semantics), so
# we can pin "stdout is clean JSON" and "the table is on stderr" directly.
runner = CliRunner()


def test_snapshot_default_stdout_is_clean_json():
    res = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--from-fixtures"],
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)  # raises if the table pollutes stdout
    assert payload["provider"] == "deepseek"
    assert "get_weather" in payload["tools"]


def test_snapshot_table_goes_to_stderr():
    res = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--from-fixtures"],
    )
    assert res.exit_code == 0, res.output
    # The human table (with its suite header) is on stderr, not stdout.
    assert "suite=weather" in res.stderr
    assert "suite=weather" not in res.stdout


def test_snapshot_quiet_stdout_is_clean_json():
    """--quiet already suppressed the table; keep it clean."""
    res = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--from-fixtures", "--quiet"],
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["provider"] == "deepseek"
