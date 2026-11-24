"""Shared model catalog for CLI selections and validation."""

from __future__ import annotations

ModelOption = tuple[str, str]
ProviderModeOptions = dict[str, dict[str, list[ModelOption]]]

# Providers that serve many / frequently-changing models: offer only "Custom
# model ID" rather than a list that goes stale.
_CUSTOM_ONLY: dict[str, list[ModelOption]] = {
    "quick": [("Custom model ID", "custom")],
    "deep": [("Custom model ID", "custom")],
}


# Shared model list for GLM via Z.AI (international) and BigModel (China).
# Source: docs.z.ai (GLM Coding Plan supported models + LLM guides).
# All GLM 4.7+ entries support thinking mode via thinking={"type":"enabled"}.
_GLM_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("GLM-5.3-Flash - Fast, cost-efficient, 1M ctx", "glm-5.3-flash"),
        ("GLM-5-Turbo - Fast, switchable thinking modes", "glm-5-turbo"),
        ("GLM-4.5-Air - Lightweight, cost-efficient", "glm-4.5-air"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("GLM-5.3 - Latest flagship, 1M ctx", "glm-5.3"),
        ("GLM-5.2 - 744B, 1M ctx", "glm-5.2"),
        ("GLM-5.1 - 745B, 200K ctx", "glm-5.1"),
        ("GLM-4.7 - Previous-gen flagship", "glm-4.7"),
        ("Custom model ID", "custom"),
    ],
}


# Shared model list for Qwen's global (dashscope-intl) and CN (dashscope) endpoints.
# Source: modelstudio.console.alibabacloud.com (Featured Models — Flagship + Cost-optimized).
#
# Only versioned IDs are exposed in the dropdown. The version-less aliases
# (qwen-plus, qwen-flash) are documented by Alibaba as auto-upgrading
# pointers ("backbone, latest, and snapshot ... have been upgraded to the
# Qwen3 series"), which means their behavior shifts when Alibaba rotates
# the backing model. Users who want a specific generation pick it
# explicitly; users who really want auto-latest can enter the alias via
# "Custom model ID".
_QWEN_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("Qwen 3.8 Flash - Fast, cost-efficient", "qwen3.8-flash"),
        ("Qwen 3.7 Plus - Balanced speed and cost", "qwen3.7-plus"),
        ("Qwen 3.6 Plus - Previous-gen balanced", "qwen3.6-plus"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("Qwen4 Max - Flagship reasoning model", "qwen4-max"),
        ("Qwen 3.8 Max - Previous flagship", "qwen3.8-max"),
        ("Qwen 3.7 Max - Earlier flagship", "qwen3.7-max"),
        ("Qwen 3.6 Max - Previous-gen flagship", "qwen3.6-max"),
        ("Qwen 3.7 Plus - Balanced alternative", "qwen3.7-plus"),
        ("Custom model ID", "custom"),
    ],
}


# Shared model list for MiniMax's global and CN endpoints (same IDs).
# Full official lineup per platform.minimax.io/docs/api-reference/text-openai-api.
# M3 carries a 1M-token context window; the M2.x line is 204,800 tokens.
_MINIMAX_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("MiniMax M3.1 Flash - Fast multimodal reasoning", "MiniMax-M3.1-Flash"),
        ("MiniMax M3 - 1M context, native multimodal", "MiniMax-M3"),
        ("MiniMax-M2.7-highspeed - Fast M2.7, 204K ctx, ~100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5-highspeed - Previous-gen highspeed, 204K ctx", "MiniMax-M2.5-highspeed"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("MiniMax M3.1 Flash - Latest, tunable reasoning depth", "MiniMax-M3.1-Flash"),
        ("MiniMax M3 - Previous flagship", "MiniMax-M3"),
        ("MiniMax-M2.7 - Previous flagship, 204K ctx", "MiniMax-M2.7"),
        ("MiniMax-M2.7-highspeed - Same quality as M2.7, ~100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5 - Earlier flagship, 204K ctx", "MiniMax-M2.5"),
        ("Custom model ID", "custom"),
    ],
}


MODEL_OPTIONS: ProviderModeOptions = {
    "openai": {
        "quick": [
            ("GPT-6 Luna - Fast, cost-efficient", "gpt-6-luna"),
            ("GPT-6.1 Terra - Efficient multimodal reasoning", "gpt-6.1-terra"),
            ("GPT-5.6 Luna - Previous fast model", "gpt-5.6-luna"),
            ("GPT-5.6 Terra - Balances intelligence and cost", "gpt-5.6-terra"),
            ("GPT-5.4 Mini - Fast, strong coding and tool use", "gpt-5.4-mini"),
        ],
        "deep": [
            ("GPT-6.2 Sol - Everyday agent workflows", "gpt-6.2-sol"),
            ("GPT-6.2 Astra - Flagship reasoning", "gpt-6.2-astra"),
            ("GPT-5.6 Sol - Previous flagship", "gpt-5.6"),
            ("GPT-5.6 Terra - Balances intelligence and cost", "gpt-5.6-terra"),
            ("GPT-5.5 - Previous-gen frontier, 1M context", "gpt-5.5"),
            ("GPT-5.4 - Cost-effective, 1M context", "gpt-5.4"),
        ],
    },
    "anthropic": {
        "quick": [
            ("Claude Haiku 5.5 - Low latency and cost", "claude-haiku-5-5"),
            ("Claude Sonnet 5.5 - Balanced performance", "claude-sonnet-5-5"),
            ("Claude Sonnet 5 - Previous balanced model", "claude-sonnet-5"),
            ("Claude Haiku 4.5 - Fastest with near-frontier intelligence", "claude-haiku-4-5"),
        ],
        "deep": [
            ("Claude Opus 5.5 - Recommended for complex work", "claude-opus-5-5"),
            ("Claude Fable 5.2 - Demanding long-horizon reasoning", "claude-fable-5-2"),
            ("Claude Sonnet 5.5 - Balanced performance", "claude-sonnet-5-5"),
            ("Claude Fable 5 - Earlier reasoning model", "claude-fable-5"),
            ("Claude Opus 4.8 - Frontier agentic coding and reasoning", "claude-opus-4-8"),
            ("Claude Sonnet 5 - Near-frontier intelligence at Sonnet cost", "claude-sonnet-5"),
            ("Claude Opus 4.7 - Previous frontier, long-running agents", "claude-opus-4-7"),
        ],
    },
    "google": {
        "quick": [
            ("Gemini 4 Hydrogen - Fast everyday agent workflows", "gemini-4-hydrogen"),
            ("Gemini 3.8 Flash - Previous-generation Flash", "gemini-3.8-flash"),
            ("Gemini 3.5 Flash - Earlier Flash model", "gemini-3.5-flash"),
            ("Gemini 3.1 Flash Lite - Most cost-efficient", "gemini-3.1-flash-lite"),
        ],
        "deep": [
            ("Gemini 4 Neon - Frontier reasoning and speed", "gemini-4-neon"),
            ("Gemini 4 Carbon - Flagship reasoning", "gemini-4-carbon"),
            ("Gemini 4 Argon - Efficient frontier reasoning", "gemini-4-argon"),
            ("Gemini 3.8 Flash - Previous-generation Flash", "gemini-3.8-flash"),
        ],
    },
    "xai": {
        "quick": [
            ("Grok 4.7 - Current flagship", "grok-4.7"),
            ("Grok 4.3 - Earlier reasoning model", "grok-4.3"),
            ("Grok 4.20 (Non-Reasoning) - Speed-optimized", "grok-4.20-0309-non-reasoning"),
            ("Grok Build 0.1 - Coding-specialized, 256K ctx", "grok-build-0.1"),
        ],
        "deep": [
            ("Grok 4.7 - Current flagship", "grok-4.7"),
            ("Grok 4.6 - Previous flagship", "grok-4.6"),
            ("Grok 4.3 - Earlier reasoning model", "grok-4.3"),
            ("Grok 4.20 (Reasoning) - Previous-gen reasoning", "grok-4.20-0309-reasoning"),
            ("Grok 4.20 Multi-Agent - Multi-agent reasoning", "grok-4.20-multi-agent-0309"),
        ],
    },
    # DeepSeek recommends deepseek-flash for the current V4.1 Flash release.
    # Keep older explicit IDs valid for existing configurations.
    "deepseek": {
        "quick": [
            ("DeepSeek V4.1 Flash - Fast model", "deepseek-flash"),
            ("Custom model ID", "custom"),
        ],
        "deep": [
            ("DeepSeek V4 Pro - Pro tier", "deepseek-v4-pro"),
            ("DeepSeek V4.1 Flash - Fast model", "deepseek-flash"),
            ("DeepSeek V4 Flash - Legacy alias", "deepseek-v4-flash"),
            ("Custom model ID", "custom"),
        ],
    },
    # Qwen: same model IDs across global (dashscope-intl) and China
    # (dashscope) endpoints, so the two provider keys share one model list.
    "qwen": _QWEN_MODELS,
    "qwen-cn": _QWEN_MODELS,
    # GLM: Z.AI (international) and BigModel (China) host the same model
    # IDs; the two provider keys share one model list.
    "glm": _GLM_MODELS,
    "glm-cn": _GLM_MODELS,
    # MiniMax: same model IDs across global (.io) and China (.com) regions,
    # so the two provider keys share one model list.
    "minimax": _MINIMAX_MODELS,
    "minimax-cn": _MINIMAX_MODELS,
    # OpenRouter: fetched dynamically. Azure: any deployed model name.
    # Ollama display labels intentionally omit a "local" marker — the
    # endpoint is now configurable via OLLAMA_BASE_URL, so the same labels
    # apply whether the user runs ollama-serve on localhost or against a
    # remote host. The actual resolved endpoint is surfaced separately by
    # cli.utils.confirm_ollama_endpoint() right after provider selection.
    # "Custom model ID" lets users pick any model they have pulled via
    # `ollama pull` beyond the three suggested defaults.
    "ollama": {
        "quick": [
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("Custom model ID", "custom"),
        ],
        "deep": [
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("Custom model ID", "custom"),
        ],
    },
    # Generic OpenAI-compatible endpoint: the model is whatever the user's
    # server serves, so only "Custom model ID" is offered.
    "openai_compatible": _CUSTOM_ONLY,
    # Hosted OpenAI-compatible providers that serve many (and frequently
    # changing) models — offer "Custom model ID" rather than a list that goes
    # stale. The endpoint + key are wired by the provider; the user picks the
    # model their account has access to.
    "mistral": _CUSTOM_ONLY,
    "kimi": _CUSTOM_ONLY,
    "groq": _CUSTOM_ONLY,
    "nvidia": _CUSTOM_ONLY,
    # Bedrock model IDs / cross-region inference profile IDs are user-specified.
    "bedrock": _CUSTOM_ONLY,
}


def get_model_options(provider: str, mode: str) -> list[ModelOption]:
    """Return shared model options for a provider and selection mode."""
    return MODEL_OPTIONS[provider.lower()][mode]


def get_known_models() -> dict[str, list[str]]:
    """Build known model names from the shared CLI catalog."""
    return {
        provider: sorted(
            {
                value
                for options in mode_options.values()
                for _, value in options
            }
        )
        for provider, mode_options in MODEL_OPTIONS.items()
    }
