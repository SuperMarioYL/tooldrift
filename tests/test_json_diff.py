"""m7 tests: `--format json` machine-readable ContractDiff output.

`run` and `diff` gained a `--format {rich,json}` option. In json mode the
ContractDiff is emitted as JSON to stdout and the rich panel is suppressed, so
CI (and the documented hosted-drift-watch SaaS seam) can parse drift
programmatically. The exit code still reflects drift (0 equivalent / 1 drift).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tooldrift.cli import app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SUITE = ROOT / "examples" / "suite.weather.yaml"

runner = CliRunner()


def _snapshot_json(provider: str, model_id: str, tmp_path: Path) -> Path:
    """Write a fixture-derived snapshot to a temp file and return its path."""
    from tooldrift.probe import Suite, probe_from_fixture

    suite = Suite.load(SUITE)
    snap = probe_from_fixture(
        FIXTURES / f"{provider}_tool_calls.json",
        provider=provider,
        model_id=model_id,
        suite=suite,
    )
    out = tmp_path / f"{provider}.json"
    out.write_text(snap.to_json(), encoding="utf-8")
    return out


def test_diff_format_json_drift_is_valid_contractdiff(tmp_path):
    ds = _snapshot_json("deepseek", "deepseek-chat", tmp_path)
    qw = _snapshot_json("qwen", "qwen-plus", tmp_path)
    result = runner.invoke(app, ["diff", str(ds), str(qw), "--format", "json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["old_label"] == "deepseek/deepseek-chat"
    assert payload["new_label"] == "qwen/qwen-plus"
    # The drifted tools surface in the JSON.
    tool_names = {t["tool"] for t in payload["tools"]}
    assert "get_weather" in tool_names
    assert "get_forecast" in tool_names


def test_diff_format_json_identical_exits_0(tmp_path):
    a = _snapshot_json("deepseek", "deepseek-chat", tmp_path)
    b = _snapshot_json("deepseek", "deepseek-chat", tmp_path)  # same fixture twice
    result = runner.invoke(app, ["diff", str(a), str(b), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(not t["fields"] and t["only_in"] is None for t in payload["tools"])


def test_diff_default_format_is_rich_not_json(tmp_path):
    """Without --format, the rich panel renders (no JSON on stdout)."""
    ds = _snapshot_json("deepseek", "deepseek-chat", tmp_path)
    qw = _snapshot_json("qwen", "qwen-plus", tmp_path)
    result = runner.invoke(app, ["diff", str(ds), str(qw)])
    assert result.exit_code == 1, result.output
    # The rich report has a FAIL panel; pure JSON would not contain 'PASS'/'FAIL' prose.
    assert "FAIL" in result.output
    # And it must NOT be valid JSON (it's a rich panel).
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


def test_run_format_json_pairwise(tmp_path):
    result = runner.invoke(
        app,
        ["run", "--old", "deepseek", "--new", "qwen", "--from-fixtures", "--format", "json"],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["old_label"] == "deepseek/deepseek-chat"
    assert payload["new_label"] == "qwen/qwen-plus"
