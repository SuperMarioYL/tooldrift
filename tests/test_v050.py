"""v0.5.0 regressions (m12–m17).

m12 — a response body that is valid JSON but the wrong SHAPE (array, scalar,
`choices`/`message` not the expected types) must exit as a clean named error
on both the fixture-replay and live paths, never a raw AttributeError whose
exit 1 reads as contract drift in CI.
m13 — a contract.yaml `expected:` block with wrong-typed fields must exit
cleanly, not with a raw pydantic ValidationError traceback (exit 1).
m14 — fixture mode must honor its documented refusal of incompatible model
overrides (README.en.md:98 / web/site.json) instead of relabeling saved data.
m15 — structurally-malformed suite files (tools entries as strings, messages
as a string) must exit with a named error instead of crashing raw or silently
mangling.
m16 — an unwritable `--output` target must exit cleanly, not with a raw
OSError traceback (exit 1).
m17 is exercised end-to-end by the release pipeline (no unit test possible).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from tooldrift.cli import app
from tooldrift.probe import ProbeError, Suite, probe_live
from tooldrift.providers import Provider

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "examples" / "suite.weather.yaml"
DEEPSEEK_FIXTURE = ROOT / "tests" / "fixtures" / "deepseek_tool_calls.json"

runner = CliRunner()


def _assert_clean_error(res, *needles: str) -> None:
    """The CLI error contract: one-line message on stderr, exit 2, no crash.

    Needles are matched against whitespace-normalized stderr because the rich
    console word-wraps long paths, which can split a phrase across lines.
    """
    assert res.exit_code == 2, res.output
    flat_stderr = " ".join(res.stderr.split())
    for needle in needles:
        assert needle in flat_stderr, res.stderr
    assert "Traceback" not in flat_stderr


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# m12: wrong-shape response bodies                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body,needle",
    [
        ("[]", "not a JSON object"),
        ('"just a string"', "not a JSON object"),
        ('{"choices": "x"}', "'choices' is str"),
        ('{"choices": ["x"]}', "choices[0] is str"),
        ('{"choices": [{"message": "x"}]}', "'message' is str"),
    ],
)
def test_malformed_fixture_body_exits_clean(tmp_path, body, needle):
    fixture = _write(tmp_path / "broken.json", body)
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--fixture",
            str(fixture),
            "-q",
            "-o",
            str(tmp_path / "out.json"),
        ],
    )
    _assert_clean_error(res, "error:", needle)


def test_malformed_tool_call_elements_are_skipped(tmp_path):
    """Non-mapping tool_calls entries are skipped like unnamed ones, not a crash."""
    fixture = _write(
        tmp_path / "calls.json",
        '{"choices": [{"message": {"role": "assistant", "tool_calls": ["x"]}}]}',
    )
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--fixture",
            str(fixture),
            "-q",
            "-o",
            str(tmp_path / "out.json"),
        ],
    )
    assert res.exit_code == 0, res.output
    snap = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert snap["tools"]["get_weather"]["emitted"] is False


def test_probe_live_json_array_200_raises_probeerror():
    """A 200 + valid-JSON-array body (legal JSON, not an object) is a named error."""
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"[1,2,3]"))
    )
    with pytest.raises(ProbeError) as exc:
        probe_live(
            Provider(
                key="deepseek",
                base_url="https://api.deepseek.com/v1",
                default_model="deepseek-chat",
                api_key_env="DEEPSEEK_API_KEY",
            ),
            Suite.load(SUITE),
            api_key="k",
            client=client,
        )
    assert "not a JSON object" in str(exc.value)


def test_probe_live_wrong_shape_choices_raises_probeerror():
    """A 200 object whose `choices` is not a list is a named error, not a crash."""
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=b'{"choices": "nope"}')
        )
    )
    with pytest.raises(ProbeError) as exc:
        probe_live(
            Provider(
                key="deepseek",
                base_url="https://api.deepseek.com/v1",
                default_model="deepseek-chat",
                api_key_env="DEEPSEEK_API_KEY",
            ),
            Suite.load(SUITE),
            api_key="k",
            client=client,
        )
    assert "'choices' is str" in str(exc.value)


# --------------------------------------------------------------------------- #
# m13: wrong-typed expected blocks                                             #
# --------------------------------------------------------------------------- #


def _contract(tmp_path: Path, expected_yaml: str) -> Path:
    return _write(
        tmp_path / "contract.yaml",
        f"suite: {SUITE}\n"
        "providers:\n"
        "  deepseek: {}\n"
        "expected:\n"
        f"{expected_yaml}\n",
    )


def test_contract_expected_wrong_types_exits_clean(tmp_path):
    contract = _contract(tmp_path, "  get_weather:\n    parallel_arity: many\n")
    res = runner.invoke(
        app,
        ["run", "--contract", str(contract), "--base", "deepseek", "--from-fixtures"],
    )
    _assert_clean_error(res, "error:", "expected tool 'get_weather'")


def test_contract_expected_valid_block_still_passes(tmp_path):
    """A well-typed expected block matching the deepseek fixture exits 0."""
    contract = _contract(
        tmp_path,
        "  get_weather:\n"
        "    emitted: true\n"
        "    arg_keys: [location, unit]\n"
        "    arg_nesting: {location: string, unit: string}\n"
        "    arguments_encoding: json_string\n"
        "    parallel_arity: 1\n"
        "    tool_call_id_format: openai\n"
        "    finish_reason: tool_calls\n"
        "  get_forecast:\n"
        "    emitted: true\n"
        "    arg_keys: [days, include, location, unit]\n"
        "    arg_nesting: {days: integer, include: object, location: string, unit: string}\n"
        "    arguments_encoding: json_string\n"
        "    parallel_arity: 1\n"
        "    tool_call_id_format: openai\n"
        "    finish_reason: tool_calls\n",
    )
    res = runner.invoke(
        app,
        ["run", "--contract", str(contract), "--base", "deepseek", "--from-fixtures"],
    )
    assert res.exit_code == 0, res.output


# --------------------------------------------------------------------------- #
# m14: fixture model-override refusal                                          #
# --------------------------------------------------------------------------- #


def test_fixture_refuses_incompatible_model_override(tmp_path):
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--model",
            "totally-wrong-model",
            "-q",
            "-o",
            str(tmp_path / "out.json"),
        ],
    )
    _assert_clean_error(res, "error:", "recorded model 'deepseek-chat'")
    assert "refuses" in res.stderr


def test_run_refuses_incompatible_old_model_override(tmp_path):
    res = runner.invoke(
        app,
        [
            "run",
            "--old",
            "deepseek",
            "--new",
            "qwen",
            "--from-fixtures",
            "--old-model",
            "not-deepseek-chat",
        ],
    )
    _assert_clean_error(res, "error:", "recorded model 'deepseek-chat'")


def test_fixture_accepts_compatible_model_override(tmp_path):
    out = tmp_path / "out.json"
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--model",
            "deepseek-chat",
            "-q",
            "-o",
            str(out),
        ],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(out.read_text(encoding="utf-8"))["model_id"] == "deepseek-chat"


def test_fixture_labels_snapshot_from_recorded_model(tmp_path):
    """A custom fixture whose body records a model is labeled with it, not the default."""
    body = json.loads(DEEPSEEK_FIXTURE.read_text(encoding="utf-8"))
    body["model"] = "my-model-v2"
    fixture = _write(tmp_path / "custom.json", json.dumps(body))
    out = tmp_path / "out.json"
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--fixture",
            str(fixture),
            "-q",
            "-o",
            str(out),
        ],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(out.read_text(encoding="utf-8"))["model_id"] == "my-model-v2"


def test_fixture_without_recorded_model_falls_back(tmp_path):
    """A body without a `model` field keeps the caller-supplied label (and allows overrides)."""
    body = json.loads(DEEPSEEK_FIXTURE.read_text(encoding="utf-8"))
    body.pop("model")
    fixture = _write(tmp_path / "norecord.json", json.dumps(body))
    out = tmp_path / "out.json"
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--fixture",
            str(fixture),
            "--model",
            "declared-elsewhere",
            "-q",
            "-o",
            str(out),
        ],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(out.read_text(encoding="utf-8"))["model_id"] == "declared-elsewhere"


# --------------------------------------------------------------------------- #
# m15: structurally-malformed suite files                                      #
# --------------------------------------------------------------------------- #


def test_suite_tools_as_strings_exits_clean(tmp_path):
    suite = _write(
        tmp_path / "suite.yaml",
        "name: t\nmessages:\n  - role: user\n    content: hi\ntools:\n  - get_weather\n",
    )
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--suite",
            str(suite),
            "-q",
        ],
    )
    _assert_clean_error(res, "error:", "could not load suite", "'tools' must be a list of mappings")


def test_suite_messages_as_string_exits_clean(tmp_path):
    suite = _write(tmp_path / "suite.yaml", "name: t\nmessages: hello\ntools: []\n")
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "--suite",
            str(suite),
            "-q",
        ],
    )
    _assert_clean_error(
        res, "error:", "could not load suite", "'messages' must be a list of mappings"
    )


# --------------------------------------------------------------------------- #
# m16: unwritable --output targets                                             #
# --------------------------------------------------------------------------- #


def test_snapshot_unwritable_output_exits_clean(tmp_path):
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    res = runner.invoke(
        app,
        [
            "snapshot",
            "--provider",
            "deepseek",
            "--from-fixtures",
            "-q",
            "-o",
            str(blocker / "snap.json"),
        ],
    )
    _assert_clean_error(res, "error:", "could not write")


def test_compare_table_unwritable_output_exits_clean(tmp_path):
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    res = runner.invoke(
        app,
        ["compare-table", "--from-fixtures", "-o", str(blocker / "table.md")],
    )
    _assert_clean_error(res, "error:", "could not write")


# --------------------------------------------------------------------------- #
# version lockstep moved to the current version's test module (test_v060.py)    #
# --------------------------------------------------------------------------- #
