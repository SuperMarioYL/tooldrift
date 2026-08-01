"""ToolDrift command-line interface.

m1 wires the ``snapshot`` subcommand: probe one provider with a tool suite and
write a normalized contract snapshot to disk (or stdout). The ``diff``, ``run``,
and ``compare-table`` subcommands land in m2/m3 — see the clearly marked slot
near the bottom of this file.

    tooldrift snapshot --provider deepseek --suite examples/suite.weather.yaml -o contract.json
    tooldrift snapshot --provider deepseek --from-fixtures   # zero-key offline demo
"""

from __future__ import annotations

import json
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .contract import ArgumentsEncoding, ContractSnapshot
from .contract_file import ContractFile, ContractFileError
from .diff import ContractDiff, diff as diff_snapshots
from .probe import (
    ProbeError,
    Suite,
    get_api_key,
    probe_from_fixture,
    probe_live,
)
from .providers import known_providers, resolve_provider
from .report import EXIT_DRIFT, EXIT_EQUIVALENT, render_report
from .table import compare_table

app = typer.Typer(
    name="tooldrift",
    help="Cross-provider tool-call contract regression sentinel for Chinese LLMs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

# Default suite shipped with the repo, used when --suite is omitted.
_DEFAULT_SUITE = "examples/suite.weather.yaml"
# Built-in offline fixtures, by provider, for --from-fixtures.
_FIXTURES = {
    "deepseek": "tests/fixtures/deepseek_tool_calls.json",
    "qwen": "tests/fixtures/qwen_tool_calls.json",
}


class OutputFormat(str, Enum):
    """How ``run`` / ``diff`` render the contract verdict."""

    RICH = "rich"  # default: the red/green terminal panel
    JSON = "json"  # machine-readable ContractDiff JSON to stdout


def _resolve_fixture(provider: str, fixture: Optional[Path]) -> Path:
    """Resolve the offline fixture path for a provider.

    Raises :class:`ProbeError` cleanly when no ``--fixture`` is given AND the
    provider has no built-in fixture (kimi/glm/minimax etc.) — so the user gets
    the documented "no built-in fixture" message + exit 2 instead of an
    ``IsADirectoryError`` crash. Shared by ``snapshot``/``run``/``compare-table``
    so the three paths can never diverge again.
    """
    if fixture is not None:
        return fixture
    builtin = _FIXTURES.get(provider, "")
    if not builtin:
        raise ProbeError(
            f"no built-in fixture for provider '{provider}'. "
            f"Pass --fixture PATH. Built-in fixtures: {', '.join(_FIXTURES)}."
        )
    return Path(builtin)


def _emit_diffs(
    diffs: list[ContractDiff],
    fmt: OutputFormat,
    *,
    console: Console,
) -> int:
    """Emit one or more contract diffs and return the CI exit code.

    ``rich`` mode renders every diff with the red/green panel; ``json`` mode
    writes the ContractDiff(s) as JSON to stdout and suppresses the panel so
    CI / the hosted-drift-watch seam can parse drift programmatically. The exit
    code is driven by *any* drift across all emitted diffs (0 equivalent, 1
    drift) regardless of format.
    """
    if fmt is OutputFormat.JSON:
        if len(diffs) == 1:
            payload: object = diffs[0].model_dump(mode="json")
        else:
            payload = {
                "diffs": [d.model_dump(mode="json") for d in diffs],
                "equivalent": all(d.is_equivalent for d in diffs),
            }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        for d in diffs:
            render_report(d, console=console)
    return EXIT_EQUIVALENT if all(d.is_equivalent for d in diffs) else EXIT_DRIFT


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"tooldrift {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the ToolDrift version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """ToolDrift — detect tool-call contract drift across Chinese LLM providers."""


def _render_snapshot(snapshot: ContractSnapshot) -> None:
    """Pretty-print a snapshot's per-tool contract as a rich table."""
    table = Table(
        title=f"[bold]{snapshot.provider}[/] · {snapshot.model_id} · suite={snapshot.suite}",
        title_justify="left",
        header_style="bold cyan",
        expand=False,
    )
    table.add_column("tool")
    table.add_column("emitted", justify="center")
    table.add_column("arg_keys")
    table.add_column("args_enc")
    table.add_column("arity", justify="right")
    table.add_column("id_format")
    table.add_column("finish_reason")

    for name in sorted(snapshot.tools):
        shape = snapshot.tools[name]
        emitted = "[green]✓[/]" if shape.emitted else "[dim]—[/]"
        enc = shape.arguments_encoding.value
        enc_render = (
            f"[yellow]{enc}[/]" if shape.arguments_encoding is ArgumentsEncoding.JSON_STRING else enc
        )
        table.add_row(
            name,
            emitted,
            ", ".join(shape.arg_keys) or "[dim]—[/]",
            enc_render,
            str(shape.parallel_arity),
            shape.tool_call_id_format.value,
            shape.finish_reason or "[dim]—[/]",
        )
    console.print(table)


@app.command()
def snapshot(
    provider: str = typer.Option(
        ...,
        "--provider",
        "--base",
        "-p",
        help=f"Provider key to probe. Built-ins: {', '.join(known_providers())}.",
    ),
    suite: Path = typer.Option(
        Path(_DEFAULT_SUITE),
        "--suite",
        "-s",
        help="Path to the tool suite YAML (system+user prompt + tool defs).",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the snapshot JSON here. Omit to print to stdout.",
    ),
    model_id: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Override the provider's default model id (contract binds to a version).",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Override the provider's base_url (e.g. a self-hosted gateway).",
    ),
    from_fixtures: bool = typer.Option(
        False,
        "--from-fixtures",
        help="Replay an offline saved response instead of calling the live API (no key needed).",
    ),
    fixture: Optional[Path] = typer.Option(
        None,
        "--fixture",
        help="Explicit fixture file to replay (implies offline mode).",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress the rendered table; only write/emit JSON.",
    ),
) -> None:
    """Probe one provider with a tool suite and emit a normalized contract snapshot.

    Online: reads the provider's API key from its env var (e.g. DEEPSEEK_API_KEY).
    Offline: pass --from-fixtures (or --fixture PATH) to replay a saved response so
    the tool runs with zero keys — perfect for the demo and for CI smoke tests.
    """
    try:
        loaded_suite = Suite.load(suite)
    except (OSError, ProbeError) as exc:
        err_console.print(f"[red]error:[/] could not load suite {suite}: {exc}")
        raise typer.Exit(code=2)

    resolved = resolve_provider(provider, base_url=base_url, model_id=model_id)
    effective_model = model_id or resolved.default_model

    offline = from_fixtures or fixture is not None
    try:
        if offline:
            fixture_path = _resolve_fixture(provider, fixture)
            snap = probe_from_fixture(
                fixture_path,
                provider=provider,
                model_id=effective_model,
                suite=loaded_suite,
            )
        else:
            api_key = get_api_key(resolved, dict(os.environ))
            snap = probe_live(
                resolved,
                loaded_suite,
                api_key=api_key,
                model_id=model_id,
            )
    except ProbeError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(code=2)

    json_text = snap.to_json()

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json_text, encoding="utf-8")
        if not quiet:
            _render_snapshot(snap)
            console.print(
                Panel.fit(
                    f"snapshot written → [bold]{output}[/]"
                    + ("  [dim](offline / fixture mode)[/]" if offline else ""),
                    border_style="green",
                )
            )
    else:
        if not quiet:
            _render_snapshot(snap)
        # JSON to stdout so it can be piped/redirected even without -o.
        console.print(json_text, end="", soft_wrap=True, highlight=False)


def _acquire_snapshot(
    provider: str,
    loaded_suite: Suite,
    *,
    model_id: Optional[str],
    base_url: Optional[str],
    from_fixtures: bool,
    fixture: Optional[Path] = None,
    contract: Optional[ContractFile] = None,
) -> ContractSnapshot:
    """Build a snapshot for one provider, online or from a fixture.

    Shared by ``run`` and ``compare-table`` so the online/offline branch lives in
    exactly one place. When ``contract`` is given, the provider is resolved
    through the contract file (layering its ``base_url``/``model_id``/
    ``api_key_env`` overrides over the built-ins). Raises :class:`ProbeError`
    on any failure.
    """
    if contract is not None:
        resolved = contract.resolve_provider(provider)
    else:
        resolved = resolve_provider(provider, base_url=base_url, model_id=model_id)
    effective_model = model_id or resolved.default_model
    offline = from_fixtures or fixture is not None
    if offline:
        fixture_path = _resolve_fixture(provider, fixture)
        return probe_from_fixture(
            fixture_path,
            provider=provider,
            model_id=effective_model,
            suite=loaded_suite,
        )
    api_key = get_api_key(resolved, dict(os.environ))
    return probe_live(resolved, loaded_suite, api_key=api_key, model_id=model_id)


@app.command()
def diff(
    old: Path = typer.Argument(..., help="Baseline snapshot JSON (the contract you froze)."),
    new: Path = typer.Argument(..., help="Candidate snapshot JSON (after the model/version swap)."),
    fmt: OutputFormat = typer.Option(
        OutputFormat.RICH,
        "--format",
        "-f",
        help="Output format: rich (red/green panel, default) or json (machine-readable ContractDiff).",
    ),
) -> None:
    """Diff two snapshot files for contract equivalence; exit nonzero on drift.

    Pure offline comparison of two ``tooldrift snapshot`` outputs — no network.
    Drop into CI after snapshotting old + new to red-light a breaking swap:

        tooldrift diff snapshots/deepseek.json snapshots/qwen.json
        tooldrift diff snapshots/deepseek.json snapshots/qwen.json --format json
    """
    try:
        old_snap = ContractSnapshot.from_json(old.read_text(encoding="utf-8"))
        new_snap = ContractSnapshot.from_json(new.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        err_console.print(f"[red]error:[/] could not load snapshots: {exc}")
        raise typer.Exit(code=2)

    result = diff_snapshots(old_snap, new_snap)
    raise typer.Exit(code=_emit_diffs([result], fmt, console=console))


@app.command()
def run(
    old: Optional[str] = typer.Option(
        None,
        "--old",
        help="Baseline provider key to probe (e.g. deepseek). The contract you're swapping FROM. "
        "Required UNLESS --contract is given (contract-file mode).",
    ),
    new: Optional[str] = typer.Option(
        None,
        "--new",
        help="Candidate provider key to probe (e.g. qwen). The contract you're swapping TO. "
        "Required UNLESS --contract is given (contract-file mode).",
    ),
    contract: Optional[Path] = typer.Option(
        None,
        "--contract",
        help="Path to a contract.yaml declaring providers (+ optional pinned `expected` block). "
        "Probe the --base providers, diff them pairwise AND regress each against the pinned "
        "contract. Mutually exclusive with --old/--new.",
    ),
    base: Optional[list[str]] = typer.Option(
        None,
        "--base",
        "-b",
        help="Provider(s) to probe in contract-file mode (repeatable). "
        "Defaults to all providers declared in the contract file.",
    ),
    suite: Path = typer.Option(
        Path(_DEFAULT_SUITE),
        "--suite",
        "-s",
        help="Path to the tool suite YAML. Ignored when --contract is given (the contract pins its own suite).",
    ),
    old_model: Optional[str] = typer.Option(
        None, "--old-model", help="Override the baseline provider's model id (pairwise mode only)."
    ),
    new_model: Optional[str] = typer.Option(
        None, "--new-model", help="Override the candidate provider's model id (pairwise mode only)."
    ),
    base_url: Optional[str] = typer.Option(
        None, "--base-url", help="Override both providers' base_url (pairwise mode only)."
    ),
    from_fixtures: bool = typer.Option(
        False,
        "--from-fixtures",
        help="Replay offline fixtures instead of live API calls (no key needed).",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.RICH,
        "--format",
        "-f",
        help="Output format: rich (red/green panel, default) or json (machine-readable ContractDiff).",
    ),
) -> None:
    """Probe provider(s), diff their contracts, print a red/green report, exit-code it.

    Two modes:

    * **Pairwise** (default): probe two providers with the same suite, diff them,
      exit nonzero on any drift:

        tooldrift run --old deepseek --new qwen --from-fixtures

    * **Contract-file**: load a ``contract.yaml`` that declares the providers
      (+ an optional pinned ``expected`` contract), probe the named ``--base``
      providers, diff them pairwise AND regress each against the pinned
      ``expected`` block when present; red-light + nonzero exit on any drift:

        tooldrift run --contract examples/contract.yaml --base deepseek --base qwen --from-fixtures
    """
    # Mode resolution: --contract is mutually exclusive with --old/--new.
    if contract is not None:
        if old is not None or new is not None:
            err_console.print(
                "[red]error:[/] --contract cannot be combined with --old/--new "
                "(use --base to pick providers in contract-file mode)."
            )
            raise typer.Exit(code=2)
        raise typer.Exit(code=_run_contract_mode(contract, base, from_fixtures, fmt, console))

    if old is None or new is None:
        err_console.print(
            "[red]error:[/] either pass --contract PATH (contract-file mode) "
            "or both --old and --new (pairwise mode)."
        )
        raise typer.Exit(code=2)

    try:
        loaded_suite = Suite.load(suite)
    except (OSError, ProbeError) as exc:
        err_console.print(f"[red]error:[/] could not load suite {suite}: {exc}")
        raise typer.Exit(code=2)

    try:
        old_snap = _acquire_snapshot(
            old, loaded_suite, model_id=old_model, base_url=base_url, from_fixtures=from_fixtures
        )
        new_snap = _acquire_snapshot(
            new, loaded_suite, model_id=new_model, base_url=base_url, from_fixtures=from_fixtures
        )
    except ProbeError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(code=2)

    result = diff_snapshots(old_snap, new_snap)
    raise typer.Exit(code=_emit_diffs([result], fmt, console=console))


def _run_contract_mode(
    contract_path: Path,
    base: Optional[list[str]],
    from_fixtures: bool,
    fmt: OutputFormat,
    console: Console,
) -> int:
    """Probe the --base providers from a contract.yaml, diff pairwise + vs expected.

    Returns the CI exit code (0 equivalent / 1 drift). The contract file declares
    its own suite + provider overrides, so --suite/--old-model/--new-model are
    not used here.
    """
    try:
        contract = ContractFile.load(contract_path)
    except (OSError, ContractFileError) as exc:
        err_console.print(f"[red]error:[/] could not load contract {contract_path}: {exc}")
        return 2

    # Resolve the suite path. contract.yaml's `suite:` is conventionally
    # repo-root-relative (run from the repo root), so try the path as-given
    # first; fall back to contract-file-relative only if that does not exist.
    suite_path = Path(contract.suite_path)
    if not suite_path.is_absolute() and not suite_path.exists():
        suite_path = (contract_path.parent / contract.suite_path).resolve()
    try:
        loaded_suite = Suite.load(suite_path)
    except (OSError, ProbeError) as exc:
        err_console.print(f"[red]error:[/] could not load suite {suite_path}: {exc}")
        return 2

    # Pick the providers to probe: explicit --base, else every provider declared.
    columns = base or list(contract.providers.keys())
    if not columns:
        err_console.print(
            f"[red]error:[/] contract {contract_path} declares no providers and none were "
            f"passed via --base."
        )
        return 2

    snapshots: dict[str, ContractSnapshot] = {}
    for prov in columns:
        try:
            snapshots[prov] = _acquire_snapshot(
                prov,
                loaded_suite,
                model_id=None,
                base_url=None,
                from_fixtures=from_fixtures,
                contract=contract,
            )
        except ProbeError as exc:
            # In fixture mode a provider without a fixture is expected — skip it
            # rather than failing the whole run (mirrors compare-table).
            if from_fixtures:
                err_console.print(f"[dim]skip {prov}: {exc}[/]")
                continue
            err_console.print(f"[red]error:[/] {exc}")
            return 2

    if not snapshots:
        err_console.print("[red]error:[/] no provider could be probed; nothing to diff.")
        return 2

    ordered = [p for p in columns if p in snapshots]

    # Build the diff list: pairwise consecutive + each-vs-pinned-expected.
    diffs: list[ContractDiff] = []
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        diffs.append(diff_snapshots(snapshots[a], snapshots[b]))

    expected_snap = contract.expected_snapshot(suite_name=loaded_suite.name)
    if expected_snap is not None:
        for prov in ordered:
            diffs.append(
                diff_snapshots(
                    snapshots[prov],
                    expected_snap,
                    old_label=f"{prov}/{snapshots[prov].model_id}",
                    new_label="expected/pinned",
                )
            )

    return _emit_diffs(diffs, fmt, console=console)


@app.command("compare-table")
def compare_table_cmd(
    suite: Path = typer.Option(
        Path(_DEFAULT_SUITE),
        "--suite",
        "-s",
        help="Path to the tool suite YAML to probe every provider with.",
    ),
    providers: Optional[list[str]] = typer.Option(
        None,
        "--provider",
        "--base",
        "-p",
        help="Providers to compare (repeatable). Defaults to all five built-ins.",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write the Markdown table here (e.g. COMPARISON.md)."
    ),
    from_fixtures: bool = typer.Option(
        False,
        "--from-fixtures",
        help="Use offline fixtures where available (providers without one are shown as —).",
    ),
) -> None:
    """Emit a shareable Markdown table comparing tool_calls schema across providers.

    Probes each provider with one suite and lays the normalized contracts side by
    side, flagging every row where the models disagree. Paste the result straight
    into a README or post.

        tooldrift compare-table --from-fixtures -o COMPARISON.md
    """
    try:
        loaded_suite = Suite.load(suite)
    except (OSError, ProbeError) as exc:
        err_console.print(f"[red]error:[/] could not load suite {suite}: {exc}")
        raise typer.Exit(code=2)

    columns = providers or known_providers()
    snapshots: dict[str, ContractSnapshot] = {}
    for prov in columns:
        try:
            snapshots[prov] = _acquire_snapshot(
                prov, loaded_suite, model_id=None, base_url=None, from_fixtures=from_fixtures
            )
        except ProbeError as exc:
            # In fixture mode a provider without a fixture is expected — skip its
            # column rather than failing the whole table.
            if from_fixtures:
                err_console.print(f"[dim]skip {prov}: {exc}[/]")
                continue
            err_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(code=2)

    if not snapshots:
        err_console.print("[red]error:[/] no provider could be probed; nothing to compare.")
        raise typer.Exit(code=2)

    markdown = compare_table(
        snapshots,
        providers=[p for p in columns if p in snapshots],
        suite_name=loaded_suite.name,
    )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown + "\n", encoding="utf-8")
        console.print(
            Panel.fit(f"comparison table written → [bold]{output}[/]", border_style="green")
        )
    else:
        console.print(markdown, highlight=False, soft_wrap=True)


def main() -> None:  # pragma: no cover - thin entrypoint
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
