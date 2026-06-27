"""Provider registry for the five Chinese-LLM targets.

Each provider exposes an OpenAI-compatible ``/chat/completions`` endpoint, but
the *details* differ: base URL, default model id, the env var its API key lives
in, and the occasional request quirk. This module is the single place those
defaults live, plus the resolver that merges them with whatever overrides come
from a ``contract.yaml``.

ToolDrift only ever *reads* these endpoints. It never proxies business traffic
and never rewrites a request — it sends a fixed tool suite and snapshots what
comes back.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: Built-in providers, keyed by the short name used on the CLI (``--base deepseek``).
#: All five speak the OpenAI ``/chat/completions`` dialect; ``base_url`` is the
#: OpenAI-compatible root (the client appends ``/chat/completions``).


@dataclass(frozen=True)
class Provider:
    """A single provider's connection defaults.

    ``request_quirks`` carries per-provider extra body fields that some
    endpoints need (e.g. a provider that requires an explicit ``stream: false``
    or a non-standard ``tool_choice`` spelling). They are merged into the
    request body and can be overridden per contract.
    """

    key: str
    base_url: str
    default_model: str
    api_key_env: str
    request_quirks: dict[str, object] = field(default_factory=dict)


_REGISTRY: dict[str, Provider] = {
    "deepseek": Provider(
        key="deepseek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    "qwen": Provider(
        key="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        api_key_env="DASHSCOPE_API_KEY",
    ),
    "kimi": Provider(
        key="kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        api_key_env="MOONSHOT_API_KEY",
    ),
    "glm": Provider(
        key="glm",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-plus",
        api_key_env="ZHIPUAI_API_KEY",
    ),
    "minimax": Provider(
        key="minimax",
        base_url="https://api.minimaxi.com/v1",
        default_model="MiniMax-M2",
        api_key_env="MINIMAX_API_KEY",
    ),
}


def known_providers() -> list[str]:
    """Return the sorted list of built-in provider keys."""
    return sorted(_REGISTRY.keys())


def get_provider(key: str) -> Provider:
    """Look up a built-in provider by key.

    Raises :class:`KeyError` (wrapped with a helpful message) if unknown so the
    CLI can surface a clean error.
    """
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise KeyError(
            f"unknown provider '{key}'. Known providers: {', '.join(known_providers())}"
        ) from exc


def resolve_provider(
    key: str,
    *,
    base_url: str | None = None,
    model_id: str | None = None,
    api_key_env: str | None = None,
    request_quirks: dict[str, object] | None = None,
) -> Provider:
    """Resolve a provider, layering any overrides over the built-in defaults.

    A ``contract.yaml`` can pin a custom ``base_url`` / ``model_id`` /
    ``api_key_env`` per provider (e.g. a self-hosted gateway), and an unknown
    key is allowed *as long as* enough is supplied to connect. This is how a
    user points ToolDrift at a sixth model or a private endpoint without a code
    change — while keeping the five built-ins zero-config.
    """
    if key in _REGISTRY:
        base = _REGISTRY[key]
    else:
        if not base_url or not model_id:
            raise KeyError(
                f"unknown provider '{key}' and no base_url/model_id override supplied. "
                f"Either use a built-in ({', '.join(known_providers())}) or provide both "
                f"base_url and model_id in the contract."
            )
        base = Provider(
            key=key,
            base_url=base_url,
            default_model=model_id,
            api_key_env=api_key_env or f"{key.upper()}_API_KEY",
        )

    merged_quirks = dict(base.request_quirks)
    if request_quirks:
        merged_quirks.update(request_quirks)

    return replace(
        base,
        base_url=base_url or base.base_url,
        default_model=model_id or base.default_model,
        api_key_env=api_key_env or base.api_key_env,
        request_quirks=merged_quirks,
    )
