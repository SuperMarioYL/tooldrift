# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-10-15

Iteration release. Six post-ship defect fixes completing the malformed-input
story v0.3.0/v0.4.0 started (non-JSON input was covered; JSON of the wrong
SHAPE still crashed with a raw traceback and — worse — exit 1, the documented
DRIFT code), plus the release pipeline now attaching its build artifacts to
the GitHub Release. All found by reading and probing the shipped v0.4.0
source (the repo ships cold: 0 open issues).

### Fixed

- **m12 — structurally-malformed response bodies exit cleanly**: a fixture
  (or a live HTTP 200 body) containing valid JSON of the wrong shape — an
  array, a scalar, `choices` as a string, `message` as a string, `tool_calls`
  entries as strings — crashed with a raw `AttributeError` traceback and
  exit 1, ToolDrift's documented DRIFT code, so a corrupt fixture in CI
  misreported as contract drift. The parse layer now raises a named
  `ProbeError` (body not a JSON object / `choices` not a list / choice or
  message not a mapping) on both the fixture-replay and live paths, and
  non-mapping `tool_calls` elements are skipped like unnamed ones. Covered by
  `tests/test_v050.py`.
- **m13 — wrong-typed `expected:` blocks exit cleanly**: a contract.yaml
  pinning e.g. `expected: {get_weather: {parallel_arity: many}}` crashed with
  a raw pydantic `ValidationError` traceback and exit 1 (drift code) from
  `_run_contract_mode`. `expected_snapshot` now converts `ValidationError`
  into `ContractFileError` (mirroring `load`'s YAML handling) and the call
  site renders the standard one-line error + exit 2. Covered by
  `tests/test_v050.py`.
- **m14 — fixture mode now honors its documented model-override refusal**:
  the README and website document "fixture mode refuses incompatible model
  overrides rather than relabeling saved data", but no such guard existed —
  `snapshot --provider deepseek --from-fixtures --model anything` exited 0
  and stamped `model_id: anything` onto a deepseek-chat fixture's data. An
  explicit `--model`/`--old-model`/`--new-model` that disagrees with the
  fixture body's recorded `model` now exits 2 with a named error, and
  unlabeled replays stamp the body's recorded model so saved data is never
  relabeled. Covered by `tests/test_v050.py`.
- **m15 — structurally-malformed suite files exit cleanly**: a suite with
  `tools: [get_weather]` (bare strings) crashed with a raw `AttributeError`
  and exit 1, and `messages: hello` was silently coerced into five
  single-character "messages". `Suite.load` now validates that `messages` and
  `tools` are lists of mappings and raises a named `ProbeError`. Covered by
  `tests/test_v050.py`.
- **m16 — unwritable `--output` targets exit cleanly**: `snapshot -o` /
  `compare-table -o` pointed at an unwritable path (parent is a file,
  permission denied) crashed with a raw `OSError` traceback and exit 1. Both
  write sites now catch `OSError` and print the one-line `error:` + exit 2,
  closing the last raw-traceback user-input path outside the v0.4.0
  clean-error contract. Covered by `tests/test_v050.py`.
- **m17 — the release workflow attaches its artifacts to the GitHub
  Release**: the release run built sdist + wheel + `checksums.txt` but only
  parked them in a private workflow artifact, so the v0.4.0 release shipped
  wheel-only (no sdist, no checksums). A new `publish` job downloads the
  artifact and `gh release upload`s wheel + sdist + `checksums.txt` on tag
  push. The v0.5.0 release carries all three.

## [0.4.0] - 2026-09-11

Iteration release. Four post-ship defect fixes hardening the CLI's
clean-error contract — every user-input failure now exits with a one-line
`error:` message and exit code 2, never a raw traceback or a silent pass.
All found by reading and probing the shipped v0.3.0 source (the repo ships
cold: 0 open issues).

### Fixed

- **m8 — unknown provider keys exit cleanly**: `resolve_provider` raises
  `KeyError` for an unknown provider key, and that exception escaped the CLI
  as a raw traceback with exit 1 — which is ToolDrift's documented DRIFT code,
  so a typo'd provider key in a CI script was misreported as contract drift.
  `tooldrift snapshot --provider openai`, `run --old ... --new notaprovider`,
  and `compare-table --provider mystery` all crashed this way. The KeyError is
  now converted to a `ProbeError` at the two resolution sites, so all three
  commands print the clean one-line error (with the known-providers hint) and
  exit 2. Covered by `tests/test_cli_clean_errors.py`.
- **m9 — malformed suite YAML exits cleanly**: `Suite.load` called
  `yaml.safe_load` unguarded, so a malformed suite file crashed with a raw
  `yaml.ScannerError` traceback and exit 1 (while the sibling
  `ContractFile.load` already handled the same error class cleanly).
  `yaml.YAMLError` is now converted to a clean `ProbeError` ("could not load
  suite ... not valid yaml") at the owning layer, covering all four CLI
  commands. Covered by `tests/test_cli_clean_errors.py`.
- **m10 — a non-JSON fixture file exits cleanly**: `load_fixture` validated
  the path but called `json.loads` unguarded, so a fixture containing invalid
  JSON crashed with a raw `json.JSONDecodeError` traceback and exit 1 — the
  offline twin of the m5 non-JSON-200 fix shipped in v0.3.0. The decode error
  is now converted to a clean `ProbeError` ("fixture ... is not valid JSON").
  Covered by `tests/test_cli_clean_errors.py`.
- **m11 — contract-file run with nothing to compare fails loudly**:
  `tooldrift run --contract c.yaml --base <single-provider>` where the
  contract pins no `expected:` block printed NOTHING and exited 0 — an empty
  diff list meant `_emit_diffs` emitted no output and returned "equivalent".
  In CI that silent green reads as "contract passed" when zero assertions
  ran. The run now fails with an actionable error ("nothing to compare: pass
  at least two --base providers or add an 'expected:' block") and exit 2.
  Covered by `tests/test_cli_clean_errors.py`.

## [0.3.0] - 2026-08-29

Iteration release. Three post-ship defect fixes on the documented happy paths,
all found by reading the shipped v0.2.0 source (the repo ships cold: 0 open
issues).

### Fixed

- **m5 — `probe_live` non-JSON 200-OK crash**: `probe_live` called `resp.json()`
  inside a try whose except clauses caught only `httpx` exceptions, so a provider
  (or the reverse-proxy / WAF in front of it) returning HTTP 200 with a non-JSON
  body (an HTML error page, a truncated payload, a 200-wrapped gateway error)
  crashed the CLI with a raw `json.JSONDecodeError` traceback instead of the
  documented clean `ProbeError` + exit 2 every other network failure produced.
  A `ValueError` (covers `json.JSONDecodeError`) branch now converts it to a
  clean `ProbeError` carrying the HTTP status and a body snippet. Covered by
  `tests/test_probe_live_nonjson.py`.
- **m6 — `snapshot` stdout is clean pipeable JSON**: with no `--output`,
  `tooldrift snapshot` printed the human-readable rich table to stdout ahead of
  the snapshot JSON, so `tooldrift snapshot ... | jq` (or `| python -m
  json.tool`) failed — contradicting the inline doc that claimed stdout was
  pipeable. The table now goes to stderr, leaving stdout as pure JSON; the
  `--output` and `--quiet` paths are unchanged. Covered by
  `tests/test_snapshot_stdout.py`.
- **m7 — bundle the default suite + built-in fixtures in the package**:
  `_DEFAULT_SUITE` and `_FIXTURES` were CWD-relative paths and the wheel shipped
  neither `examples/` nor `tests/`, so an installed user running the documented
  zero-key demo `tooldrift snapshot --provider deepseek --from-fixtures` from any
  non-repo directory hit "could not load suite" before seeing a red/green result.
  The default suite and the two built-in fixtures now ship as package data under
  `tooldrift/_data/` and resolve relative to the package, so the demo works from
  any CWD. Covered by `tests/test_bundled_resources.py`.

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

[Unreleased]: https://github.com/SuperMarioYL/tooldrift/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/SuperMarioYL/tooldrift/releases/tag/v0.3.0
[0.2.0]: https://github.com/SuperMarioYL/tooldrift/releases/tag/v0.2.0
[0.1.0]: https://github.com/SuperMarioYL/tooldrift/releases/tag/v0.1.0
