"""m7 regression: the default suite + built-in fixtures ship inside the package
so `tooldrift snapshot --provider deepseek --from-fixtures` works for an
installed user regardless of the process CWD.

Before the fix, `_DEFAULT_SUITE` and `_FIXTURES` were CWD-relative and the wheel
shipped neither `examples/` nor `tests/`, so the documented zero-key demo failed
with "could not load suite" from any non-repo directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tooldrift import _bundled
from tooldrift.cli import app

ROOT = Path(__file__).resolve().parent.parent

runner = CliRunner()


def test_bundled_suite_and_fixtures_exist():
    assert _bundled.default_suite_path().is_file()
    assert _bundled.builtin_fixture_path("deepseek_tool_calls.json").is_file()
    assert _bundled.builtin_fixture_path("qwen_tool_calls.json").is_file()


def test_bundled_matches_repo_copies():
    """Guard against drift: the bundled runtime copies equal the repo copies."""
    assert (
        _bundled.default_suite_path().read_bytes()
        == (ROOT / "examples" / "suite.weather.yaml").read_bytes()
    )
    for name in ("deepseek_tool_calls.json", "qwen_tool_calls.json"):
        assert (
            _bundled.builtin_fixture_path(name).read_bytes()
            == (ROOT / "tests" / "fixtures" / name).read_bytes()
        )


def test_snapshot_works_from_non_repo_cwd(tmp_path, monkeypatch):
    """Run from a dir with no examples/ or tests/ nearby → still exit 0."""
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "deepseek.json"
    res = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--from-fixtures", "-q", "-o", str(out)],
    )
    assert res.exit_code == 0, res.output
    assert out.is_file()
    snap = json.loads(out.read_text())
    assert snap["provider"] == "deepseek"


def test_snapshot_stdout_from_non_repo_cwd(tmp_path, monkeypatch):
    """Default-suite stdout snapshot works from a non-repo CWD too."""
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--from-fixtures", "--quiet"],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["provider"] == "deepseek"
