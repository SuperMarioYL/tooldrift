"""Load a ``contract.yaml`` declaration file for ``tooldrift run --contract``.

A contract file declares the providers under test (base_url + model_id +
api_key_env, layered over the built-in registry) and, optionally, a *pinned*
``expected`` tool-call contract that each provider's ``tool_calls`` is expected
to satisfy. ``tooldrift run --contract examples/contract.yaml --base deepseek
--base qwen`` probes the named providers, diffs them pairwise AND regresses
each against the pinned ``expected`` block when present, red-lighting with a
non-zero exit on any drift.

This module is pure data loading — it never touches the network. Probing the
providers is the caller's job (in :mod:`tooldrift.cli`), so a contract file can
be unit-tested without keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .contract import ContractSnapshot, ToolCallShape
from .providers import Provider, resolve_provider


class ContractFileError(RuntimeError):
    """Raised when a contract.yaml cannot be loaded or is malformed."""


@dataclass
class ProviderOverride:
    """Per-provider overrides declared in a contract file.

    Any field left ``None`` falls back to the built-in provider defaults.
    """

    base_url: str | None = None
    model_id: str | None = None
    api_key_env: str | None = None


@dataclass
class ContractFile:
    """A loaded ``contract.yaml``: suite + provider overrides + pinned expected."""

    suite_path: str
    providers: dict[str, ProviderOverride] = field(default_factory=dict)
    expected: dict[str, dict[str, Any]] | None = None
    source: str = ""

    @classmethod
    def load(cls, path: str | Path) -> ContractFile:
        """Parse a contract.yaml file into a :class:`ContractFile`."""
        p = Path(path)
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ContractFileError(f"contract {p} is not valid yaml: {exc}") from exc
        if not isinstance(raw, dict):
            raise ContractFileError(f"contract {p} did not parse to a mapping")

        suite_path = raw.get("suite")
        if not suite_path:
            raise ContractFileError(
                f"contract {p} is missing a 'suite:' path to the tool suite yaml"
            )

        providers_raw = raw.get("providers") or {}
        if not isinstance(providers_raw, dict):
            raise ContractFileError(f"contract {p}: 'providers' must be a mapping")
        providers: dict[str, ProviderOverride] = {}
        for key, spec in providers_raw.items():
            spec = spec or {}
            if not isinstance(spec, dict):
                raise ContractFileError(
                    f"contract {p}: provider '{key}' must be a mapping"
                )
            providers[key] = ProviderOverride(
                base_url=spec.get("base_url"),
                model_id=spec.get("model_id"),
                api_key_env=spec.get("api_key_env"),
            )

        expected_raw = raw.get("expected")
        if expected_raw is not None:
            if not isinstance(expected_raw, dict):
                raise ContractFileError(f"contract {p}: 'expected' must be a mapping")
            # Normalise each tool's expected block to a plain dict for shape_from.
            expected: dict[str, dict[str, Any]] = {}
            for tool_name, shape in expected_raw.items():
                if not isinstance(shape, dict):
                    raise ContractFileError(
                        f"contract {p}: expected tool '{tool_name}' must be a mapping"
                    )
                expected[tool_name] = dict(shape)
        else:
            expected = None

        return cls(
            suite_path=str(suite_path),
            providers=providers,
            expected=expected,
            source=str(p),
        )

    def suite_path_resolved(self, *, relative_to: str | Path | None = None) -> Path:
        """Resolve the suite path, relative to the contract file if not absolute."""
        p = Path(self.suite_path)
        if p.is_absolute() or relative_to is None:
            return p
        return (Path(relative_to) / p).resolve()

    def resolve_provider(self, key: str) -> Provider:
        """Resolve a provider, layering this contract's overrides over built-ins."""
        override = self.providers.get(key)
        if override is None:
            return resolve_provider(key)
        return resolve_provider(
            key,
            base_url=override.base_url,
            model_id=override.model_id,
            api_key_env=override.api_key_env,
        )

    def expected_snapshot(self, *, suite_name: str = "") -> ContractSnapshot | None:
        """Build a :class:`ContractSnapshot` from the pinned ``expected`` block.

        Returns ``None`` when the contract declares no ``expected`` block (a pure
        cross-provider equivalence check). The returned snapshot's tools are
        :class:`ToolCallShape` instances built from the raw expected dicts, so a
        real provider snapshot can be diffed against it field-by-field.
        """
        if not self.expected:
            return None
        tools: dict[str, ToolCallShape] = {}
        # Only keep keys ToolCallShape actually carries (extra="forbid" rejects extras).
        allowed = set(ToolCallShape.model_fields.keys())
        for tool_name, shape_raw in self.expected.items():
            clean = {k: v for k, v in shape_raw.items() if k in allowed}
            tools[tool_name] = ToolCallShape(**clean)
        return ContractSnapshot(
            provider="expected",
            model_id="expected",
            suite=suite_name,
            tools=tools,
        ).with_normalized_tools()
