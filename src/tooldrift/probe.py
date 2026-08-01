"""Probe one provider with a tool suite and build a :class:`ContractSnapshot`.

This is the only module in ToolDrift that touches the network. It:

1. loads a tool suite (system + user prompt + JSON-schema tool definitions),
2. POSTs it to one provider's OpenAI-compatible ``/chat/completions`` with the
   tools attached so the model is forced to emit ``tool_calls``,
3. pulls the raw ``tool_calls`` + ``finish_reason`` out of the response, and
4. hands them to :func:`tooldrift.contract.shape_from_tool_calls` to normalize.

Two things keep it runnable without keys:

* **Offline / fixture mode** — instead of a live call, replay a saved raw
  response JSON from ``tests/fixtures/``. This powers ``--from-fixtures`` so the
  10-minute demo never blocks on four provider API keys.
* The live path reads the API key from the provider's env var and fails with a
  clear message (pointing at fixture mode) when it is missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml

from .contract import ContractSnapshot, shape_from_tool_calls
from .providers import Provider

DEFAULT_TIMEOUT = 60.0


class ProbeError(RuntimeError):
    """Raised when a provider cannot be probed (missing key, HTTP error, etc.)."""


# --------------------------------------------------------------------------- #
# Suite loading                                                               #
# --------------------------------------------------------------------------- #


class Suite:
    """A loaded tool suite: the chat messages + tool defs sent to every provider."""

    def __init__(self, raw: dict[str, Any], *, source: str = "") -> None:
        self.raw = raw
        self.source = source
        self.name: str = raw.get("name") or Path(source).stem or "suite"
        self.messages: list[dict[str, Any]] = list(raw.get("messages") or [])
        self.tools: list[dict[str, Any]] = list(raw.get("tools") or [])
        self.tool_choice: Any = raw.get("tool_choice", "auto")

    @property
    def tool_names(self) -> list[str]:
        """Declared tool/function names, in suite order."""
        names: list[str] = []
        for tool in self.tools:
            fn = (tool or {}).get("function") or {}
            name = fn.get("name")
            if name:
                names.append(name)
        return names

    @classmethod
    def load(cls, path: str | Path) -> Suite:
        p = Path(path)
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ProbeError(f"suite {p} did not parse to a mapping")
        return cls(raw, source=str(p))


# --------------------------------------------------------------------------- #
# Response parsing (shared by live + fixture paths)                           #
# --------------------------------------------------------------------------- #


def _extract_tool_calls(response_json: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Pull ``tool_calls`` + ``finish_reason`` out of a /chat/completions body.

    Tolerant of the small shape variations seen across providers: tool_calls may
    sit on the message, and finish_reason on the choice.
    """
    choices = response_json.get("choices") or []
    if not choices:
        return [], response_json.get("finish_reason", "") or ""
    choice = choices[0] or {}
    message = choice.get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        tool_calls = []
    finish_reason = choice.get("finish_reason") or response_json.get("finish_reason") or ""
    return tool_calls, finish_reason


def snapshot_from_response(
    response_json: dict[str, Any],
    *,
    provider: str,
    model_id: str,
    suite_name: str,
    known_tools: list[str] | None = None,
) -> ContractSnapshot:
    """Build a normalized snapshot from a raw /chat/completions response body."""
    tool_calls, finish_reason = _extract_tool_calls(response_json)
    shapes = shape_from_tool_calls(tool_calls, finish_reason, known_tools=known_tools)
    return ContractSnapshot(
        provider=provider,
        model_id=model_id,
        suite=suite_name,
        tools=shapes,
    ).with_normalized_tools()


# --------------------------------------------------------------------------- #
# Offline / fixture mode                                                      #
# --------------------------------------------------------------------------- #


def load_fixture(path: str | Path) -> dict[str, Any]:
    """Load a saved raw /chat/completions response JSON for offline replay."""
    p = Path(path)
    if not p.is_file():
        # is_file (not exists) so a directory or a missing file both raise a clean
        # ProbeError instead of crashing with IsADirectoryError / FileNotFoundError.
        raise ProbeError(f"fixture not found (expected a JSON file): {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def probe_from_fixture(
    fixture_path: str | Path,
    *,
    provider: str,
    model_id: str,
    suite: Suite,
) -> ContractSnapshot:
    """Build a snapshot from a saved response instead of a live call."""
    body = load_fixture(fixture_path)
    return snapshot_from_response(
        body,
        provider=provider,
        model_id=model_id,
        suite_name=suite.name,
        known_tools=suite.tool_names,
    )


# --------------------------------------------------------------------------- #
# Live probe                                                                   #
# --------------------------------------------------------------------------- #


def build_request_body(provider: Provider, suite: Suite, *, model_id: str | None = None) -> dict[str, Any]:
    """Assemble the OpenAI-compatible request body for a live probe."""
    body: dict[str, Any] = {
        "model": model_id or provider.default_model,
        "messages": suite.messages,
        "tools": suite.tools,
        "tool_choice": suite.tool_choice,
        "stream": False,  # v0.1 probes non-streaming only
    }
    # Per-provider quirks override defaults (e.g. a non-standard tool_choice).
    body.update(provider.request_quirks)
    return body


def probe_live(
    provider: Provider,
    suite: Suite,
    *,
    api_key: str,
    model_id: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.Client | None = None,
) -> ContractSnapshot:
    """Send the suite to a provider's live endpoint and snapshot the result."""
    url = provider.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = build_request_body(provider, suite, model_id=model_id)

    owns_client = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.post(url, headers=headers, json=body)
        resp.raise_for_status()
        response_json = resp.json()
    except httpx.HTTPStatusError as exc:
        raise ProbeError(
            f"{provider.key} returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProbeError(f"{provider.key} request failed: {exc}") from exc
    finally:
        if owns_client:
            http.close()

    return snapshot_from_response(
        response_json,
        provider=provider.key,
        model_id=model_id or provider.default_model,
        suite_name=suite.name,
        known_tools=suite.tool_names,
    )


def get_api_key(provider: Provider, env: dict[str, str]) -> str:
    """Read the provider's API key from the environment mapping.

    Raises :class:`ProbeError` pointing at fixture mode when the key is missing,
    so the user is never stranded without a runnable path.
    """
    key = env.get(provider.api_key_env, "").strip()
    if not key:
        raise ProbeError(
            f"missing API key: set ${provider.api_key_env} for provider '{provider.key}', "
            f"or run with --from-fixtures to replay an offline sample."
        )
    return key
