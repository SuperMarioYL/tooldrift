<div align="right"><sub><b>English</b>&nbsp;&nbsp;⇄&nbsp;&nbsp;<a href="./README.md">简体中文</a></sub></div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./assets/hero-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="./assets/hero-light.svg">
    <img src="./assets/hero-light.svg" width="880" alt="ToolDrift — tool-call contract regression sentinel for Chinese LLMs">
  </picture>
</p>

<p align="center"><sub>The tool-call contract-regression sentinel for Chinese LLMs: before you swap DeepSeek / Qwen / Kimi / GLM / MiniMax, CI red-lights which tool's schema is no longer equivalent.</sub></p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-0071E3.svg" alt="License: MIT"></a>
  <a href="https://github.com/SuperMarioYL/tooldrift/releases"><img src="https://img.shields.io/github/v/release/SuperMarioYL/tooldrift?color=5E5CE6" alt="Latest release"></a>
  <a href="https://github.com/SuperMarioYL/tooldrift/actions/workflows/tooldrift.yml"><img src="https://img.shields.io/github/actions/workflow/status/SuperMarioYL/tooldrift/tooldrift.yml?branch=main&label=CI" alt="CI status"></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB.svg" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Agent-tool--call_sentinel-10A37F.svg" alt="Agent tool-call sentinel">
  <img src="https://img.shields.io/badge/CI-red%2Fgreen-E5484D.svg" alt="red/green CI gate">
</p>

> **Turn "discover function-calling silently broke after the swap goes live" into a single `diff` you run before switching.** ToolDrift probes two providers' OpenAI-compatible `/chat/completions` with the same tool suite, normalizes each `tool_calls` response into a reconcilable contract snapshot, and diffs them field by field — green when equivalent, red with the exact deltas when not. On drift the process exits non-zero, so it drops straight into CI.

ToolDrift is **not** "Promptfoo for Chinese models," and it is not a unified API / router. It guards a patch of ground nobody else does: DeepSeek-Reasonix-class **single-model-locked** [Coding Agent](https://github.com/Hmbown/DeepSeek-TUI)s are hot, but they structurally never cross-check whether the tool-call contract stays equivalent when you migrate away; general eval frameworks (Promptfoo) only assert on text output and deliberately refuse to internalize any one provider's protocol quirks. As **X27**-class agent models like MiniMax-M2 — the ones [sermakarevich](https://twitter.com/sermakarevich) keeps discussing — push "great tool-calling" as a selling point, and as a price war makes "switch providers to cut cost" a monthly ops action, "swap model → function-calling silently breaks" turns from rare into systemic. ToolDrift names and defends a new primitive — *cross-provider tool-call contract-equivalence* — the dual of the lock-in narrative: it stands on the **migration** side and helps you switch away safely. It rides the broad [Agent](https://github.com/NousResearch/hermes-agent) tooling conversation as its backbone.

---

## Table of contents

- [Architecture](#architecture)
- [Why this exists](#why-this-exists)
- [Install](#install)
- [Quickstart](#quickstart)
- [Usage](#usage)
- [Demo](#demo)
- [Five-model `tool_calls` comparison](#five-model-tool_calls-comparison)
- [Configuration](#configuration)
- [Paid tier · hosted drift-watch board](#paid-tier--hosted-drift-watch-board)
- [Roadmap](#roadmap)
- [vs DeepSeek-Reasonix](#vs-deepseek-reasonix)
- [License](#license)

---

## <img src="https://api.iconify.design/tabler:topology-star-3.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Architecture

A single-process CLI — no server, no database, and it **never proxies your traffic**. It only reads each endpoint, normalizes, and compares.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./assets/atlas-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="./assets/atlas-light.svg">
    <img src="./assets/atlas-light.svg" width="880" alt="Architecture: suite.yaml → probe two providers → normalized contract snapshots → diff → red/green CI exit code">
  </picture>
</p>

The core primitive is **`ContractSnapshot`** — the "shape" of how each model emits `tool_calls`, distilled into something you can diff:

```text
ContractSnapshot
├─ provider / model_id            # the contract binds to a specific model/version
└─ tools: { tool_name -> ToolCallShape }
                                  ToolCallShape
                                  ├─ emitted            was this tool actually called
                                  ├─ arg_keys           top-level argument keys (sorted)
                                  ├─ arg_nesting        each argument's JSON type / nesting
                                  ├─ arguments_encoding  object | json_string
                                  ├─ parallel_arity     arity semantics of parallel tool_calls
                                  ├─ tool_call_id_format  openai | custom | absent
                                  └─ finish_reason      "tool_calls" vs other values
```

`diff(a, b)` aligns two snapshots on `tool_name`, judges equivalence field by field, and yields `[ToolDelta]` — exactly the work Promptfoo (asserts text) and DeepSeek-Reasonix (locked to one model) structurally **won't** do.

## <img src="https://api.iconify.design/tabler:bulb.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Why this exists

Every Chinese model emits `tool_calls` **differently** and not backward-compatibly: argument names change, `arguments` flips from object to string, parallel-call array semantics differ, `finish_reason` takes different values. Change one `base_url`/`model_id`, smoke-test a couple of chat prompts, ship — and a tool's schema silently drifts, so the agent calls the wrong tool, or no tool at all, in production. This is **per-model** contract drift; general text eval can't see it. ToolDrift moves it forward into a red/green light in CI, before you switch.

## <img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Install

```bash
pip install tooldrift          # or: uv tool install tooldrift
```

Five pure-Python dependencies; `pip install -e .` from a clone works just as well.

## <img src="https://api.iconify.design/tabler:player-play.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Quickstart

**See red/green with zero API keys** — every command accepts `--from-fixtures` to replay the offline samples under `tests/fixtures/`:

```bash
tooldrift snapshot --base deepseek --from-fixtures              # capture a contract snapshot
tooldrift run --old deepseek --new qwen --from-fixtures         # diff two providers; non-zero on drift
echo "CI exit code: $?"                                          # → 1 (drift caught)
```

<details><summary>sample output (a DeepSeek → Qwen swap catches 2 contract drifts)</summary>

```text
ToolDrift deepseek/deepseek-chat  →  qwen/qwen-plus   suite=weather
  ✗ get_forecast contract drift
      arg_keys            days, include, location, unit  →  days, location
      arg_nesting:days    integer                        →  string
      arguments_encoding  json_string                    →  object
      tool_call_id_format openai                         →  custom
      finish_reason       tool_calls                     →  stop
  ✗ get_weather contract drift
      arguments_encoding  json_string                    →  object
      tool_call_id_format openai                         →  custom
      finish_reason       tool_calls                     →  stop
╭──────────────────────────────────────────────────╮
│ FAIL — BREAKING drift in 2 of 2 tool(s). Exit 1. │
╰──────────────────────────────────────────────────╯
```

</details>

For live endpoints, export each provider's key (`DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, … — see [`examples/contract.yaml`](./examples/contract.yaml)) and drop `--from-fixtures`.

## <img src="https://api.iconify.design/tabler:terminal-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Usage

Four subcommands make up the OSS core:

```bash
# 1) snapshot — capture one provider's contract to JSON (binds to a model version)
tooldrift snapshot --base deepseek --suite examples/suite.weather.yaml -o snapshots/deepseek.json

# 2) diff — purely offline comparison of two saved snapshots (no network); non-zero on drift
tooldrift diff snapshots/deepseek.json snapshots/qwen.json

# 3) run — the one-line CI entry: probe old vs new, diff, red/green report + exit code
tooldrift run --old deepseek --new qwen --suite examples/suite.weather.yaml

# 4) compare-table — produce a shareable Markdown comparison across five providers
tooldrift compare-table --from-fixtures -o COMPARISON.md
```

More in [`examples/`](./examples/). Wire line 3 into CI (see `.github/workflows/tooldrift.yml`) and a model-swap PR fails the moment a schema is non-equivalent.

## <img src="https://api.iconify.design/tabler:photo.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Demo

![ToolDrift demo — snapshot one provider, then run catches the DeepSeek→Qwen drift and red-lights with a non-zero exit](assets/demo.gif)

> The same 30-second flow is also captured as an asciinema cast: [`assets/demo.cast`](./assets/demo.cast).

## <img src="https://api.iconify.design/tabler:table.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Five-model `tool_calls` comparison

A by-product of a single `tooldrift compare-table` run — this table is the best shareable hook (below is the offline-fixture result; rows marked `Δ` are the cross-provider non-equivalence points):

### `tool_calls` contract comparison — suite `weather`

| tool | field | deepseek | qwen |
|---|---|---|---|
| **get_forecast** | emitted | ✓ | ✓ |
|  | **Δ arg_keys** | `days, include, location, unit` | `days, location` |
|  | **Δ args_encoding** | `json_string` | `object` |
|  | parallel_arity | 1 | 1 |
|  | **Δ id_format** | `openai` | `custom` |
|  | **Δ finish_reason** | `tool_calls` | `stop` |
| **get_weather** | emitted | ✓ | ✓ |
|  | arg_keys | `location, unit` | `location, unit` |
|  | **Δ args_encoding** | `json_string` | `object` |
|  | parallel_arity | 1 | 1 |
|  | **Δ id_format** | `openai` | `custom` |
|  | **Δ finish_reason** | `tool_calls` | `stop` |

> With live keys for all five providers, `tooldrift compare-table` fills in the kimi / glm / minimax columns too.

## <img src="https://api.iconify.design/tabler:adjustments.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Configuration

Top-level keys of `contract.yaml` (full example in [`examples/contract.yaml`](./examples/contract.yaml)):

| key | type | default | meaning |
|---|---|---|---|
| `version` | int | `1` | contract file format version |
| `suite` | path | — | the tool suite YAML to probe with (prompt + tool defs) |
| `providers` | map | — | providers under test: each with `base_url` / `model_id` / `api_key_env` |
| `providers.<p>.api_key_env` | str | — | env var the key is read from — keys are **never** written to any file or snapshot |
| `expected` | map | *(optional)* | pin a known-good contract so `run` regresses every provider against it |

## <img src="https://api.iconify.design/tabler:building-bank.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Paid tier · hosted drift-watch board

The OSS core (`snapshot / diff / run / compare-table` CLI) is **free forever**; the moat is the open contract-snapshot format. The commercial layer is a **hosted "drift-watch board"** — it continuously re-regresses the five providers' latest APIs on a schedule and pushes an alert the moment a new version ships (e.g. *"GLM changed `arguments` stringification again"*), billed per team:

| tier | price | what you get |
|---|---|---|
| **Team** | ¥499/mo (≈$69) | hosted scheduled regression + five-provider change alerts (email / Feishu / DingTalk webhook) + private contract hosting |
| **Enterprise** | from ¥2,999/mo | private deployment, audit-trail reports (compliance/gov delivery), on-demand adapters beyond the five (Doubao / Baichuan) |

The first paying customer is an **agent middleware / framework team that promises "supports multiple Chinese models"** — every new model they onboard is a blind jump, so they have the most reason to pay for a ready-made equivalence test plus a protocol-change subscription. The board itself is out of scope for this repo (the CLI ships the seam + docs); open an issue to try the hosted layer.

## <img src="https://api.iconify.design/tabler:map-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Roadmap

- [x] **m1** · `snapshot` probes one provider, normalizes a `ContractSnapshot`, writes JSON
- [x] **m2** · `diff` pure function + `run` red/green report + non-zero CI exit
- [x] **m3** · `compare-table` produces a five-model comparison Markdown table
- [x] **m4** · CI template (`.github/workflows/tooldrift.yml`) + demo + bilingual polished README + monetization seam
- [ ] Streaming tool-call (SSE delta) reassembly
- [ ] Adapters beyond the five (Doubao / Baichuan…, paid on demand)
- [ ] Hosted "drift-watch board" SaaS (paid tier)

## <img src="https://api.iconify.design/tabler:git-compare.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> vs DeepSeek-Reasonix

Honest positioning — ToolDrift stands on the migration side, the dual of lock-in, and stays off their lane:

| axis | ToolDrift | [DeepSeek-Reasonix](https://github.com/esengine/DeepSeek-Reasonix) |
|---|---|---|
| goal | cross-provider tool-call contract **equivalence regression** | engineering an agent around **one** model (DeepSeek) to the hilt |
| single-model depth / prefix-cache engineering | — | ✓ (its 25k-star moat) |
| cross-model migration safety (equivalent when you switch away?) | ✓ | — (structurally won't — doing it would dissolve the DeepSeek-native pitch) |
| out-of-the-box agent terminal experience | partial (a CLI tool, not an agent) | ✓ |
| red/green exit code for CI | ✓ | — |

## <img src="https://api.iconify.design/tabler:license.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> License

[MIT](./LICENSE). Open an [issue](https://github.com/SuperMarioYL/tooldrift/issues) describing your real migration scenario, or send a PR adding a new provider adapter.

## Share this

```
ToolDrift — the Agent tool-call contract-regression sentinel for Chinese LLMs.
Catch broken function-calling before you swap DeepSeek/Qwen/Kimi/GLM/MiniMax. https://github.com/SuperMarioYL/tooldrift
```

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
