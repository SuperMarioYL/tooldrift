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
from pydantic import ValidationError

from .contract import ContractSnapshot, ToolCallShape
from .providers import Provider, resolve_provider


class ContractFileError(RuntimeError):
    """Raised when a contract.yaml cannot be loaded or is malformed."""


#: Keys a provider block may set. Anything else is a typo that would otherwise
#: be dropped silently — and a dropped key changes what gets probed.
_PROVIDER_STRING_FIELDS = ("base_url", "model_id", "api_key_env")
_PROVIDER_FIELDS = (*_PROVIDER_STRING_FIELDS, "request_quirks")


@dataclass
class ProviderOverride:
    """Per-provider overrides declared in a contract file.

    Any field left ``None`` falls back to the built-in provider defaults.
    ``request_quirks`` are extra request-body fields merged over the built-ins
    (e.g. a gateway that needs ``tool_choice: required``).
    """

    base_url: str | None = None
    model_id: str | None = None
    api_key_env: str | None = None
    request_quirks: dict[str, Any] | None = None


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
            # Strict keys/types: a typo such as `base_urls:`/`model:` used to be
            # dropped silently (probe fell back to the registry defaults), and a
            # non-string value crashed later in probe_live with an AttributeError
            # and exit 1 — ToolDrift's documented DRIFT code.
            unknown = sorted(str(k) for k in set(spec) - set(_PROVIDER_FIELDS))
            if unknown:
                raise ContractFileError(
                    f"contract {p}: provider '{key}' has unknown field(s): "
                    f"{', '.join(unknown)}; supported: {', '.join(_PROVIDER_FIELDS)}"
                )
            for field_name in _PROVIDER_STRING_FIELDS:
                value = spec.get(field_name)
                if value is not None and not isinstance(value, str):
                    raise ContractFileError(
                        f"contract {p}: provider '{key}' field '{field_name}' must be a "
                        f"string, got {type(value).__name__}"
                    )
            quirks = spec.get("request_quirks")
            if quirks is not None and not isinstance(quirks, dict):
                raise ContractFileError(
                    f"contract {p}: provider '{key}' field 'request_quirks' must be a "
                    f"mapping, got {type(quirks).__name__}"
                )
            providers[key] = ProviderOverride(
                base_url=spec.get("base_url"),
                model_id=spec.get("model_id"),
                api_key_env=spec.get("api_key_env"),
                request_quirks=dict(quirks) if quirks else None,
            )

        expected_raw = raw.get("expected")
        if expected_raw is not None:
            if not isinstance(expected_raw, dict):
                raise ContractFileError(f"contract {p}: 'expected' must be a mapping")
            allowed_fields = set(ToolCallShape.model_fields)
            expected: dict[str, dict[str, Any]] = {}
            for tool_name, shape in expected_raw.items():
                if not isinstance(shape, dict):
                    raise ContractFileError(
                        f"contract {p}: expected tool '{tool_name}' must be a mapping"
                    )
                # A misspelled field would otherwise be filtered out and the
                # assertion would silently stop running (a false PASS).
                unknown = sorted(str(k) for k in set(shape) - allowed_fields)
                if unknown:
                    raise ContractFileError(
                        f"contract {p}: expected tool '{tool_name}' has unknown "
                        f"field(s): {', '.join(unknown)}; supported: "
                        f"{', '.join(sorted(allowed_fields))}"
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
            request_quirks=override.request_quirks,
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
        # load() already rejected unknown keys, so nothing is dropped here.
        for tool_name, shape_raw in self.expected.items():
            try:
                tools[tool_name] = ToolCallShape(**shape_raw)
            except ValidationError as exc:
                # A pinned expected block with wrong-typed fields (e.g.
                # parallel_arity: many) is a contract-file problem, not a
                # crash: convert to ContractFileError so the CLI renders the
                # standard one-line error + exit 2, mirroring how load()
                # handles YAMLError.
                raise ContractFileError(
                    f"contract {self.source}: expected tool '{tool_name}' does "
                    f"not match the ToolCallShape schema: {exc}"
                ) from exc
        return ContractSnapshot(
            provider="expected",
            model_id="expected",
            suite=suite_name,
            tools=tools,
        ).with_normalized_tools()
