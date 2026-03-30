"""Watchlist Manager Component for TradingAgents Web UI."""
import json
import os
import sys
import traceback
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import streamlit as st


# API URL - use same default as app.py
API_URL = os.environ.get("API_URL", "http://localhost:8000")


def get_stock_intraday_data(symbol: str) -> Optional[pd.DataFrame]:
    """Get intraday price data for a stock.

    Args:
        symbol: 6-digit stock code (e.g. '000001')

    Returns:
        DataFrame with DatetimeIndex and OHLCV columns
        (open, high, low, close, volume), or None if unavailable.
        Filters out non-trading periods (weekends, holidays) where volume=0.
    """
    try:
        from tradingagents.dataflows.ashare_provider import AshareProvider
        provider = AshareProvider()

        # Try to get intraday kline data first
        df = provider.get_kline(symbol, period="1m", limit=240)

        if df is not None and not df.empty:
            # Filter out non-trading periods (volume=0) to remove weekends/holidays
            df = df[df['volume'] > 0]
            if not df.empty:
                return df

        # Fallback to realtime quote if kline fails
        quote = provider.get_realtime_quote(symbol)
        if quote is not None and quote.get('price') is not None:
            price = float(quote['price'])
            return pd.DataFrame(
                {
                    'open': [price],
                    'high': [price],
                    'low': [price],
                    'close': [price],
                    'volume': [0],
                },
                index=pd.DatetimeIndex([datetime.now()])
            )

        return None
    except Exception:
        return None


def render_candlestick_chart(df: pd.DataFrame, title: str = "", height: int = 300):
    """Render a candlestick chart using Plotly.

    Args:
        df: DataFrame with DatetimeIndex and open/high/low/close/volume columns
        title: Chart title
        height: Chart height in pixels
    """
    import plotly.graph_objects as go

    # Use category type x-axis to remove time gaps between trading days
    # Format labels as "MM/DD HH:MM" for multi-day or "HH:MM" for single day
    if len(df) > 0:
        time_diff = df.index[-1] - df.index[0]
        if time_diff.days <= 1:
            # Single day: show time only
            x_labels = df.index.strftime('%H:%M')
        else:
            # Multi-day: show date and time
            x_labels = df.index.strftime('%m/%d %H:%M')
    else:
        x_labels = df.index

    fig = go.Figure(data=[go.Candlestick(
        x=list(range(len(df))),  # Use index positions as x
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        increasing_line_color='#ef5350',  # A-share red = up
        decreasing_line_color='#26a69a',  # A-share green = down
    )])

    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=40, r=10, t=30 if title else 5, b=30),
        xaxis_rangeslider_visible=False,
        xaxis_showgrid=True,
        yaxis_showgrid=True,
        yaxis_fixedrange=True,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(size=11),
        xaxis_tickfont=dict(size=9),
        yaxis_tickfont=dict(size=9),
    )

    # Set x-axis as category type with formatted labels
    fig.update_xaxes(
        type='category',
        tickmode='auto',
        nticks=6,  # Show ~6 time labels to avoid crowding
        ticktext=x_labels[::max(1, len(x_labels)//6)],
        tickvals=list(range(0, len(df), max(1, len(df)//6))),
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            'displayModeBar': False,       # hide toolbar for cleaner look
            'scrollZoom': False,
            'staticPlot': False,
            'responsive': True,
        },
    )


def format_signal(signal: str, confidence: float) -> str:
    """Format AI signal with emoji and color."""
    if signal is None or confidence is None:
        return "⚪--(--%)"
    emoji_map = {'BUY': '🟢', 'SELL': '🔴', 'HOLD': '🟡', 'UNKNOWN': '⚪'}
    emoji = emoji_map.get(signal, '⚪')
    return f"{emoji}{signal}({confidence:.0%})"


def get_signal_color(signal: str) -> str:
    """Get color for signal."""
    color_map = {
        'BUY': '#4CAF50',
        'SELL': '#F44336',
        'HOLD': '#FF9800',
        'UNKNOWN': '#9E9E9E'
    }
    return color_map.get(signal, '#9E9E9E')


def get_next_analysis_text(is_high_freq: bool, high_freq_until: Optional[datetime]) -> str:
    """Get next analysis countdown text."""
    if is_high_freq and high_freq_until:
        remaining = high_freq_until - datetime.utcnow()
        if remaining.total_seconds() > 0:
            minutes = int(remaining.total_seconds() / 60)
            return f"⚡变盘 ({minutes}分钟)"
    return "⏱️5分钟"


def format_turning_alert(alert: dict) -> str:
    """Format turning signal for display."""
    importance = alert.get('importance_score', 0)
    importance_emoji = '🔥' if importance > 0.9 else '⚡' if importance > 0.7 else '📊'
    time_str = alert.get('time', 'Unknown')
    symbol = alert.get('symbol', 'Unknown')
    reason = alert.get('reason', '')
    return f"{importance_emoji} {time_str} {symbol} {reason}"


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human readable string."""
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}分{secs}秒"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}小时{mins}分"


def load_watchlist() -> List[Dict[str, Any]]:
    """Load watchlist from API."""
    try:
        resp = requests.get(f"{API_URL}/api/v1/watchlist/", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
    return []


def add_watchlist_stock(symbol: str, name: str = "", exchange: str = "CN") -> Optional[Dict]:
    """Add a stock to watchlist."""
    try:
        payload = {
            "symbol": symbol,
            "name": name,
            "exchange": exchange
        }
        resp = requests.post(
            f"{API_URL}/api/v1/watchlist/",
            json=payload,
            timeout=5
        )
        if resp.status_code == 201:
            return resp.json()
        elif resp.status_code == 400:
            st.error(f"添加失败: {resp.json().get('detail', '股票已存在或参数错误')}")
        else:
            st.error(f"添加失败: HTTP {resp.status_code}")
    except Exception as e:
        st.error(f"添加失败: {str(e)}")
        traceback.print_exc(file=sys.stderr)
    return None


def delete_watchlist_stock(stock_id: int) -> bool:
    """Delete a stock from watchlist."""
    try:
        resp = requests.delete(f"{API_URL}/api/v1/watchlist/{stock_id}", timeout=5)
        if resp.status_code == 204:
            return True
        elif resp.status_code == 404:
            st.error("股票不存在")
        else:
            st.error(f"删除失败: HTTP {resp.status_code}")
    except Exception as e:
        st.error(f"删除失败: {str(e)}")
        traceback.print_exc(file=sys.stderr)
    return False


def trigger_quick_analysis(stock_id: int) -> Optional[Dict]:
    """Trigger quick analysis for a stock."""
    try:
        resp = requests.post(
            f"{API_URL}/api/v1/watchlist/{stock_id}/quick-analyze",
            timeout=5
        )
        if resp.status_code == 202 or resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"分析触发失败: HTTP {resp.status_code}")
    except Exception as e:
        st.error(f"分析触发失败: {str(e)}")
        traceback.print_exc(file=sys.stderr)
    return None


def get_turning_alerts(limit: int = 20) -> List[Dict]:
    """Get turning signal alerts."""
    try:
        resp = requests.get(
            f"{API_URL}/api/v1/watchlist/alerts",
            params={"limit": limit},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
    return []


def get_scheduler_status() -> Optional[Dict]:
    """Get scheduler status."""
    try:
        resp = requests.get(f"{API_URL}/api/v1/scheduler/status", timeout=3)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def initialize_monitoring_state() -> None:
    """Initialize monitoring state from API on page load."""
    try:
        resp = requests.get(
            f"{API_URL}/api/v1/watchlist/monitoring/state",
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.monitoring_active = data.get('is_active', False)
        else:
            # Default to False if API returns error
            st.session_state.monitoring_active = False
    except Exception as e:
        # On error, keep existing state or default to False
        if 'monitoring_active' not in st.session_state:
            st.session_state.monitoring_active = False


def start_monitoring() -> bool:
    """Start monitoring via API.

    Returns:
        True if successful, False otherwise.
    """
    try:
        resp = requests.post(
            f"{API_URL}/api/v1/watchlist/monitoring/start",
            timeout=5
        )
        if resp.status_code == 200:
            return True
        else:
            error_detail = resp.json().get('detail', f'HTTP {resp.status_code}')
            st.error(f"启动监控失败: {error_detail}")
            return False
    except Exception as e:
        st.error(f"启动监控失败: {str(e)}")
        return False


def stop_monitoring() -> bool:
    """Stop monitoring via API.

    Returns:
        True if successful, False otherwise.
    """
    try:
        resp = requests.post(
            f"{API_URL}/api/v1/watchlist/monitoring/stop",
            timeout=5
        )
        if resp.status_code == 200:
            return True
        else:
            error_detail = resp.json().get('detail', f'HTTP {resp.status_code}')
            st.error(f"停止监控失败: {error_detail}")
            return False
    except Exception as e:
        st.error(f"停止监控失败: {str(e)}")
        return False


def resolve_stock_name(symbol: str) -> str:
    """Resolve A-share stock code to name via Tencent real-time API.
    
    Args:
        symbol: 6-digit stock code (e.g. '000001')
    
    Returns:
        Stock name (e.g. '平安银行') or empty string if not found.
    """
    try:
        from tradingagents.dataflows.ashare_provider import AshareProvider
        provider = AshareProvider()
        quote = provider.get_realtime_quote(symbol)
        if quote and quote.get("name"):
            return quote["name"]
    except Exception:
        pass
    return ""


def render_add_stock_section():
    """Render search and add stock section."""
    st.subheader("🔍 添加自选股")
    
    # Inject CSS once at the top (outside columns to avoid extra containers)
    st.markdown(
        """<style>
        /* Remove margin from button container */
        div[data-testid="stHorizontalBlock"] div[data-testid="column"]:nth-child(3) .stButton {
            margin-top: 0 !important;
        }
        div[data-testid="stHorizontalBlock"] div[data-testid="column"]:nth-child(3) .stButton > button {
            height: 38px !important;
            min-height: 38px !important;
            max-height: 38px !important;
            line-height: 1 !important;
            padding: 0 1rem !important;
        }
        /* Style for resolved name display */
        .resolved-name-box {
            padding: 0.5rem 0.75rem;
            border: 1px solid #d1d5db;
            border-radius: 0.375rem;
            background: #f0fdf4;
            color: #166534;
            font-size: 0.875rem;
            line-height: 1.25;
            height: 38px;
            display: flex;
            align-items: center;
            box-sizing: border-box;
            margin: 0;
        }
        </style>""",
        unsafe_allow_html=True
    )
    
    col1, col2, col3 = st.columns([3, 2, 1])

    with col1:
        search_symbol = st.text_input(
            label="股票代码",
            placeholder="输入股票代码 (如: 000001)",
            key="watchlist_search",
            label_visibility="collapsed"
        )
    
    # Auto-resolve name when symbol is entered (6-digit A-share code)
    resolved_name = ""
    if search_symbol and len(search_symbol.strip()) == 6 and search_symbol.strip().isdigit():
        cache_key = f"_resolved_name_{search_symbol.strip()}"
        if cache_key not in st.session_state:
            with st.spinner("正在查询股票名称..."):
                name = resolve_stock_name(search_symbol.strip())
                if name:
                    st.session_state[cache_key] = name
        resolved_name = st.session_state.get(cache_key, "")
    
    with col2:
        if resolved_name:
            # Show resolved name as read-only styled box - single markdown call
            st.markdown(
                f'<div class="resolved-name-box">✅ {resolved_name}</div>',
                unsafe_allow_html=True
            )
        else:
            st.text_input(
                label="股票名称",
                placeholder="可选: 手动输入名称",
                key="watchlist_name",
                label_visibility="collapsed"
            )
        # Determine the final name: resolved > user input
        user_input_name = st.session_state.get("watchlist_name", "")
        final_name = resolved_name if resolved_name else user_input_name
    
    with col3:
        # Simple button without wrapper divs
        button_clicked = st.button(
            "➕ 添加",
            use_container_width=True,
            type="primary",
            key="add_watchlist_btn"
        )
        if button_clicked:
            if search_symbol:
                # If not yet resolved, try one last time
                if not final_name and len(search_symbol.strip()) == 6 and search_symbol.strip().isdigit():
                    final_name = resolve_stock_name(search_symbol.strip())
                result = add_watchlist_stock(search_symbol.upper(), final_name)
                if result:
                    display = f"{result.get('symbol', search_symbol)} {final_name}" if final_name else result.get('symbol', search_symbol)
                    st.success(f"已添加: {display}")
                    st.session_state.watchlist_data = load_watchlist()
                    # Clear caches
                    cache_key = f"_resolved_name_{search_symbol.strip()}"
                    st.session_state.pop(cache_key, None)
                    st.session_state.pop("watchlist_name", None)
                    st.session_state.pop("watchlist_search", None)
                    time.sleep(0.5)
                    st.rerun()
            else:
                st.warning("请输入股票代码")


def render_watchlist_table():
    """Render watchlist table with AI signals."""
    st.subheader("📋 自选股列表")
    st.caption("每5分钟AI分析，变盘时2分钟高频")
    
    # Load watchlist data
    if 'watchlist_data' not in st.session_state:
        st.session_state.watchlist_data = load_watchlist()
    
    watchlist = st.session_state.watchlist_data
    
    if not watchlist:
        st.info("暂无自选股，请添加股票开始监控")
        return
    
    # Table header
    header_cols = st.columns([1.2, 1.5, 1, 1, 2, 1.5, 1, 1, 1.2])
    with header_cols[0]:
        st.write("**代码**")
    with header_cols[1]:
        st.write("**名称**")
    with header_cols[2]:
        st.write("**价格**")
    with header_cols[3]:
        st.write("**涨跌**")
    with header_cols[4]:
        st.write("**AI信号**")
    with header_cols[5]:
        st.write("**下次分析**")
    with header_cols[6]:
        st.write("**查看**")
    with header_cols[7]:
        st.write("**分析**")
    with header_cols[8]:
        st.write("**管理**")
    
    st.divider()
    
    # Table rows
    for item in watchlist:
        stock_id = item.get('id', 0)
        symbol = item.get('symbol', 'Unknown')
        name = item.get('name', symbol)
        
        # Price data
        last_price = item.get('last_price', 0)
        last_change_pct = item.get('last_change_pct', 0)
        
        # AI signal data
        last_signal = item.get('last_signal', 'UNKNOWN')
        last_confidence = item.get('last_confidence', 0)
        
        # High frequency status
        is_high_freq = item.get('is_high_frequency', False)
        high_freq_until_str = item.get('high_freq_until')
        high_freq_until = None
        if high_freq_until_str:
            try:
                high_freq_until = datetime.fromisoformat(high_freq_until_str.replace('Z', '+00:00')).replace(tzinfo=None)
            except:
                pass
        
        # Determine row highlighting
        is_turning = is_high_freq and high_freq_until and high_freq_until > datetime.utcnow()
        importance_high = last_confidence is not None and last_confidence > 0.9 and last_signal in ['BUY', 'SELL']
        
        # Row container with optional highlighting
        if is_turning or importance_high:
            st.markdown(
                """
                <div style="background-color: rgba(255, 193, 7, 0.1); 
                            border-left: 3px solid #FFC107; 
                            padding: 8px; 
                            margin: 4px 0;
                            border-radius: 4px;">
                """,
                unsafe_allow_html=True
            )
        
        row_cols = st.columns([1.2, 1.5, 1, 1, 2, 1.5, 1, 1, 1.2])
        
        with row_cols[0]:
            st.write(f"**{symbol}**")
        
        with row_cols[1]:
            display_name = name if name else symbol
            st.write(display_name[:8] + "..." if len(display_name) > 8 else display_name)
            if is_turning:
                st.caption("🔥")
        
        with row_cols[2]:
            if last_price:
                st.write(f"¥{last_price:.2f}")
            else:
                st.caption("--")
        
        with row_cols[3]:
            if last_change_pct:
                color = "#4CAF50" if last_change_pct > 0 else "#F44336" if last_change_pct < 0 else "#9E9E9E"
                sign = "+" if last_change_pct > 0 else ""
                st.markdown(f"<span style='color: {color}'>{sign}{last_change_pct:.1f}%</span>", unsafe_allow_html=True)
            else:
                st.caption("--")
        
        with row_cols[4]:
            signal_color = get_signal_color(last_signal)
            signal_text = format_signal(last_signal, last_confidence)
            st.markdown(f"<span style='color: {signal_color}; font-weight: bold;'>{signal_text}</span>", unsafe_allow_html=True)
        
        with row_cols[5]:
            next_analysis = get_next_analysis_text(is_high_freq, high_freq_until)
            st.write(next_analysis)
        
        with row_cols[6]:
            if st.button("👁️", key=f"view_stock_{stock_id}", help="查看详情"):
                st.session_state.selected_stock = item
                st.session_state.show_stock_detail = True
        
        with row_cols[7]:
            if st.button("🔄", key=f"analyze_stock_{stock_id}", help="立即分析"):
                with st.spinner("启动分析..."):
                    result = trigger_quick_analysis(stock_id)
                    if result:
                        st.success(f"分析已启动: {result.get('analysis_id', 'N/A')[:8]}...")
                        time.sleep(1)
                        st.rerun()
        
        with row_cols[8]:
            # Management buttons
            mgmt_cols = st.columns(2)
            with mgmt_cols[0]:
                if st.button("⚙️", key=f"settings_stock_{stock_id}", help="设置"):
                    st.session_state.selected_stock = item
                    st.session_state.show_stock_settings = True
            with mgmt_cols[1]:
                # Use a unique key for each delete button confirmation
                confirm_key = f"confirm_delete_{stock_id}"
                if confirm_key not in st.session_state:
                    st.session_state[confirm_key] = False
                
                if not st.session_state[confirm_key]:
                    if st.button("🗑️", key=f"delete_stock_{stock_id}", help="点击删除"):
                        st.session_state[confirm_key] = True
                        st.rerun()
                else:
                    st.warning(f"确定删除 {symbol}?")
                    col_yes, col_no = st.columns(2)
                    with col_yes:
                        if st.button("✅ 确定", key=f"confirm_yes_{stock_id}"):
                            if delete_watchlist_stock(stock_id):
                                st.session_state[confirm_key] = False
                                st.toast(f"✅ 已删除 {symbol}", icon="🗑️")
                                # Refresh immediately after successful deletion
                                st.rerun()
                    with col_no:
                        if st.button("❌ 取消", key=f"confirm_no_{stock_id}"):
                            st.session_state[confirm_key] = False
                            st.rerun()
        
        if is_turning or importance_high:
            st.markdown("</div>", unsafe_allow_html=True)
        
        st.divider()


def render_control_buttons():
    """Render control buttons for monitoring."""
    st.subheader("🎛️ 监控控制")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

    # Initialize monitoring state from API on page load
    if 'monitoring_state_initialized' not in st.session_state:
        initialize_monitoring_state()
        st.session_state.monitoring_state_initialized = True

    with col1:
        if not st.session_state.monitoring_active:
            if st.button("▶️ 开始监控", use_container_width=True, type="primary"):
                if start_monitoring():
                    st.session_state.monitoring_active = True
                    st.success("监控已启动")
                    time.sleep(0.5)
                    st.rerun()
        else:
            if st.button("⏸️ 暂停监控", use_container_width=True):
                if stop_monitoring():
                    st.session_state.monitoring_active = False
                    st.warning("监控已暂停")
                    time.sleep(0.5)
                    st.rerun()
    
    with col2:
        if st.button("🔄 立即分析全部", use_container_width=True):
            watchlist = st.session_state.get('watchlist_data', [])
            if watchlist:
                progress_text = st.empty()
                progress_bar = st.progress(0)
                for i, item in enumerate(watchlist):
                    stock_id = item.get('id', 0)
                    symbol = item.get('symbol', 'Unknown')
                    progress_text.write(f"分析中: {symbol}...")
                    trigger_quick_analysis(stock_id)
                    progress_bar.progress((i + 1) / len(watchlist))
                    time.sleep(0.2)  # Small delay between requests
                progress_text.empty()
                progress_bar.empty()
                st.success(f"已启动 {len(watchlist)} 个分析任务")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("自选股列表为空")
    
    with col3:
        if st.button("🔄 刷新列表", use_container_width=True):
            st.session_state.watchlist_data = load_watchlist()
            st.rerun()
    
    with col4:
        # Auto-refresh toggle
        if 'auto_refresh' not in st.session_state:
            st.session_state.auto_refresh = True
        
        auto_refresh = st.checkbox(
            "🔄 自动刷新",
            value=st.session_state.auto_refresh,
            key="auto_refresh_toggle"
        )
        st.session_state.auto_refresh = auto_refresh
        
        # Show scheduler status
        scheduler_status = get_scheduler_status()
        if scheduler_status:
            status_emoji = "🟢" if scheduler_status.get('status') == 'running' else "🔴"
            st.caption(f"{status_emoji} 调度器: {scheduler_status.get('status', 'unknown')}")


def render_monitoring_panel():
    """Render real-time monitoring panel."""
    st.subheader("📈 实时监控面板")
    st.caption("价格走势与AI信号关联")
    
    watchlist = st.session_state.get('watchlist_data', [])
    
    if not watchlist:
        st.info("添加股票以查看实时面板")
        return

    # Initialize session state for multi-select
    if 'monitoring_selected_stocks' not in st.session_state:
        # Select first 4 stocks by default
        st.session_state.monitoring_selected_stocks = [
            item['id'] for item in watchlist[:4]
        ]

    # Multi-stock charts section
    st.subheader("📊 多股价格对比")
    selected_ids = st.session_state.monitoring_selected_stocks

    # Filter watchlist to get selected stocks
    selected_stocks = [item for item in watchlist if item['id'] in selected_ids]

    # Display charts in rows of 2 (larger charts = better resolution)
    for i in range(0, len(selected_stocks), 2):
        row_stocks = selected_stocks[i:i+2]
        cols = st.columns(2)
        for idx, stock in enumerate(row_stocks):
            with cols[idx]:
                symbol = stock['symbol']
                name = stock.get('name', symbol)
                st.write(f"**{symbol} {name}**")

                # Fetch and display chart
                df = get_stock_intraday_data(symbol)
                if df is not None and not df.empty:
                    render_candlestick_chart(df, height=350)
                else:
                    st.caption("暂无数据")

    st.divider()

    # Stock selector for detail view
    stock_options = {f"{item.get('symbol', 'Unknown')} - {item.get('name', '')}": item for item in watchlist}
    selected_key = st.selectbox(
        "选择股票查看详情",
        options=list(stock_options.keys()),
        key="monitoring_stock_selector"
    )
    
    if selected_key:
        selected_item = stock_options[selected_key]
        symbol = selected_item.get('symbol', 'Unknown')
        name = selected_item.get('name', symbol)
        
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            last_price = selected_item.get('last_price', 0)
            if last_price:
                st.metric("当前价格", f"¥{last_price:.2f}")
            else:
                st.metric("当前价格", "--")
        
        with col2:
            last_change_pct = selected_item.get('last_change_pct', 0)
            if last_change_pct:
                st.metric("涨跌幅", f"{last_change_pct:+.2f}%", delta=f"{last_change_pct:+.2f}%")
            else:
                st.metric("涨跌幅", "--")
        
        with col3:
            last_signal = selected_item.get('last_signal', 'UNKNOWN')
            last_confidence = selected_item.get('last_confidence', 0)
            signal_color = get_signal_color(last_signal)
            st.markdown(f"**AI信号**")
            st.markdown(f"<span style='color: {signal_color}; font-size: 1.2em; font-weight: bold;'>{format_signal(last_signal, last_confidence)}</span>", unsafe_allow_html=True)
        
        with col4:
            last_analysis_at = selected_item.get('last_analysis_at')
            if last_analysis_at:
                try:
                    dt = datetime.fromisoformat(last_analysis_at.replace('Z', '+00:00'))
                    time_str = dt.strftime("%H:%M")
                    st.metric("最后分析", time_str)
                except:
                    st.metric("最后分析", "--")
            else:
                st.metric("最后分析", "--")
        
        # Price trend - real K-line chart
        st.write("**价格走势**")

        detail_df = get_stock_intraday_data(symbol)
        if detail_df is not None and not detail_df.empty:
            render_candlestick_chart(detail_df, title=f"{symbol} {name} 分时K线", height=400)
        else:
            st.caption("暂无价格数据")

        # AI signal timeline
        last_signal = selected_item.get('last_signal', 'UNKNOWN')
        last_confidence = selected_item.get('last_confidence', 0)
        if last_signal != 'UNKNOWN':
            st.write("**AI信号时间线**")
            signal_color = get_signal_color(last_signal)
            signal_text = format_signal(last_signal, last_confidence)
            st.markdown(f"<span style='color: {signal_color}; font-size: 1.5em; font-weight: bold;'>{signal_text}</span>", unsafe_allow_html=True)
        else:
            st.caption("尚无AI信号，请先运行分析")

    # Checkbox selection area
    st.divider()
    st.subheader("📋 选择要显示的股票")

    # Create checkbox grid (6 columns)
    checkbox_cols = st.columns(6)
    for idx, item in enumerate(watchlist):
        col_idx = idx % 6
        with checkbox_cols[col_idx]:
            is_checked = item['id'] in st.session_state.monitoring_selected_stocks
            checkbox_key = f"monitor_select_{item['id']}"

            # Let st.checkbox manage its own session state via key+value
            # Do NOT pre-set st.session_state[checkbox_key] — that causes
            # "created with a default value but also had its value set via Session State API"
            new_state = st.checkbox(
                f"{item['symbol']} {item.get('name', '')}",
                value=is_checked,
                key=checkbox_key
            )

            # Sync monitoring_selected_stocks based on checkbox result
            if new_state and item['id'] not in st.session_state.monitoring_selected_stocks:
                st.session_state.monitoring_selected_stocks.append(item['id'])
            elif not new_state and item['id'] in st.session_state.monitoring_selected_stocks:
                st.session_state.monitoring_selected_stocks.remove(item['id'])


def render_turning_history():
    """Render turning signal history."""
    st.subheader("🔔 变盘信号历史")
    st.caption("基于AI分析结果对比")
    
    # Load alerts
    if 'turning_alerts' not in st.session_state or st.session_state.get('refresh_alerts', False):
        st.session_state.turning_alerts = get_turning_alerts(limit=20)
        st.session_state.refresh_alerts = False
    
    alerts = st.session_state.turning_alerts
    
    if not alerts:
        st.info("暂无变盘信号记录")
        return
    
    # Display alerts in a list format
    for alert in alerts[:10]:  # Show top 10
        importance = alert.get('importance_score', 0)
        importance_emoji = '🔥' if importance > 0.9 else '⚡' if importance > 0.7 else '📊'
        
        alert_time = alert.get('time', 'Unknown')
        symbol = alert.get('symbol', 'Unknown')
        name = alert.get('name', symbol)
        reason = alert.get('reason', '信号变化')
        confidence = alert.get('confidence', 0)
        
        # Color based on importance
        bg_color = "rgba(255, 82, 82, 0.1)" if importance > 0.9 else "rgba(255, 193, 7, 0.1)" if importance > 0.7 else "transparent"
        
        st.markdown(
            f"""
            <div style="background-color: {bg_color}; 
                        padding: 10px; 
                        margin: 4px 0;
                        border-radius: 4px;
                        border-left: 3px solid {'#FF5252' if importance > 0.9 else '#FFC107' if importance > 0.7 else '#9E9E9E'};">
                <strong>{importance_emoji} {alert_time}</strong> 
                <span style="font-weight: bold;">{name} ({symbol})</span><br/>
                <span style="color: #666;">{reason}</span>
                {f'<br/><span style="color: #888; font-size: 0.9em;">置信度: {confidence:.0%}</span>' if confidence else ''}
            </div>
            """,
            unsafe_allow_html=True
        )
    
    if len(alerts) > 10:
        st.caption(f"还有 {len(alerts) - 10} 条历史记录...")


def render_stock_detail_modal():
    """Render stock detail modal (using expander)."""
    if st.session_state.get('show_stock_detail') and st.session_state.get('selected_stock'):
        item = st.session_state.selected_stock
        
        with st.expander(f"📊 {item.get('symbol', 'Unknown')} 详情", expanded=True):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.write("**基本信息**")
                st.write(f"代码: {item.get('symbol', 'N/A')}")
                st.write(f"名称: {item.get('name', 'N/A')}")
                st.write(f"交易所: {item.get('exchange', 'N/A')}")
            
            with col2:
                st.write("**当前状态**")
                last_price = item.get('last_price', 0)
                last_change_pct = item.get('last_change_pct', 0)
                if last_price:
                    st.write(f"价格: ¥{last_price:.2f}")
                if last_change_pct:
                    st.write(f"涨跌: {last_change_pct:+.2f}%")
                
                last_signal = item.get('last_signal', 'UNKNOWN')
                last_confidence = item.get('last_confidence', 0)
                st.write(f"信号: {format_signal(last_signal, last_confidence)}")
            
            with col3:
                st.write("**监控状态**")
                is_active = item.get('is_active', True)
                is_high_freq = item.get('is_high_frequency', False)
                st.write(f"监控: {'✅ 启用' if is_active else '❌ 禁用'}")
                st.write(f"高频: {'⚡ 是' if is_high_freq else '⏱️ 否'}")
                
                turning_enabled = item.get('turning_detection_enabled', True)
                st.write(f"变盘检测: {'✅' if turning_enabled else '❌'}")
            
            # Analysis history placeholder
            st.write("**分析历史**")
            st.info("分析历史功能开发中...")
            
            if st.button("关闭", key="close_detail"):
                st.session_state.show_stock_detail = False
                st.session_state.selected_stock = None
                st.rerun()


def render_stock_settings_modal():
    """Render stock settings modal."""
    if st.session_state.get('show_stock_settings') and st.session_state.get('selected_stock'):
        item = st.session_state.selected_stock
        stock_id = item.get('id', 0)
        
        with st.expander(f"⚙️ {item.get('symbol', 'Unknown')} 设置", expanded=True):
            st.write("**监控设置**")
            
            # Toggle active state
            is_active = st.checkbox(
                "启用监控",
                value=item.get('is_active', True),
                key=f"setting_active_{stock_id}"
            )
            
            # Toggle turning detection
            turning_enabled = st.checkbox(
                "启用变盘检测",
                value=item.get('turning_detection_enabled', True),
                key=f"setting_turning_{stock_id}"
            )
            
            # Confidence jump threshold
            current_threshold = item.get('confidence_jump_threshold', 0.15)
            threshold = st.slider(
                "置信度突破阈值",
                min_value=0.05,
                max_value=0.30,
                value=float(current_threshold),
                step=0.01,
                key=f"setting_threshold_{stock_id}"
            )
            
            st.caption(f"当前阈值: {threshold:.0%} (当置信度变化超过此值时触发变盘信号)")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("保存设置", key=f"save_settings_{stock_id}"):
                    # Update via API
                    try:
                        resp = requests.put(
                            f"{API_URL}/api/v1/watchlist/{stock_id}",
                            json={
                                'is_active': is_active,
                                'turning_detection_enabled': turning_enabled,
                                'confidence_jump_threshold': threshold
                            },
                            timeout=5
                        )
                        if resp.status_code == 200:
                            st.success("设置已保存")
                            st.session_state.show_stock_settings = False
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(f"保存失败: HTTP {resp.status_code}")
                    except Exception as e:
                        st.error(f"保存失败: {str(e)}")
            
            with col2:
                if st.button("取消", key=f"cancel_settings_{stock_id}"):
                    st.session_state.show_stock_settings = False
                    st.rerun()


def render_watchlist_manager():
    """Main entry point for watchlist management page."""
    try:
        st.title("📊 自选股实时监控")
        st.caption("AI驱动变盘检测")
        
        st.divider()
        
        # Search and add section
        render_add_stock_section()
        
        st.divider()
        
        # Watchlist table
        render_watchlist_table()
        
        st.divider()
        
        # Control buttons
        render_control_buttons()
        
        st.divider()
        
        # Real-time monitoring panel
        render_monitoring_panel()
        
        st.divider()
        
        # Turning signal history
        render_turning_history()
        
        # Stock detail modal (if active)
        if st.session_state.get('show_stock_detail'):
            render_stock_detail_modal()
        
        # Stock settings modal (if active)
        if st.session_state.get('show_stock_settings'):
            render_stock_settings_modal()
        
        # Auto-refresh logic - only refresh data, not full page reload
        if st.session_state.get('auto_refresh', True):
            # Use a shorter delay and incremental refresh
            time.sleep(10)  # Refresh every 10 seconds (was 5)
            st.session_state.refresh_alerts = True
            # Only reload watchlist data, not full rerun if possible
            watchlist_data = load_watchlist()
            if watchlist_data != st.session_state.get('watchlist_data', []):
                st.session_state.watchlist_data = watchlist_data
                st.rerun()
            
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        st.error(f"自选股管理页面加载失败: {str(e)}")


# Backward compatibility alias
render_watchlist_page = render_watchlist_manager
