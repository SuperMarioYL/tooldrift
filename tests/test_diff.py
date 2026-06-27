"""m2 tests: contract diff + red/green exit code.

Load the two shipped fixtures (DeepSeek = arguments-as-JSON-string, Qwen =
arguments-as-object with a retyped + dropped key and a different finish_reason),
normalize each into a :class:`ContractSnapshot`, and assert that:

* :func:`tooldrift.diff.diff` flags the non-equivalence on the real fields,
* :func:`tooldrift.report.run_diff` would exit NONZERO on that drift, and
* two identical snapshots are equivalent and exit ZERO.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from tooldrift.contract import ArgumentsEncoding, ToolCallIdFormat
from tooldrift.diff import DeltaSeverity, diff
from tooldrift.probe import Suite, probe_from_fixture
from tooldrift.report import EXIT_DRIFT, EXIT_EQUIVALENT, run_diff

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SUITE = ROOT / "examples" / "suite.weather.yaml"

# A console that renders to a throwaway buffer so tests don't spew to stdout but
# still exercise the real rendering path.
_QUIET = Console(file=open("/dev/null", "w"), force_terminal=False)


def _load_suite() -> Suite:
    return Suite.load(SUITE)


def _deepseek_snapshot():
    return probe_from_fixture(
        FIXTURES / "deepseek_tool_calls.json",
        provider="deepseek",
        model_id="deepseek-chat",
        suite=_load_suite(),
    )


def _qwen_snapshot():
    return probe_from_fixture(
        FIXTURES / "qwen_tool_calls.json",
        provider="qwen",
        model_id="qwen-plus",
        suite=_load_suite(),
    )


# --------------------------------------------------------------------------- #
# The snapshots themselves carry the contract surface we expect.              #
# --------------------------------------------------------------------------- #


def test_deepseek_snapshot_is_openai_canonical():
    snap = _deepseek_snapshot()
    weather = snap.tools["get_weather"]
    assert weather.emitted is True
    assert weather.arguments_encoding is ArgumentsEncoding.JSON_STRING
    assert weather.arg_keys == ["location", "unit"]
    assert weather.tool_call_id_format is ToolCallIdFormat.OPENAI
    assert weather.finish_reason == "tool_calls"
    # get_forecast.days decoded from the JSON string is a real integer.
    assert snap.tools["get_forecast"].arg_nesting["days"] == "integer"


def test_qwen_snapshot_diverges():
    snap = _qwen_snapshot()
    weather = snap.tools["get_weather"]
    # Qwen inlines arguments as an object — the headline drift.
    assert weather.arguments_encoding is ArgumentsEncoding.OBJECT
    assert weather.tool_call_id_format is ToolCallIdFormat.CUSTOM
    assert weather.finish_reason == "stop"
    # get_forecast dropped unit + include and typed days as a string.
    forecast = snap.tools["get_forecast"]
    assert forecast.arg_keys == ["days", "location"]
    assert forecast.arg_nesting["days"] == "string"


# --------------------------------------------------------------------------- #
# The diff flags the non-equivalence on the right fields.                     #
# --------------------------------------------------------------------------- #


def test_diff_flags_non_equivalence():
    result = diff(_deepseek_snapshot(), _qwen_snapshot())

    assert result.is_equivalent is False
    assert result.has_breaking is True

    drifted = {t.tool for t in result.drifted_tools}
    assert "get_weather" in drifted
    assert "get_forecast" in drifted

    # get_weather: the arguments_encoding flip is present and BREAKING.
    weather = next(t for t in result.tools if t.tool == "get_weather")
    fields = {fd.field: fd for fd in weather.fields}
    assert "arguments_encoding" in fields
    assert fields["arguments_encoding"].old == "json_string"
    assert fields["arguments_encoding"].new == "object"
    assert fields["arguments_encoding"].severity is DeltaSeverity.BREAKING
    assert "tool_call_id_format" in fields
    assert "finish_reason" in fields

    # get_forecast: dropped keys + retyped 'days' surface as concrete deltas.
    forecast = next(t for t in result.tools if t.tool == "get_forecast")
    forecast_fields = {fd.field: fd for fd in forecast.fields}
    assert "arg_keys" in forecast_fields
    assert "arg_nesting:days" in forecast_fields
    assert forecast_fields["arg_nesting:days"].old == "integer"
    assert forecast_fields["arg_nesting:days"].new == "string"


def test_run_diff_exits_nonzero_on_drift():
    result = diff(_deepseek_snapshot(), _qwen_snapshot())
    code = run_diff(result, console=_QUIET)
    assert code == EXIT_DRIFT
    assert code != 0


# --------------------------------------------------------------------------- #
# Positive case: identical snapshots are equivalent, exit zero.               #
# --------------------------------------------------------------------------- #


def test_identical_snapshots_are_equivalent():
    snap = _deepseek_snapshot()
    # Diff a snapshot against itself (re-loaded) — must be fully equivalent.
    other = _deepseek_snapshot()
    result = diff(snap, other, old_label="deepseek@v1", new_label="deepseek@v2")

    assert result.is_equivalent is True
    assert result.drifted_tools == []
    assert result.has_breaking is False

    code = run_diff(result, console=_QUIET)
    assert code == EXIT_EQUIVALENT
    assert code == 0


def test_diff_is_pure_and_repeatable():
    # Same inputs -> identical structured result (no hidden state / ordering flake).
    a = diff(_deepseek_snapshot(), _qwen_snapshot())
    b = diff(_deepseek_snapshot(), _qwen_snapshot())
    assert a.model_dump() == b.model_dump()
