"""m6 tests: the `snapshot` no-builtin-fixture guard fix.

Before the fix, `tooldrift snapshot --provider kimi --from-fixtures` crashed
with `IsADirectoryError: [Errno 21] Is a directory: '.'` because
`Path(_FIXTURES.get(provider, ""))` yields `Path(".")` and the
`if not str(fixture_path)` guard (`not "."`) was always False. The shared
`_acquire_snapshot` helper handled the same case correctly; these tests pin
that `snapshot` now raises the documented clean ProbeError + exit 2 and that
`load_fixture` is robust against a directory argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tooldrift.cli import _resolve_fixture, app
from tooldrift.probe import ProbeError, load_fixture

ROOT = Path(__file__).resolve().parent.parent

runner = CliRunner()


def test_resolve_fixture_raises_for_no_builtin_provider():
    with pytest.raises(ProbeError) as exc:
        _resolve_fixture("kimi", fixture=None)
    assert "no built-in fixture for provider 'kimi'" in str(exc.value)


def test_resolve_fixture_returns_explicit_fixture(tmp_path):
    fp = tmp_path / "resp.json"
    fp.write_text("{}", encoding="utf-8")
    assert _resolve_fixture("kimi", fixture=fp) == fp


def test_resolve_fixture_returns_builtin_for_deepseek():
    assert _resolve_fixture("deepseek", fixture=None) == Path(
        "tests/fixtures/deepseek_tool_calls.json"
    )


def test_snapshot_no_builtin_provider_exits_2(tmp_path):
    """kimi/glm/minimax have no built-in fixture → clean exit 2, not a crash."""
    result = runner.invoke(
        app,
        ["snapshot", "--provider", "kimi", "--from-fixtures", "-o", str(tmp_path / "out.json")],
    )
    assert result.exit_code == 2, result.output
    assert "no built-in fixture for provider 'kimi'" in result.output


def test_snapshot_builtin_provider_still_works(tmp_path):
    """deepseek has a built-in fixture → exit 0, snapshot written."""
    out = tmp_path / "deepseek.json"
    result = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--from-fixtures", "-q", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_load_fixture_raises_probeerror_for_directory(tmp_path):
    """A directory must raise ProbeError (clean), not IsADirectoryError (crash)."""
    with pytest.raises(ProbeError) as exc:
        load_fixture(tmp_path)  # a directory
    assert "fixture not found" in str(exc.value)


def test_load_fixture_raises_probeerror_for_missing_file(tmp_path):
    with pytest.raises(ProbeError):
        load_fixture(tmp_path / "does-not-exist.json")
