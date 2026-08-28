"""m5 regression: probe_live must turn a non-JSON 200-OK response into a clean
ProbeError, not a raw json.JSONDecodeError traceback.

A provider (or the reverse proxy / WAF in front of it) can return HTTP 200
with a non-JSON body — an HTML error page, a truncated payload, a 200-wrapped
gateway error. Before the fix, `resp.json()` in probe_live raised
json.JSONDecodeError (a ValueError), which slipped past the httpx-only except
clauses and crashed the CLI. These tests pin the clean behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tooldrift.probe import ProbeError, Suite, probe_live
from tooldrift.providers import Provider

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "examples" / "suite.weather.yaml"


def _suite() -> Suite:
    return Suite.load(SUITE)


def _provider() -> Provider:
    return Provider(
        key="deepseek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
    )


def test_probe_live_nonjson_200_raises_probeerror():
    """A 200-OK HTML body must raise ProbeError, not json.JSONDecodeError."""
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=b"<html>Bad Gateway</html>")
        )
    )
    with pytest.raises(ProbeError) as exc:
        probe_live(_provider(), _suite(), api_key="k", client=client)
    msg = str(exc.value)
    assert "non-JSON" in msg
    assert "deepseek" in msg


def test_probe_live_valid_json_still_snapshots():
    """A well-formed 200 chat.completions body still produces a snapshot."""
    payload = (ROOT / "tests" / "fixtures" / "deepseek_tool_calls.json").read_bytes()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=payload, headers={"content-type": "application/json"})
        )
    )
    snap = probe_live(_provider(), _suite(), api_key="k", client=client)
    assert snap.provider == "deepseek"
    assert snap.tools["get_weather"].emitted is True
