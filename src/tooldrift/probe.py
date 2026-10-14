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
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            # Malformed suite YAML must surface as the clean "could not load
            # suite" error + exit 2, not a raw yaml traceback — mirroring
            # ContractFile.load's handling of the same error class.
            raise ProbeError(f"suite {p} is not valid yaml: {exc}") from exc
        if not isinstance(raw, dict):
            raise ProbeError(f"suite {p} did not parse to a mapping")
        # Structural validation: Suite.__init__ would silently coerce a
        # non-list `messages` (list("hello") -> chars) and a non-mapping
        # `tools` entry would only crash later in tool_names, far from the
        # load site. Name the problem here, once, for every consumer.
        for field in ("messages", "tools"):
            value = raw.get(field)
            if value is None:
                continue
            if not isinstance(value, list) or any(
                not isinstance(entry, dict) for entry in value
            ):
                raise ProbeError(
                    f"suite {p}: '{field}' must be a list of mappings, "
                    f"got {type(value).__name__}"
                )
        return cls(raw, source=str(p))


# --------------------------------------------------------------------------- #
# Response parsing (shared by live + fixture paths)                           #
# --------------------------------------------------------------------------- #


def _extract_tool_calls(response_json: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Pull ``tool_calls`` + ``finish_reason`` out of a /chat/completions body.

    Tolerant of the small shape variations seen across providers: tool_calls may
    sit on the message, and finish_reason on the choice. A body whose nested
    fields are the WRONG types entirely (choices not a list, choice/message not
    a mapping) is not a small variation — it raises a clean ProbeError naming
    the offending field instead of an AttributeError escape.
    """
    choices = response_json.get("choices") or []
    if not isinstance(choices, list):
        raise ProbeError(
            f"response body has an unexpected shape: 'choices' is "
            f"{type(choices).__name__}, expected a list"
        )
    if not choices:
        return [], response_json.get("finish_reason", "") or ""
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProbeError(
            f"response body has an unexpected shape: choices[0] is "
            f"{type(choice).__name__}, expected a mapping"
        )
    message = choice.get("message")
    if message is not None and not isinstance(message, dict):
        raise ProbeError(
            f"response body has an unexpected shape: 'message' is "
            f"{type(message).__name__}, expected a mapping"
        )
    message = message or {}
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
    if not isinstance(response_json, dict):
        # Valid JSON but not an object (an array, scalar, string — all legal
        # JSON). Both the fixture-replay and the live path funnel here, and a
        # provider/gateway can return HTTP 200 with such a body, so this is a
        # named ProbeError, never an AttributeError escape.
        raise ProbeError(
            f"response body is not a JSON object: {str(response_json)[:120]}"
        )
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
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        # json.JSONDecodeError: a fixture that is not valid JSON gets the same
        # clean ProbeError treatment the live path gives a non-JSON 200 body.
        raise ProbeError(f"fixture {p} is not valid JSON: {exc}") from exc


def probe_from_fixture(
    fixture_path: str | Path,
    *,
    provider: str,
    model_id: str,
    suite: Suite,
    override_model: str | None = None,
) -> ContractSnapshot:
    """Build a snapshot from a saved response instead of a live call.

    ``override_model`` carries the RAW model override the user passed on the
    CLI (``--model`` / ``--old-model`` / ``--new-model``), distinct from the
    resolved default in ``model_id``. When it disagrees with the model recorded
    in the fixture body, the replay is refused: the snapshot's contract binds
    to a model version, and relabeling saved data with a version that never
    produced it would silently poison every diff it feeds (the behavior the
    README documents as "fixture mode refuses incompatible model overrides").
    When no override was passed, the snapshot is labeled with the body's
    recorded model (falling back to ``model_id`` for bodies without one), so
    saved data is never relabeled.
    """
    body = load_fixture(fixture_path)
    recorded = body.get("model") if isinstance(body, dict) else None
    if override_model and recorded and override_model != recorded:
        raise ProbeError(
            f"fixture {fixture_path} recorded model '{recorded}' but --model "
            f"'{override_model}' was requested — fixture mode refuses "
            f"incompatible model overrides rather than relabeling saved data."
        )
    return snapshot_from_response(
        body,
        provider=provider,
        model_id=override_model or recorded or model_id,
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
    except ValueError as exc:
        # resp.json() raises json.JSONDecodeError (a ValueError) when a provider
        # or a reverse-proxy/WAF returns HTTP 200 with a non-JSON body (an HTML
        # error page, a truncated payload, a 200-wrapped gateway error). It is
        # not an httpx exception, so without this branch it would crash the CLI
        # with a raw traceback instead of the clean ProbeError + exit 2 every
        # other network failure produces. `resp` is bound here: to reach
        # resp.json(), the post + raise_for_status above must have succeeded.
        raise ProbeError(
            f"{provider.key} returned a non-JSON response (HTTP {resp.status_code}): "
            f"{resp.text[:200]}"
        ) from exc
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
