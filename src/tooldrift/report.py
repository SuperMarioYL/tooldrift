"""Render a :class:`ContractDiff` as a red/green report and drive the CI exit code.

m2's user-facing half. Two things live here:

* :func:`render_report` — pretty-prints a diff with rich: one green line per tool
  whose contract is equivalent, and a red breakdown (field · old → new · why) for
  every tool that drifted. Pure presentation; it returns nothing and raises
  nothing.
* :func:`run_diff` — given two already-built snapshots, render the report and
  return the process exit code: ``0`` when contracts are equivalent, ``1`` when
  any drift is present. This is what makes ``tooldrift run`` / ``tooldrift diff``
  drop straight into a CI step — a red exit fails the pipeline before the model
  swap reaches production.

The exit-code contract is deliberately simple and stable: *any* non-equivalence
(breaking or warning) is a non-zero exit. A contract that changed at all is not
the contract CI froze.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .diff import ContractDiff, DeltaSeverity

# Process exit codes (kept here so callers don't hardcode integers).
EXIT_EQUIVALENT = 0
EXIT_DRIFT = 1


def _severity_style(severity: DeltaSeverity) -> str:
    return "bold red" if severity is DeltaSeverity.BREAKING else "yellow"


def render_report(diff_result: ContractDiff, *, console: Console | None = None) -> None:
    """Pretty-print the diff: green for equivalent tools, red for drifted ones."""
    console = console or Console()

    header = Text()
    header.append("ToolDrift ", style="bold")
    header.append(f"{diff_result.old_label}", style="cyan")
    header.append("  →  ", style="dim")
    header.append(f"{diff_result.new_label}", style="cyan")
    if diff_result.suite:
        header.append(f"   suite={diff_result.suite}", style="dim")
    console.print(header)

    drifted = diff_result.drifted_tools
    equivalent = [t for t in diff_result.tools if t.is_equivalent]

    # Green roll-up: the tools that are still equivalent.
    for tool in equivalent:
        console.print(f"  [green]✓[/] [bold]{tool.tool}[/] [green]equivalent[/]")

    # Red breakdown: each drifted tool gets its own table of field deltas.
    for tool in drifted:
        if tool.only_in is not None:
            side = "baseline (old)" if tool.only_in == "old" else "candidate (new)"
            console.print(
                f"  [red]✗[/] [bold]{tool.tool}[/] "
                f"[red]only present in {side}[/] — the tool appears on one side only."
            )
            continue

        console.print(f"  [red]✗[/] [bold]{tool.tool}[/] [red]contract drift[/]")
        table = Table(show_header=True, header_style="bold red", box=None, pad_edge=False)
        table.add_column("field", style="bold")
        table.add_column("old")
        table.add_column("→", justify="center")
        table.add_column("new")
        table.add_column("why", style="dim")
        for fd in tool.fields:
            style = _severity_style(fd.severity)
            table.add_row(
                Text(fd.field, style=style),
                Text(fd.old, style="dim"),
                "→",
                Text(fd.new, style=style),
                fd.note,
            )
        console.print(table)

    # Verdict panel — the line a CI log reader scans for.
    if diff_result.is_equivalent:
        console.print(
            Panel.fit(
                Text(
                    f"PASS — tool-call contracts are equivalent across {len(equivalent)} tool(s).",
                    style="bold green",
                ),
                border_style="green",
            )
        )
    else:
        verb = "BREAKING drift" if diff_result.has_breaking else "drift"
        console.print(
            Panel.fit(
                Text(
                    f"FAIL — {verb} in {len(drifted)} of {len(diff_result.tools)} tool(s). "
                    f"Exit {EXIT_DRIFT}.",
                    style="bold red",
                ),
                border_style="red",
            )
        )


def run_diff(diff_result: ContractDiff, *, console: Console | None = None) -> int:
    """Render a diff and return the CI exit code (0 equivalent, 1 on any drift)."""
    render_report(diff_result, console=console)
    return EXIT_EQUIVALENT if diff_result.is_equivalent else EXIT_DRIFT
