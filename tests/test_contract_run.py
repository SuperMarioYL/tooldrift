"""m5 tests: contract-file mode for `tooldrift run` (the documented happy path).

The shipped `examples/contract.yaml` documents
`tooldrift run --contract examples/contract.yaml --base deepseek --base qwen`,
which previously failed with `No such option: --contract`. These tests assert the
contract-file loader works, the pinned `expected:` block builds a comparable
snapshot, and the CLI command now exits with the right drift verdict — all
offline via the shipped fixtures (deepseek matches `expected`, qwen diverges).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tooldrift.cli import app
from tooldrift.contract import ArgumentsEncoding, ToolCallIdFormat
from tooldrift.contract_file import ContractFile, ContractFileError

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "examples" / "contract.yaml"

runner = CliRunner()


# --------------------------------------------------------------------------- #
# ContractFile loader + expected-snapshot builder                              #
# --------------------------------------------------------------------------- #


def test_contract_file_loads():
    cf = ContractFile.load(CONTRACT)
    assert cf.suite_path == "examples/suite.weather.yaml"
    # All five declared providers carry overrides.
    assert set(cf.providers) == {"deepseek", "qwen", "kimi", "glm", "minimax"}
    assert cf.providers["deepseek"].model_id == "deepseek-chat"
    assert cf.providers["deepseek"].api_key_env == "DEEPSEEK_API_KEY"
    # The pinned expected block is present.
    assert cf.expected is not None
    assert "get_weather" in cf.expected
    assert "get_forecast" in cf.expected


def test_expected_snapshot_matches_openai_canonical():
    cf = ContractFile.load(CONTRACT)
    snap = cf.expected_snapshot(suite_name="weather")
    assert snap is not None
    weather = snap.tools["get_weather"]
    assert weather.emitted is True
    assert weather.arguments_encoding is ArgumentsEncoding.JSON_STRING
    assert weather.tool_call_id_format is ToolCallIdFormat.OPENAI
    assert weather.finish_reason == "tool_calls"
    forecast = snap.tools["get_forecast"]
    assert forecast.arg_nesting["days"] == "integer"
    assert forecast.arg_nesting["include"] == "object"


def test_contract_file_rejects_missing_suite(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("providers: {}\n", encoding="utf-8")
    with pytest.raises(ContractFileError):
        ContractFile.load(bad)


def test_resolve_provider_layers_overrides():
    cf = ContractFile.load(CONTRACT)
    # A custom override should win over the built-in default model.
    resolved = cf.resolve_provider("deepseek")
    assert resolved.default_model == "deepseek-chat"
    assert resolved.base_url == "https://api.deepseek.com/v1"


# --------------------------------------------------------------------------- #
# CLI: `tooldrift run --contract ... --base ... --from-fixtures`                #
# --------------------------------------------------------------------------- #


def test_run_contract_flags_drift_exit_1():
    """deepseek vs qwen + each vs expected → qwen drifts → exit 1."""
    result = runner.invoke(
        app,
        [
            "run",
            "--contract", str(CONTRACT),
            "--base", "deepseek",
            "--base", "qwen",
            "--from-fixtures",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "FAIL" in result.output


def test_run_contract_deepseek_alone_matches_expected_exit_0():
    """deepseek matches the pinned `expected` block exactly → exit 0."""
    result = runner.invoke(
        app,
        [
            "run",
            "--contract", str(CONTRACT),
            "--base", "deepseek",
            "--from-fixtures",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


def test_run_contract_json_emits_diffs_object():
    result = runner.invoke(
        app,
        [
            "run",
            "--contract", str(CONTRACT),
            "--base", "deepseek",
            "--base", "qwen",
            "--from-fixtures",
            "--format", "json",
        ],
    )
    assert result.exit_code == 1, result.output
    import json

    payload = json.loads(result.output)
    assert "diffs" in payload
    assert payload["equivalent"] is False
    # 3 diffs: 1 pairwise + 2 vs-expected (deepseek, qwen).
    assert len(payload["diffs"]) == 3


def test_run_contract_rejects_old_with_contract():
    result = runner.invoke(
        app,
        [
            "run",
            "--contract", str(CONTRACT),
            "--old", "deepseek",
            "--from-fixtures",
        ],
    )
    # typer surfaces the exit-2 arg error; assert it did NOT run successfully.
    assert result.exit_code != 0
    assert "contract" in result.output.lower()


def test_run_pairwise_mode_still_works():
    """The legacy --old/--new pairwise mode is unchanged."""
    result = runner.invoke(
        app,
        ["run", "--old", "deepseek", "--new", "qwen", "--from-fixtures"],
    )
    assert result.exit_code == 1, result.output
