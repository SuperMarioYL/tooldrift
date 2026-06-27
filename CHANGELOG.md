# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/SuperMarioYL/tooldrift/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SuperMarioYL/tooldrift/releases/tag/v0.1.0
