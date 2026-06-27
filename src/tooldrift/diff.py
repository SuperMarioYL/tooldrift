"""Pure contract-equivalence diff between two :class:`ContractSnapshot`s.

This is the heart of ToolDrift's m2 milestone — and the one module that is a
plain, side-effect-free function so it can be exhaustively unit-tested.

The question it answers is narrow and load-bearing: *are these two snapshots'
tool-call contracts equivalent?* "Equivalent" is decided per tool, per field,
by principled rules:

* **arguments_encoding** — ``json_string`` vs ``object`` is a BREAKING diff. A
  caller that ``json.loads`` the OpenAI-canonical string will throw on a
  provider that inlines an object (and vice-versa). This is the single most
  common silent break on a model swap, so it is always flagged.
* **arg_keys** — the set of top-level argument keys must match exactly. A
  dropped or renamed key changes what the downstream handler receives.
* **arg_nesting** — for the keys present on both sides, the JSON type/shape must
  match (``object`` becoming ``string`` is a contract break).
* **emitted** — a tool that stops being called on the new side is drift: the
  agent silently lost a capability.
* **parallel_arity** — the number of parallel calls to a tool changes the loop
  semantics a caller must handle (1 vs N).
* **tool_call_id_format** — ``openai`` vs ``custom`` vs ``absent`` matters for
  callers that key state on the id shape.
* **finish_reason** — ``tool_calls`` vs anything else changes how a caller
  decides "the model wants me to run a tool".

Every non-equivalent field becomes a :class:`FieldDelta`; the per-tool deltas
roll up into :class:`ToolDelta`; the whole comparison is a
:class:`ContractDiff` that knows whether the contracts ``is_equivalent`` (the
CI exit code derives from exactly that).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .contract import ContractSnapshot, ToolCallShape

# The fields whose inequality breaks tool-call equivalence. ``arg_nesting`` is
# handled specially (per-key), and ``arg_keys`` is compared as a set, so they are
# not in this flat scalar list.
_SCALAR_FIELDS: tuple[str, ...] = (
    "emitted",
    "arguments_encoding",
    "parallel_arity",
    "tool_call_id_format",
    "finish_reason",
)


class DeltaSeverity(str, Enum):
    """How damaging a single field difference is to a downstream caller.

    ``breaking`` differences will, in practice, crash or silently misroute a
    tool-calling agent on the swap; ``warning`` differences are observable
    contract changes that may be tolerable depending on the caller. Both are
    reported; only their colour and the headline message differ. ToolDrift's
    exit code is driven by *any* delta, regardless of severity — a contract that
    changed at all is not equivalent.
    """

    BREAKING = "breaking"
    WARNING = "warning"


class FieldDelta(BaseModel):
    """One non-equivalent field within a tool's contract."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="The ToolCallShape field that differs (or 'arg_nesting:<key>').")
    old: str = Field(description="Stringified value on the OLD (baseline) side.")
    new: str = Field(description="Stringified value on the NEW (candidate) side.")
    severity: DeltaSeverity = Field(default=DeltaSeverity.WARNING)
    note: str = Field(default="", description="Human-readable reason this difference matters.")


class ToolDelta(BaseModel):
    """All non-equivalent fields for a single tool name.

    A tool present on only one side is itself a delta (``only_in``); otherwise
    ``fields`` carries the per-field differences.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    only_in: str | None = Field(
        default=None,
        description="If the tool exists on only one side, which one ('old' or 'new').",
    )
    fields: list[FieldDelta] = Field(default_factory=list)

    @property
    def is_equivalent(self) -> bool:
        return self.only_in is None and not self.fields


class ContractDiff(BaseModel):
    """The full equivalence verdict between two snapshots."""

    model_config = ConfigDict(extra="forbid")

    old_label: str = Field(description="Identifier for the baseline snapshot (provider/model).")
    new_label: str = Field(description="Identifier for the candidate snapshot (provider/model).")
    suite: str = Field(default="")
    tools: list[ToolDelta] = Field(default_factory=list)

    @property
    def drifted_tools(self) -> list[ToolDelta]:
        """Tools whose contract is NOT equivalent across the two snapshots."""
        return [t for t in self.tools if not t.is_equivalent]

    @property
    def is_equivalent(self) -> bool:
        """True iff every tool's contract is equivalent (drives the CI exit code)."""
        return not self.drifted_tools

    @property
    def has_breaking(self) -> bool:
        return any(
            fd.severity is DeltaSeverity.BREAKING for t in self.tools for fd in t.fields
        )


# --------------------------------------------------------------------------- #
# Field-level comparison                                                       #
# --------------------------------------------------------------------------- #


def _scalar_value(shape: ToolCallShape, field_name: str) -> str:
    """Stringify a scalar ToolCallShape field for stable comparison/display."""
    value = getattr(shape, field_name)
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _severity_for(field_name: str) -> DeltaSeverity:
    """Classify how damaging a given field's difference is."""
    breaking = {
        "arguments_encoding",  # json.loads on the wrong encoding crashes the caller
        "arg_keys",
        "emitted",  # the agent silently lost a tool
    }
    if field_name in breaking or field_name.startswith("arg_nesting:"):
        return DeltaSeverity.BREAKING
    return DeltaSeverity.WARNING


def _note_for(field_name: str) -> str:
    notes = {
        "arguments_encoding": (
            "arguments switched between a JSON string and an inline object — "
            "a caller that json.loads() the arguments will break on the swap."
        ),
        "arg_keys": "the set of top-level argument keys changed (key renamed/dropped/added).",
        "emitted": "the tool stopped (or started) being emitted for the same prompt.",
        "parallel_arity": "the number of parallel calls to this tool changed (loop semantics differ).",
        "tool_call_id_format": "the tool_call id shape changed; callers keying on the id format may break.",
        "finish_reason": "the choice finish_reason changed; tool-dispatch gating may differ.",
    }
    if field_name.startswith("arg_nesting:"):
        key = field_name.split(":", 1)[1]
        return f"the JSON type of argument '{key}' changed (nesting/shape drift)."
    return notes.get(field_name, "")


def _diff_tool(old: ToolCallShape, new: ToolCallShape) -> list[FieldDelta]:
    """Compare two tool shapes field-by-field, returning every difference."""
    deltas: list[FieldDelta] = []

    # arg_keys compared as an ordered set (both are already sorted on snapshot).
    if list(old.arg_keys) != list(new.arg_keys):
        deltas.append(
            FieldDelta(
                field="arg_keys",
                old=", ".join(old.arg_keys) or "—",
                new=", ".join(new.arg_keys) or "—",
                severity=_severity_for("arg_keys"),
                note=_note_for("arg_keys"),
            )
        )

    # arg_nesting compared per key over the union, so an added/removed/retyped
    # argument all surface as concrete per-key deltas.
    for key in sorted(set(old.arg_nesting) | set(new.arg_nesting)):
        old_type = old.arg_nesting.get(key, "absent")
        new_type = new.arg_nesting.get(key, "absent")
        if old_type != new_type:
            deltas.append(
                FieldDelta(
                    field=f"arg_nesting:{key}",
                    old=old_type,
                    new=new_type,
                    severity=_severity_for(f"arg_nesting:{key}"),
                    note=_note_for(f"arg_nesting:{key}"),
                )
            )

    # Remaining scalar fields.
    for field_name in _SCALAR_FIELDS:
        old_v = _scalar_value(old, field_name)
        new_v = _scalar_value(new, field_name)
        if old_v != new_v:
            deltas.append(
                FieldDelta(
                    field=field_name,
                    old=old_v,
                    new=new_v,
                    severity=_severity_for(field_name),
                    note=_note_for(field_name),
                )
            )

    return deltas


def diff(
    old: ContractSnapshot,
    new: ContractSnapshot,
    *,
    old_label: str | None = None,
    new_label: str | None = None,
) -> ContractDiff:
    """Compare two snapshots for tool-call contract equivalence.

    Pure function: no I/O, deterministic, fully unit-testable. The result's
    :attr:`ContractDiff.is_equivalent` is the single source of truth for the CI
    red/green exit code in :mod:`tooldrift.report`.

    Tools are aligned on name. A tool present on only one side is recorded as an
    ``only_in`` delta. For tools on both sides, every non-equivalent field is
    enumerated.
    """
    old = old.with_normalized_tools()
    new = new.with_normalized_tools()

    old_label = old_label or f"{old.provider}/{old.model_id}"
    new_label = new_label or f"{new.provider}/{new.model_id}"

    tool_names = sorted(set(old.tools) | set(new.tools))
    tool_deltas: list[ToolDelta] = []

    for name in tool_names:
        in_old = name in old.tools
        in_new = name in new.tools

        if in_old and not in_new:
            tool_deltas.append(ToolDelta(tool=name, only_in="old"))
            continue
        if in_new and not in_old:
            tool_deltas.append(ToolDelta(tool=name, only_in="new"))
            continue

        fields = _diff_tool(old.tools[name], new.tools[name])
        tool_deltas.append(ToolDelta(tool=name, fields=fields))

    return ContractDiff(
        old_label=old_label,
        new_label=new_label,
        suite=new.suite or old.suite,
        tools=tool_deltas,
    )
