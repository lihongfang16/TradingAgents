"""Streamlit analysis input form component."""

import streamlit as st
from datetime import date
from typing import Dict, List, Any


def render_analysis_form() -> Dict[str, Any]:
    """
    Render the analysis input form and return form data.
    
    Returns:
        Dict with keys:
            - symbol (str): Stock symbol
            - date (str): Date in YYYY-MM-DD format
            - source (str): Data source (mairui/ashare/akshare/baostock)
            - exchange (str): Exchange (CN/US/HK)
            - analysts (List[str]): Selected analysts
            - depth (str): Research depth (brief/normal/deep)
            - submitted (bool): Whether form was submitted
    """
    with st.form("analysis_form", clear_on_submit=False):
        st.subheader("分析参数")
        
        # Stock symbol input
        symbol = st.text_input(
            "股票代码",
            value="",
            placeholder="例如: 000001, AAPL, 0700.HK",
            help="输入股票代码，支持A股、港股、美股"
        )
        
        # Date picker
        selected_date = st.date_input(
            "分析日期",
            value=date.today(),
            help="选择要分析的日期"
        )
        
        # Data source selection
        source = st.selectbox(
            "数据源",
            options=["mairui", "ashare", "akshare", "baostock"],
            index=0,
            help="选择金融数据源"
        )
        
        # Exchange selection
        exchange = st.radio(
            "交易所",
            options=["CN", "US", "HK"],
            horizontal=True,
            help="选择股票交易所"
        )
        
        # Analyst checkboxes
        st.markdown("**分析师选择**")
        col1, col2 = st.columns(2)
        with col1:
            analyst_market = st.checkbox("市场分析", value=True)
            analyst_news = st.checkbox("新闻分析", value=True)
        with col2:
            analyst_fundamentals = st.checkbox("基本面分析", value=True)
            analyst_social = st.checkbox("社交情绪", value=True)
        
        analysts: List[str] = []
        if analyst_market:
            analysts.append("market")
        if analyst_news:
            analysts.append("news")
        if analyst_fundamentals:
            analysts.append("fundamentals")
        if analyst_social:
            analysts.append("social")
        
        # Research depth radio
        depth = st.radio(
            "研究深度",
            options=["brief", "normal", "deep"],
            format_func=lambda x: {"brief": "简略", "normal": "普通", "deep": "深度"}[x],
            horizontal=True,
            help="选择研究分析深度"
        )

        # Cache control checkbox
        st.markdown("**缓存控制**")
        force_refresh = st.checkbox(
            "强制刷新",
            value=False,
            help="忽略缓存，重新执行全部分析（会增加LLM调用成本）"
        )

        # Submit button
        submitted = st.form_submit_button("开始分析", use_container_width=True)
        
        # Convert date to string
        date_str = selected_date.strftime("%Y-%m-%d")
        
        return {
            "symbol": symbol.strip() if symbol else "",
            "date": date_str,
            "source": source,
            "exchange": exchange,
            "analysts": analysts,
            "depth": depth,
            "force_refresh": force_refresh,
            "submitted": submitted
        }
