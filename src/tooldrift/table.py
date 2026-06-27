"""m3: the shareable five-model ``tool_calls`` schema comparison table.

``tooldrift compare-table`` probes (or replays from fixtures) every target
provider with one suite, then renders a single Markdown table that lays the
five providers' normalized tool-call contracts side by side — the artifact you
paste into a README, a 掘金 long-form, or a PR description to show, at a glance,
*where the five Chinese models disagree* on tool-call shape.

Each row is one (tool, field) pair; each column is a provider. Cells that differ
across providers are flagged so a reader's eye lands on the drift. This module is
pure rendering over already-built :class:`ContractSnapshot`s — collecting the
snapshots (live vs fixtures) is the caller's job in :mod:`tooldrift.cli`.
"""

from __future__ import annotations

from .contract import ContractSnapshot, ToolCallShape

# The per-tool fields surfaced as rows, in display order, with friendly labels.
_ROW_FIELDS: list[tuple[str, str]] = [
    ("emitted", "emitted"),
    ("arg_keys", "arg_keys"),
    ("arguments_encoding", "args_encoding"),
    ("parallel_arity", "parallel_arity"),
    ("tool_call_id_format", "id_format"),
    ("finish_reason", "finish_reason"),
]


def _cell(shape: ToolCallShape | None, field_name: str) -> str:
    """Render one provider's value for one tool field as a Markdown cell."""
    if shape is None:
        return "—"
    if field_name == "emitted":
        return "✓" if shape.emitted else "✗"
    if field_name == "arg_keys":
        return "`" + ", ".join(shape.arg_keys) + "`" if shape.arg_keys else "—"
    if field_name == "arguments_encoding":
        return f"`{shape.arguments_encoding.value}`"
    if field_name == "parallel_arity":
        return str(shape.parallel_arity)
    if field_name == "tool_call_id_format":
        return f"`{shape.tool_call_id_format.value}`"
    if field_name == "finish_reason":
        return f"`{shape.finish_reason}`" if shape.finish_reason else "—"
    return "—"


def _raw_value(shape: ToolCallShape | None, field_name: str) -> str:
    """Comparable scalar for the 'do these cells agree?' check (ignores missing)."""
    if shape is None:
        return "\x00missing"
    if field_name == "emitted":
        return str(shape.emitted)
    if field_name == "arg_keys":
        return ",".join(shape.arg_keys)
    if field_name == "arguments_encoding":
        return shape.arguments_encoding.value
    if field_name == "parallel_arity":
        return str(shape.parallel_arity)
    if field_name == "tool_call_id_format":
        return shape.tool_call_id_format.value
    if field_name == "finish_reason":
        return shape.finish_reason
    return ""


def _row_agrees(shapes: list[ToolCallShape | None], field_name: str) -> bool:
    """True when every present provider reports the same value for this field."""
    present = [_raw_value(s, field_name) for s in shapes if s is not None]
    return len(set(present)) <= 1


def compare_table(
    snapshots: dict[str, ContractSnapshot],
    *,
    providers: list[str] | None = None,
    suite_name: str = "",
    title: str | None = None,
) -> str:
    """Render the five-model ``tool_calls`` schema comparison as Markdown.

    ``snapshots`` maps provider key -> snapshot. ``providers`` fixes the column
    order (defaults to sorted snapshot keys). A ``Δ`` marker prefixes any row
    where the providers disagree, so the drift is scannable in plain Markdown.
    """
    columns = providers or sorted(snapshots)
    # Only keep columns we actually have a snapshot for, preserving order.
    columns = [p for p in columns if p in snapshots]

    suite_name = suite_name or next(
        (snapshots[p].suite for p in columns if snapshots[p].suite), ""
    )
    heading = title or (
        f"`tool_calls` contract comparison"
        + (f" — suite `{suite_name}`" if suite_name else "")
    )

    # Union of all tool names across the snapshots, suite order isn't known here
    # so sort for determinism.
    tool_names: list[str] = sorted(
        {name for snap in snapshots.values() for name in snap.tools}
    )

    lines: list[str] = [f"### {heading}", ""]

    header_cells = ["tool", "field", *columns]
    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("|" + "|".join(["---"] * len(header_cells)) + "|")

    for tool in tool_names:
        shapes: list[ToolCallShape | None] = [
            snapshots[p].tools.get(tool) for p in columns
        ]
        for raw_field, label in _ROW_FIELDS:
            agrees = _row_agrees(shapes, raw_field)
            field_label = label if agrees else f"**Δ {label}**"
            cells = [_cell(s, raw_field) for s in shapes]
            # Only repeat the tool name on its first row for readability.
            tool_cell = f"**{tool}**" if raw_field == _ROW_FIELDS[0][0] else ""
            lines.append(
                "| " + " | ".join([tool_cell, field_label, *cells]) + " |"
            )

    lines.append("")
    lines.append(
        "> Rows marked `Δ` differ across providers — those are the tool-call "
        "contract drifts to handle before swapping models. Columns shown: "
        + ", ".join(f"`{c}`" for c in columns)
        + "."
    )
    lines.append("")
    return "\n".join(lines)
