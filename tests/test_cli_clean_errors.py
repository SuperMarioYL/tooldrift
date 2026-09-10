"""m8–m11 regressions: every user-input failure honors the CLI's clean-error
contract — a one-line ``error:`` message and exit code 2 — and a contract-file
run with nothing to compare fails loudly instead of silently passing.

Before these fixes (shipped v0.3.0), all four paths escaped as raw tracebacks
(or a silent exit 0):

* m8 — an unknown provider key crashed with a raw ``KeyError`` traceback and
  exit 1 (which is ToolDrift's documented DRIFT code, misreporting a typo'd
  provider as contract drift in CI).
* m9 — a malformed suite YAML crashed with a raw ``yaml.ScannerError``
  traceback (while the sibling contract.yaml loader already handled the same
  error class cleanly).
* m10 — a fixture file that is not valid JSON crashed with a raw
  ``json.JSONDecodeError`` traceback (the offline twin of the m5 non-JSON-200
  fix shipped in v0.3.0).
* m11 — ``run --contract c.yaml --base <one-provider>`` with no ``expected:``
  block printed nothing and exited 0: a silent no-op that reads as a green
  PASS in CI.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from tooldrift.cli import app

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "examples" / "contract.yaml"

runner = CliRunner()


def _assert_clean_error(res, *needles: str) -> None:
    """The CLI error contract: one-line message on stderr, exit 2, no crash."""
    assert res.exit_code == 2, res.output
    for needle in needles:
        assert needle in res.stderr, res.stderr
    assert "Traceback" not in res.stderr
    assert not isinstance(res.exception, KeyError), "raw KeyError escaped the CLI"


# --------------------------------------------------------------------------- #
# m8: unknown provider keys                                                    #
# --------------------------------------------------------------------------- #


def test_snapshot_unknown_provider_exits_2_with_clean_error():
    res = runner.invoke(app, ["snapshot", "--provider", "openai"])
    _assert_clean_error(res, "error:", "unknown provider")


def test_run_pairwise_unknown_provider_exits_2_with_clean_error():
    res = runner.invoke(
        app,
        ["run", "--old", "deepseek", "--new", "notaprovider", "--from-fixtures"],
    )
    _assert_clean_error(res, "error:", "unknown provider")


def test_compare_table_unknown_provider_exits_2_with_clean_error():
    res = runner.invoke(app, ["compare-table", "--provider", "mystery"])
    _assert_clean_error(res, "error:", "unknown provider")


def test_compare_table_unknown_provider_fixture_mode_exits_2():
    """Fixture mode skips fixture-less providers, but must still never crash."""
    res = runner.invoke(app, ["compare-table", "--provider", "mystery", "--from-fixtures"])
    _assert_clean_error(res, "unknown provider")


# --------------------------------------------------------------------------- #
# m9: malformed suite YAML                                                     #
# --------------------------------------------------------------------------- #


def test_malformed_suite_yaml_exits_2_with_clean_error(tmp_path):
    bad = tmp_path / "broken_suite.yaml"
    bad.write_text("messages: [oops\n  - broken: yaml", encoding="utf-8")
    res = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--suite", str(bad), "--from-fixtures"],
    )
    _assert_clean_error(res, "could not load suite", "not valid yaml")


# --------------------------------------------------------------------------- #
# m10: fixture file that is not valid JSON                                     #
# --------------------------------------------------------------------------- #


def test_malformed_fixture_json_exits_2_with_clean_error(tmp_path):
    bad = tmp_path / "broken_fixture.json"
    bad.write_text("not json at all", encoding="utf-8")
    res = runner.invoke(
        app,
        ["snapshot", "--provider", "deepseek", "--from-fixtures", "--fixture", str(bad)],
    )
    _assert_clean_error(res, "error:", "not valid JSON")


# --------------------------------------------------------------------------- #
# m11: contract-file run with nothing to compare                               #
# --------------------------------------------------------------------------- #


def test_contract_single_base_no_expected_fails_loudly(tmp_path):
    """One provider + no pinned expected block => error + exit 2, not exit 0."""
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    spec.pop("expected", None)
    contract = tmp_path / "contract_no_expected.yaml"
    contract.write_text(yaml.safe_dump(spec), encoding="utf-8")

    res = runner.invoke(
        app,
        ["run", "--contract", str(contract), "--base", "deepseek", "--from-fixtures"],
    )
    _assert_clean_error(res, "nothing to compare")


def test_contract_single_base_with_expected_still_passes():
    """Guard against over-broad rejection: one base + a pinned expected block
    still diffs (deepseek matches the example contract's pin) and exits 0."""
    res = runner.invoke(
        app,
        ["run", "--contract", str(CONTRACT), "--base", "deepseek", "--from-fixtures"],
    )
    assert res.exit_code == 0, res.output
    assert "PASS" in res.output
