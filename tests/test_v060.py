"""v0.6.0 regressions.

Four shipped-behavior defects, each reproduced against v0.5.0 before the fix:

* m18 — fixture mode skipped *any* failing provider (the skip exists only for a
  provider with no bundled fixture). ``compare-table -p deepseek -p notaprovider
  --from-fixtures`` exited 0 with a partial table.
* m19 — a wrong-typed provider override in contract.yaml (``base_url: 123``)
  reached ``probe_live`` and raised ``AttributeError``, exiting 1 — the
  documented DRIFT code — for a config-file error.
* m20 — unknown keys in provider blocks and pinned ``expected`` blocks were
  silently dropped, so a typo retargeted a provider to registry defaults or
  silently un-pinned an assertion (a false PASS).
* m21 — two snapshots with zero tools compared equal: PASS + exit 0 with no
  assertion having run.

Plus m22: the READMEs' documented per-provider ``request_quirks`` block is now
actually honored by contract.yaml.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import tooldrift
from tooldrift.cli import app
from tooldrift.contract_file import ContractFile, ContractFileError
from tooldrift.probe import Suite, build_request_body

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "examples" / "suite.weather.yaml"
CONTRACT = ROOT / "examples" / "contract.yaml"

runner = CliRunner()


def _contract(tmp_path: Path, providers: str, extra: str = "", name: str = "contract.yaml") -> Path:
    """Write a minimal contract.yaml pointing at the real bundled suite."""
    path = tmp_path / name
    path.write_text(
        f"version: 1\nsuite: {SUITE}\nproviders:\n{providers}{extra}",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
# m18: fixture-mode skip only covers providers without a bundled fixture        #
# --------------------------------------------------------------------------- #


def test_fixture_mode_unknown_provider_in_compare_table_is_an_error():
    res = runner.invoke(
        app, ["compare-table", "-p", "deepseek", "-p", "notaprovider", "--from-fixtures"]
    )
    assert res.exit_code == 2, res.output
    assert "error:" in res.stderr
    assert "unknown provider" in res.stderr
    assert "Traceback" not in res.stderr


def test_fixture_mode_still_skips_provider_without_a_bundled_fixture():
    res = runner.invoke(app, ["compare-table", "-p", "deepseek", "-p", "kimi", "--from-fixtures"])
    assert res.exit_code == 0, res.output
    assert "skip kimi" in res.output
    assert "get_weather" in res.output


def test_fixture_mode_contract_run_reports_an_unknown_base_provider(tmp_path):
    contract = _contract(tmp_path, "  deepseek: {}\n  qwen:\n    model_id: qwen-plus\n")
    res = runner.invoke(
        app,
        [
            "run",
            "--contract",
            str(contract),
            "--base",
            "deepseek",
            "--base",
            "qwen",
            "--base",
            "notaprovider",
            "--from-fixtures",
        ],
    )
    assert res.exit_code == 2, res.output
    assert "unknown provider" in res.stderr
    assert "Traceback" not in res.stderr


# --------------------------------------------------------------------------- #
# m19: wrong-typed contract provider overrides                                  #
# --------------------------------------------------------------------------- #


def test_contract_wrong_typed_base_url_is_a_clean_error(tmp_path):
    contract = _contract(tmp_path, "  deepseek:\n    base_url: 123\n  qwen: {}\n")
    res = runner.invoke(
        app,
        ["run", "--contract", str(contract), "--base", "deepseek", "--base", "qwen", "--from-fixtures"],
    )
    assert res.exit_code == 2, res.output
    assert "must be a string" in res.stderr
    assert "Traceback" not in res.stderr


def test_contract_wrong_typed_model_id_is_rejected_at_load(tmp_path):
    contract = _contract(tmp_path, "  deepseek:\n    model_id: [deepseek-chat]\n")
    with pytest.raises(ContractFileError, match="must be a string"):
        ContractFile.load(contract)


# --------------------------------------------------------------------------- #
# m20: unknown contract keys are rejected, not dropped                         #
# --------------------------------------------------------------------------- #


def test_contract_unknown_provider_field_is_rejected(tmp_path):
    contract = _contract(tmp_path, "  deepseek:\n    base_urls: https://example.invalid/v1\n")
    with pytest.raises(ContractFileError, match="base_urls"):
        ContractFile.load(contract)


def test_contract_unknown_expected_field_is_rejected(tmp_path):
    contract = _contract(
        tmp_path,
        "  deepseek: {}\n",
        extra="expected:\n  get_weather:\n    arg_key: [location]\n",
    )
    with pytest.raises(ContractFileError, match="arg_key"):
        ContractFile.load(contract)


def test_contract_unknown_key_error_reaches_the_cli(tmp_path):
    contract = _contract(tmp_path, "  deepseek:\n    model: deepseek-chat\n  qwen: {}\n")
    res = runner.invoke(
        app,
        ["run", "--contract", str(contract), "--base", "deepseek", "--base", "qwen", "--from-fixtures"],
    )
    assert res.exit_code == 2, res.output
    assert "model" in res.stderr
    assert "Traceback" not in res.stderr


def test_example_contract_still_loads_and_pins_expected():
    loaded = ContractFile.load(CONTRACT)
    assert loaded.expected_snapshot(suite_name="weather") is not None


# --------------------------------------------------------------------------- #
# m21: a comparison with zero tools is not green                               #
# --------------------------------------------------------------------------- #


def _empty_snapshot(path: Path, provider: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": provider,
                "model_id": "m",
                "suite": "weather",
                "tools": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_diff_of_two_empty_snapshots_fails_loudly(tmp_path):
    old = _empty_snapshot(tmp_path / "a.json", "a")
    new = _empty_snapshot(tmp_path / "b.json", "b")
    res = runner.invoke(app, ["diff", str(old), str(new)])
    assert res.exit_code == 2, res.output
    assert "nothing to compare" in res.stderr


# --------------------------------------------------------------------------- #
# m22: per-provider request quirks from contract.yaml                          #
# --------------------------------------------------------------------------- #


def test_contract_provider_request_quirks_reach_the_request_body(tmp_path):
    contract = _contract(
        tmp_path, "  deepseek:\n    request_quirks:\n      tool_choice: required\n"
    )
    provider = ContractFile.load(contract).resolve_provider("deepseek")
    assert provider.request_quirks == {"tool_choice": "required"}

    suite = Suite.load(SUITE)
    body = build_request_body(provider, suite)
    assert body["tool_choice"] == "required"


def test_contract_non_mapping_request_quirks_is_rejected(tmp_path):
    contract = _contract(tmp_path, "  deepseek:\n    request_quirks: [tool_choice]\n")
    with pytest.raises(ContractFileError, match="request_quirks"):
        ContractFile.load(contract)


# --------------------------------------------------------------------------- #
# version lockstep (single source of truth across surfaces)                     #
# --------------------------------------------------------------------------- #


def test_version_lockstep_v060():
    """Every version surface asserts 0.6.0 so a partial bump fails CI."""
    assert tooldrift.__version__ == "0.6.0"
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.0"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.6.0"' in pyproject
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.6.0]" in changelog
    site = json.loads((ROOT / "web" / "site.json").read_text(encoding="utf-8"))
    assert site["content_version"] == "v0.6.0"
