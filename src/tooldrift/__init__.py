"""ToolDrift — cross-provider tool-call contract regression sentinel.

ToolDrift probes each Chinese-LLM provider's OpenAI-compatible
``/chat/completions`` endpoint with the same tool suite, normalizes the
returned ``tool_calls`` into a versioned contract snapshot, and diffs two
snapshots to flag non-equivalence on a model/version swap with a red/green
CI exit code.

It is a *detector*, not a router: it never proxies business traffic and never
rewrites requests.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
