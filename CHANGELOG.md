# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-02

Iteration release. Closes two shipped-source defects and adds the
machine-readable diff output the hosted-drift-watch monetization seam needs.

### Added

- **m7 — `--format json` machine-readable diff**: `run` and `diff` now accept
  `--format {rich,json}` (default `rich`, unchanged behaviour). In `json` mode
  the `ContractDiff` is emitted as JSON to stdout and the rich panel is
  suppressed, so CI pipelines — and the documented hosted-drift-watch board —
  can parse drift programmatically instead of scraping terminal colour. The
  exit code still reflects drift (0 equivalent / 1 drift). Covered by
  `tests/test_json_diff.py`.

### Fixed

- **m5 — `--contract` contract-file mode for `run`**: the headline happy-path
  command `tooldrift run --contract examples/contract.yaml --base deepseek
  --base qwen` (documented in the README pitch and the shipped
  `examples/contract.yaml` header) previously failed with
  `No such option: --contract`; the contract.yaml `expected:` pinned-contract
  block was read by no code path. `run` now loads a `contract.yaml` (declares
  providers + an optional pinned `expected` contract), probes the `--base`
  providers, diffs them pairwise AND regresses each against the pinned
  `expected` block when present, red-lighting with a non-zero exit on any drift.
  Covered by `tests/test_contract_run.py`.
- **m6 — `snapshot` no-builtin-fixture guard**: `tooldrift snapshot --provider
  kimi --from-fixtures` (kimi/glm/minimax have no built-in fixture) crashed
  with `IsADirectoryError: [Errno 21] Is a directory: '.'` because
  `Path(_FIXTURES.get(provider, ""))` yielded `Path(".")` and the
  `if not str(fixture_path)` guard was always `False`. The offline-fixture
  resolution is now unified into one helper shared by `snapshot` / `run` /
  `compare-table`, so the documented clean "no built-in fixture" error + exit 2
  is raised instead. Covered by `tests/test_snapshot_fixture_guard.py`.

## [0.1.0] - 2026-06-27

First public release. ToolDrift is a per-provider tool-call contract regression
sentinel for Chinese LLMs (DeepSeek / Qwen / Kimi / GLM / MiniMax): it probes
each provider's OpenAI-compatible `/chat/completions` with one tool suite,
normalizes the `tool_calls` contract, and red-lights a non-equivalent
model/version swap with a CI-ready exit code.

### Added

- **m1 — `snapshot`**: probe one provider with a tool suite and write a
  normalized `ContractSnapshot` (per-tool `arg_keys`, `arg_nesting`,
  `arguments_encoding` of `object` vs `json_string`, `parallel_arity`,
  `tool_call_id_format`, `finish_reason`). `--from-fixtures` runs fully offline
  with zero API keys.
- **m2 — `diff` / `run`**: `diff old.json new.json` compares two snapshots as a
  pure function; `run --old <p> --new <p>` probes both providers, diffs their
  contracts, prints a red/green `rich` report, and exits non-zero on drift so it
  drops straight into CI. Covered by `tests/test_diff.py`.
- **m3 — `compare-table`**: emit a shareable Markdown table laying the five
  providers' `tool_calls` schema side by side, flagging every disagreement.
- **m4 — CI & polish**: `tooldrift` / `release` / `demo` GitHub Actions
  workflows, a `vhs` demo tape rendering `assets/demo.gif`, an asciinema cast,
  hand-built hero + architecture SVGs (light/dark), and bilingual polished
  READMEs (Chinese primary + `README.en.md`). The OSS-core / hosted
  drift-watch monetization seam is documented but not implemented.

[Unreleased]: https://github.com/SuperMarioYL/tooldrift/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/SuperMarioYL/tooldrift/releases/tag/v0.2.0
[0.1.0]: https://github.com/SuperMarioYL/tooldrift/releases/tag/v0.1.0
