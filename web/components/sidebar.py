"""Streamlit Sidebar Component for LLM Configuration."""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

# Load environment variables from .env file
project_root = Path(__file__).parent.parent.parent
env_file = project_root / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)

# Provider display names and API key env vars
_PROVIDER_INFO = {
    "minimax":  ("MiniMax (Moonshot)", "MINIMAX_API_KEY", "OPENAI_API_KEY"),
    "kimi":     ("Kimi (Moonshot)",    "MOONSHOT_API_KEY", "KIMI_API_KEY"),
    "openai":   ("OpenAI (GPT)",       "OPENAI_API_KEY"),
    "anthropic":("Anthropic (Claude)", "ANTHROPIC_API_KEY"),
    "google":   ("Google (Gemini)",    "GOOGLE_API_KEY"),
    "xai":      ("xAI (Grok)",         "XAI_API_KEY"),
    "openrouter":("OpenRouter",        "OPENROUTER_API_KEY"),
    "ollama":   ("Ollama (本地)",       None),
}


def _is_provider_configured(provider: str) -> bool:
    """Check whether the given provider has at least one API key set."""
    info = _PROVIDER_INFO.get(provider)
    if not info:
        return False
    env_vars = info[1:]  # everything after the display name
    if env_vars[0] is None:
        return True  # Ollama — always "configured" (local)
    return any(os.getenv(v) for v in env_vars)


def render_sidebar() -> dict:
    """Render LLM configuration sidebar and return config dict.

    Returns:
        dict: Configuration with keys:
            - llm_provider: str
            - deep_model: str
            - quick_model: str
            - enable_memory: bool
            - debug_mode: bool
    """
    with st.sidebar:
        st.header("TradingAgents")

        # ── API Status Section ──────────────────────────────────────
        st.subheader("API 状态")

        configured = [
            (info[0], provider)
            for provider, info in _PROVIDER_INFO.items()
            if _is_provider_configured(provider)
        ]

        # Show up to 4 metrics in a 2×2 grid
        cols = st.columns(min(len(configured), 4)) if configured else st.columns(2)
        for idx, (display_name, _) in enumerate(configured[:4]):
            with cols[idx % len(cols)]:
                st.metric(display_name, "✅ 已配置")

        if not configured:
            st.warning("未检测到任何 LLM API Key，请在 .env 中配置")

        st.divider()

        # ── Provider Selection ──────────────────────────────────────
        st.subheader("模型配置")

        # Build provider list (show configured first, then unconfigured)
        available_providers = list(_PROVIDER_INFO.keys())
        provider_labels = [
            f"{_PROVIDER_INFO[p][0]} {'✅' if _is_provider_configured(p) else '⚠️'}"
            for p in available_providers
        ]

        selected_provider_idx = st.selectbox(
            "LLM 提供商",
            options=range(len(available_providers)),
            format_func=lambda i: provider_labels[i],
            index=0,
            help="选择 LLM 提供商（✅ 已配置API Key / ⚠️ 未配置）",
        )
        llm_provider = available_providers[selected_provider_idx]

        # ── Model Selection (dynamic based on provider) ─────────────
        # Resolve catalog key: minimax → lookup in MODEL_OPTIONS under "openai"
        # because minimax uses OpenAI-compatible routing in the factory.
        catalog_key = llm_provider
        if llm_provider == "minimax":
            catalog_key = "openai"  # MiniMax models listed under openai in catalog

        model_options = MODEL_OPTIONS.get(catalog_key, {})

        deep_options = model_options.get("deep", [])
        quick_options = model_options.get("quick", [])

        # Fallback: if no catalog entries, allow free-form input
        if deep_options:
            deep_labels = [label for label, _ in deep_options]
            deep_values = [value for _, value in deep_options]
            deep_idx = st.selectbox(
                "深度分析模型",
                options=range(len(deep_options)),
                format_func=lambda i: deep_labels[i],
                index=0,
                help="用于深度推理的模型（研究员、投资经理等）",
            )
            deep_model = deep_values[deep_idx]
        else:
            deep_model = st.text_input(
                "深度分析模型",
                value="",
                placeholder="输入模型名称",
            )

        if quick_options:
            quick_labels = [label for label, _ in quick_options]
            quick_values = [value for _, value in quick_options]
            quick_idx = st.selectbox(
                "快速响应模型",
                options=range(len(quick_options)),
                format_func=lambda i: quick_labels[i],
                index=0,
                help="用于快速任务的模型（分析师、交易员等）",
            )
            quick_model = quick_values[quick_idx]
        else:
            quick_model = st.text_input(
                "快速响应模型",
                value="",
                placeholder="输入模型名称",
            )

        # For MiniMax, hardcode the model since catalog uses openai entries
        if llm_provider == "minimax":
            deep_model = "MiniMax-M2.7-highspeed"
            quick_model = "MiniMax-M2.7-highspeed"

        st.divider()

        # ── Advanced Settings ───────────────────────────────────────
        st.subheader("高级设置")

        enable_memory = st.toggle(
            "启用记忆功能",
            value=False,
            help="开启后将在对话中保留历史上下文",
        )

        debug_mode = st.toggle(
            "调试模式",
            value=False,
            help="开启后将显示详细日志信息",
        )

    return {
        "llm_provider": llm_provider,
        "deep_model": deep_model,
        "quick_model": quick_model,
        "enable_memory": enable_memory,
        "debug_mode": debug_mode,
    }
