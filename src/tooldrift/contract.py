"""Normalized tool-call contract models.

The whole point of ToolDrift is to collapse each provider's idiosyncratic
``tool_calls`` payload into a small, comparable, *versioned* shape — the
:class:`ContractSnapshot`. Two snapshots taken against two providers (or two
model versions of one provider) can then be diffed field-by-field to decide
whether the tool-call contract is still *equivalent* across a swap.

Nothing here talks to the network. These are pure data models plus the
normalization helpers that turn a raw OpenAI-compatible ``tool_calls`` list
into a snapshot. Keeping this layer free of I/O is what makes the diff (m2)
a pure, unit-testable function.

Determinism matters: a snapshot is an artifact that gets committed, diffed in
CI, and pasted into READMEs, so :meth:`ContractSnapshot.to_json` always emits
sorted keys and a trailing newline. Re-serializing a snapshot is idempotent.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_SCHEMA_VERSION = 1


class ArgumentsEncoding(str, Enum):
    """How a provider delivers the ``arguments`` of a tool call.

    OpenAI's spec strings the arguments as a JSON-encoded ``str``; some
    providers instead inline a JSON ``object``. This single field is one of
    the most common silent drifts on a model swap, so it is first-class.
    """

    OBJECT = "object"
    JSON_STRING = "json_string"
    ABSENT = "absent"


class ToolCallIdFormat(str, Enum):
    """Shape of the ``id`` a provider stamps on each tool call."""

    OPENAI = "openai"  # e.g. "call_" + 24 alphanumerics
    CUSTOM = "custom"  # present but not the OpenAI shape
    ABSENT = "absent"  # no id field at all


# The JSON-type vocabulary used by ``arg_nesting``. A nested object collapses
# to the literal "object" (we record the *shape kind*, not the full subtree —
# that keeps the contract diff focused on the contract surface, not payload
# values). Arrays collapse to "array".
JSON_TYPES = ("string", "integer", "number", "boolean", "object", "array", "null")


class ToolCallShape(BaseModel):
    """Normalized shape of one tool's ``tool_calls`` output.

    This is the per-tool contract. Equivalence across providers is decided by
    comparing these fields (see :mod:`tooldrift.diff`, m2).
    """

    model_config = ConfigDict(extra="forbid")

    emitted: bool = Field(
        default=False,
        description="Whether the provider actually emitted a call to this tool for the suite prompt.",
    )
    arg_keys: list[str] = Field(
        default_factory=list,
        description="Sorted set of top-level argument keys the provider supplied.",
    )
    arg_nesting: dict[str, str] = Field(
        default_factory=dict,
        description="Per-argument JSON type/shape kind (string|integer|number|boolean|object|array|null).",
    )
    arguments_encoding: ArgumentsEncoding = Field(
        default=ArgumentsEncoding.ABSENT,
        description="Whether arguments arrived as a JSON string or an inline object.",
    )
    parallel_arity: int = Field(
        default=0,
        description="How many parallel calls to THIS tool appeared in the single turn.",
    )
    tool_call_id_format: ToolCallIdFormat = Field(
        default=ToolCallIdFormat.ABSENT,
        description="Shape of the tool_call id the provider stamped.",
    )
    finish_reason: str = Field(
        default="",
        description="The choice-level finish_reason that accompanied the call (e.g. 'tool_calls').",
    )

    def normalized(self) -> ToolCallShape:
        """Return a copy with deterministic ordering (sorted ``arg_keys``)."""
        return self.model_copy(update={"arg_keys": sorted(self.arg_keys)})


class ContractSnapshot(BaseModel):
    """A provider's full tool-call contract for one suite run.

    Serializes deterministically (sorted keys, trailing newline) so the file
    is diff-stable and safe to commit / regress in CI.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=CONTRACT_SCHEMA_VERSION)
    provider: str = Field(description="Provider key, e.g. 'deepseek'.")
    model_id: str = Field(description="Concrete model/version the contract is bound to.")
    suite: str = Field(default="", description="Name of the tool suite that produced this snapshot.")
    tools: dict[str, ToolCallShape] = Field(
        default_factory=dict,
        description="tool_name -> normalized ToolCallShape.",
    )

    # ----------------------------------------------------------------- io ---
    def to_json(self) -> str:
        """Serialize deterministically: sorted keys + trailing newline."""
        payload = self.model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> ContractSnapshot:
        """Inverse of :meth:`to_json`."""
        return cls.model_validate(json.loads(text))

    def with_normalized_tools(self) -> ContractSnapshot:
        """Return a copy whose every tool shape is normalized (sorted keys)."""
        return self.model_copy(
            update={"tools": {name: shape.normalized() for name, shape in self.tools.items()}}
        )


# --------------------------------------------------------------------------- #
# Normalization: raw OpenAI-compatible tool_calls  ->  ToolCallShape per tool  #
# --------------------------------------------------------------------------- #


def _json_type(value: Any) -> str:
    """Classify a decoded JSON value into the contract's type vocabulary."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # bool before int — bool is a subclass of int
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _decode_arguments(raw_arguments: Any) -> tuple[dict[str, Any], ArgumentsEncoding]:
    """Decode a tool call's ``arguments`` and record how it was encoded.

    Handles the two real-world cases ToolDrift exists to catch:

    * ``arguments`` is a JSON-encoded **string** (OpenAI canonical) ->
      :attr:`ArgumentsEncoding.JSON_STRING`.
    * ``arguments`` is already an inline **object** -> :attr:`ArgumentsEncoding.OBJECT`.

    A string that does not parse to an object (or a missing/odd value) yields an
    empty mapping; we still record the *encoding* so the drift is visible.
    """
    if raw_arguments is None:
        return {}, ArgumentsEncoding.ABSENT

    if isinstance(raw_arguments, dict):
        return raw_arguments, ArgumentsEncoding.OBJECT

    if isinstance(raw_arguments, str):
        try:
            decoded = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError:
            decoded = {}
        if not isinstance(decoded, dict):
            decoded = {}
        return decoded, ArgumentsEncoding.JSON_STRING

    # Anything else (list, scalar) — unusual, but record it without crashing.
    return {}, ArgumentsEncoding.OBJECT


def _classify_id(call_id: Any) -> ToolCallIdFormat:
    """Classify the ``id`` a provider stamped on a tool call."""
    if call_id is None or call_id == "":
        return ToolCallIdFormat.ABSENT
    if isinstance(call_id, str) and call_id.startswith("call_") and len(call_id) >= 8:
        return ToolCallIdFormat.OPENAI
    return ToolCallIdFormat.CUSTOM


def shape_from_tool_calls(
    tool_calls: list[dict[str, Any]],
    finish_reason: str,
    *,
    known_tools: list[str] | None = None,
) -> dict[str, ToolCallShape]:
    """Normalize a raw OpenAI-compatible ``tool_calls`` list into per-tool shapes.

    ``tool_calls`` is the list under ``choice.message.tool_calls`` of a
    non-streaming /chat/completions response. Each element looks like::

        {"id": "call_abc", "type": "function",
         "function": {"name": "get_weather", "arguments": "{\\"location\\": ...}"}}

    ``known_tools`` (the suite's declared tool names) lets us emit an
    ``emitted=False`` shape for tools the provider *didn't* call, so a snapshot
    always covers the whole suite surface — "it stopped emitting this tool" is
    itself a drift worth flagging.
    """
    shapes: dict[str, ToolCallShape] = {}

    # Bucket raw calls by tool name so parallel_arity is a real count.
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for call in tool_calls or []:
        fn = (call or {}).get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        by_tool.setdefault(name, []).append(call)

    for name, calls in by_tool.items():
        first = calls[0]
        fn = first.get("function") or {}
        decoded_args, encoding = _decode_arguments(fn.get("arguments"))
        arg_nesting = {k: _json_type(v) for k, v in decoded_args.items()}
        shapes[name] = ToolCallShape(
            emitted=True,
            arg_keys=sorted(decoded_args.keys()),
            arg_nesting=arg_nesting,
            arguments_encoding=encoding,
            parallel_arity=len(calls),
            tool_call_id_format=_classify_id(first.get("id")),
            finish_reason=finish_reason,
        )

    # Cover suite tools the provider never called.
    for name in known_tools or []:
        shapes.setdefault(
            name,
            ToolCallShape(emitted=False, finish_reason=finish_reason),
        )

    return shapes
