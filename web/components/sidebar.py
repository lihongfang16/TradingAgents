"""Streamlit Sidebar Component for LLM Configuration."""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env file
project_root = Path(__file__).parent.parent.parent
env_file = project_root / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)


def render_sidebar() -> dict:
    """Render LLM configuration sidebar and return config dict.
    
    Returns:
        dict: Configuration with keys:
            - llm_provider: str ("minimax")
            - deep_model: str
            - quick_model: str
            - enable_memory: bool
            - debug_mode: bool
    """
    with st.sidebar:
        st.header("TradingAgents")

        # API Status Section
        st.subheader("API 状态")

        mairui_status = "已配置" if os.getenv("MAIRUI_LICENCE") else "未配置"
        # MiniMax uses OPENAI_API_KEY (OpenAI-compatible API) or MINIMAX_API_KEY
        minimax_status = "已配置" if os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY") else "未配置"

        col1, col2 = st.columns(2)
        with col1:
            st.metric("迈睿UI", mairui_status)
        with col2:
            st.metric("MiniMax", minimax_status)

        st.divider()

        # Model Selection
        st.subheader("模型配置")

        deep_model = st.selectbox(
            "深度分析模型",
            options=["MiniMax-M2.7-highspeed"],
            index=0,
            disabled=True
        )

        quick_model = st.selectbox(
            "快速响应模型",
            options=["MiniMax-M2.7-highspeed"],
            index=0,
            disabled=True
        )

        st.divider()

        # Advanced Settings
        st.subheader("高级设置")

        enable_memory = st.toggle(
            "启用记忆功能",
            value=False,
            help="开启后将在对话中保留历史上下文"
        )

        debug_mode = st.toggle(
            "调试模式",
            value=False,
            help="开启后将显示详细日志信息"
        )

    return {
        "llm_provider": "minimax",
        "deep_model": deep_model,
        "quick_model": quick_model,
        "enable_memory": enable_memory,
        "debug_mode": debug_mode,
    }
