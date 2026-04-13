"""Watchlist Manager Component for TradingAgents Web UI."""

# pyright: reportMissingTypeStubs=false, reportReturnType=false, reportCallIssue=false, reportArgumentType=false, reportMissingTypeArgument=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportAttributeAccessIssue=false
import json
import os
import sys
import traceback
import time
import requests
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Optional
from socket import timeout as SocketTimeout

import streamlit as st

# Import incremental analysis panel renderer
from .watchlist_manager_incremental import render_incremental_analysis_section


# API URL - use same default as app.py
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8002")


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

        # Try to get intraday kline data first - fetch more data to cover
        # the analysis history window (5 days of 5m data = ~240 bars per day)
        df = provider.get_kline(symbol, period="5m", limit=480)

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


def add_trade_trajectory(fig, analysis_data: List[Dict], df: pd.DataFrame) -> None:
    """Add trading trajectory lines between BUY and SELL signals.

    Detects both BUY→SELL (long) and SELL→BUY (short) trade pairs.
    Profitable trades are drawn as green solid lines; losing trades as
    red dashed lines.  Hovering over a line shows entry/exit price and P&L.

    Args:
        fig: Plotly figure object to add traces to
        analysis_data: List of analysis history items with signal data
        df: DataFrame with price data for timestamp matching
    """
    import plotly.graph_objects as go

    if not analysis_data or df.empty:
        return

    # Sort analysis data chronologically
    sorted_data = sorted(analysis_data, key=lambda x: x.get("timestamp", ""))

    def _find_idx(timestamp_str: str) -> Optional[int]:
        """Find DataFrame index position closest to *timestamp_str* within 5 min."""
        try:
            ts = pd.to_datetime(timestamp_str)
            best_idx, best_diff = None, float("inf")
            for i, idx in enumerate(df.index):
                diff = abs((idx - ts).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
            return best_idx if best_idx is not None and best_diff <= 300 else None
        except Exception:
            return None

    # --- pair detection ---------------------------------------------------
    # Stack-based: BUY opens a long, SELL opens a short.
    # A BUY while short → close short (SELL→BUY pair).
    # A SELL while long → close long (BUY→SELL pair).
    open_positions: list = []  # list of (signal_type, item_dict, df_idx)
    pairs: list = []           # list of (entry_item, exit_item, entry_idx, exit_idx)

    for item in sorted_data:
        signal = item.get("signal", "")
        if signal not in ("BUY", "SELL"):
            continue

        idx = _find_idx(item.get("timestamp", ""))
        if idx is None:
            continue

        if signal == "BUY":
            if open_positions and open_positions[-1][0] == "SELL":
                # Close short: SELL→BUY pair
                sell_item, _, sell_idx = open_positions.pop()
                pairs.append((sell_item, item, sell_idx, idx))
            else:
                # Open long
                open_positions.append(("BUY", item, idx))
        else:  # SELL
            if open_positions and open_positions[-1][0] == "BUY":
                # Close long: BUY→SELL pair
                buy_item, _, buy_idx = open_positions.pop()
                pairs.append((buy_item, item, buy_idx, idx))
            else:
                # Open short
                open_positions.append(("SELL", item, idx))

    # --- draw trajectory lines --------------------------------------------
    for entry_item, exit_item, entry_idx, exit_idx in pairs:
        if entry_idx >= exit_idx:
            continue  # skip malformed pairs

        # Use price from analysis data, or fallback to candle close price
        entry_price = entry_item.get("price")
        if entry_price is None:
            entry_price = df.iloc[entry_idx]["close"]
        exit_price = exit_item.get("price")
        if exit_price is None:
            exit_price = df.iloc[exit_idx]["close"]

        # Determine direction and P&L
        entry_signal = entry_item.get("signal", "BUY")
        if entry_signal == "BUY":
            pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        else:  # SELL (short)
            pnl_pct = ((entry_price - exit_price) / entry_price * 100) if entry_price > 0 else 0

        is_profit = pnl_pct > 0
        line_color = "#4CAF50" if is_profit else "#F44336"
        line_dash = "solid" if is_profit else "dash"
        direction = "BUY→SELL" if entry_signal == "BUY" else "SELL→BUY"

        fig.add_trace(go.Scatter(
            x=[entry_idx, exit_idx],
            y=[entry_price, exit_price],
            mode="lines",
            line=dict(color=line_color, width=2, dash=line_dash),
            hovertemplate=(
                f"Trade: {direction}<br>"
                "Entry: ¥%{customdata[0]:.2f}<br>"
                "Exit: ¥%{customdata[1]:.2f}<br>"
                "P&amp;L: %{customdata[2]:+.2f}%<extra></extra>"
            ),
            customdata=[[entry_price, exit_price, pnl_pct]],
            showlegend=False,
        ))


def render_candlestick_chart(
    df: pd.DataFrame,
    title: str = "",
    height: int = 300,
    analysis_data: Optional[List[Dict]] = None,
    chart_key: str = "kline_chart",
) -> Optional[Dict]:
    """Render a candlestick chart using Plotly with optional signal overlays.

    Args:
        df: DataFrame with DatetimeIndex and open/high/low/close/volume columns
        title: Chart title
        height: Chart height in pixels
        analysis_data: Optional list of analysis history items for signal overlay
        chart_key: Unique key for the chart (enables on_select click handling)

    Returns:
        Dict with clicked signal details, or None if no marker was clicked.
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

    # Add signal markers if analysis data is provided
    if analysis_data:
        # Prepare marker data for all 5 signal types
        buy_x, buy_y, buy_text, buy_cd = [], [], [], []
        overweight_x, overweight_y, overweight_text, overweight_cd = [], [], [], []
        hold_x, hold_y, hold_text, hold_cd = [], [], [], []
        underweight_x, underweight_y, underweight_text, underweight_cd = [], [], [], []
        sell_x, sell_y, sell_text, sell_cd = [], [], [], []

        for item in analysis_data:
            signal = item.get("signal", "")
            timestamp = item.get("timestamp", "")
            price = item.get("price")
            confidence = item.get("confidence", 0)

            if not timestamp:
                continue

            try:
                # Parse timestamp and find matching index in df
                item_ts = pd.to_datetime(timestamp)

                # Find closest index in df
                closest_idx = None
                min_diff = float('inf')
                for i, idx in enumerate(df.index):
                    diff = abs((idx - item_ts).total_seconds())
                    if diff < min_diff:
                        min_diff = diff
                        closest_idx = i

                if closest_idx is None or min_diff > 300:  # Skip if more than 5 minutes off
                    continue

                # Determine y position based on signal type
                if signal == "BUY":
                    # Position at high + small offset
                    y_pos = df.iloc[closest_idx]["high"] * 1.002 if price is None else price * 1.002
                    buy_x.append(closest_idx)
                    buy_y.append(y_pos)
                    conf_str = f"置信度: {confidence:.0%}" if confidence is not None else ""
                    buy_text.append(f"BUY<br>{conf_str}<br>价格: ¥{price:.2f}" if price else f"BUY<br>{conf_str}")
                    buy_cd.append([json.dumps({"signal": "BUY", "confidence": confidence, "timestamp": timestamp, "price": price})])
                elif signal == "SELL":
                    # Position at low - small offset
                    y_pos = df.iloc[closest_idx]["low"] * 0.998 if price is None else price * 0.998
                    sell_x.append(closest_idx)
                    sell_y.append(y_pos)
                    conf_str = f"置信度: {confidence:.0%}" if confidence is not None else ""
                    sell_text.append(f"SELL<br>{conf_str}<br>价格: ¥{price:.2f}" if price else f"SELL<br>{conf_str}")
                    sell_cd.append([json.dumps({"signal": "SELL", "confidence": confidence, "timestamp": timestamp, "price": price})])
                elif signal == "OVERWEIGHT":
                    # Position at high + small offset (similar to BUY but less aggressive)
                    y_pos = df.iloc[closest_idx]["high"] * 1.001 if price is None else price * 1.001
                    overweight_x.append(closest_idx)
                    overweight_y.append(y_pos)
                    conf_str = f"置信度: {confidence:.0%}" if confidence is not None else ""
                    overweight_text.append(f"增持<br>{conf_str}<br>价格: ¥{price:.2f}" if price else f"增持<br>{conf_str}")
                    overweight_cd.append([json.dumps({"signal": "OVERWEIGHT", "confidence": confidence, "timestamp": timestamp, "price": price})])
                elif signal == "HOLD":
                    # Position at close
                    y_pos = df.iloc[closest_idx]["close"] if price is None else price
                    hold_x.append(closest_idx)
                    hold_y.append(y_pos)
                    conf_str = f"置信度: {confidence:.0%}" if confidence is not None else ""
                    hold_text.append(f"HOLD<br>{conf_str}<br>价格: ¥{price:.2f}" if price else f"HOLD<br>{conf_str}")
                    hold_cd.append([json.dumps({"signal": "HOLD", "confidence": confidence, "timestamp": timestamp, "price": price})])
                elif signal == "UNDERWEIGHT":
                    # Position at low - small offset (similar to SELL but less aggressive)
                    y_pos = df.iloc[closest_idx]["low"] * 0.999 if price is None else price * 0.999
                    underweight_x.append(closest_idx)
                    underweight_y.append(y_pos)
                    conf_str = f"置信度: {confidence:.0%}" if confidence is not None else ""
                    underweight_text.append(f"减持<br>{conf_str}<br>价格: ¥{price:.2f}" if price else f"减持<br>{conf_str}")
                    underweight_cd.append([json.dumps({"signal": "UNDERWEIGHT", "confidence": confidence, "timestamp": timestamp, "price": price})])
            except Exception:
                continue  # Skip items that fail to parse

        # Add BUY markers (green triangle-up)
        if buy_x:
            fig.add_trace(go.Scatter(
                x=buy_x,
                y=buy_y,
                mode="markers",
                customdata=buy_cd,
                marker=dict(
                    symbol="triangle-up",
                    size=14,
                    color="#4CAF50",
                    line=dict(width=1, color="white")
                ),
                hoverinfo="text",
                hovertext=buy_text,
                name="BUY",
                showlegend=False
            ))

        # Add SELL markers (red triangle-down)
        if sell_x:
            fig.add_trace(go.Scatter(
                x=sell_x,
                y=sell_y,
                mode="markers",
                customdata=sell_cd,
                marker=dict(
                    symbol="triangle-down",
                    size=14,
                    color="#F44336",
                    line=dict(width=1, color="white")
                ),
                hoverinfo="text",
                hovertext=sell_text,
                name="SELL",
                showlegend=False
            ))

        # Add HOLD markers (orange diamond)
        if hold_x:
            fig.add_trace(go.Scatter(
                x=hold_x,
                y=hold_y,
                mode="markers",
                customdata=hold_cd,
                marker=dict(
                    symbol="diamond",
                    size=12,
                    color="#FF9800",
                    line=dict(width=1, color="white")
                ),
                hoverinfo="text",
                hovertext=hold_text,
                name="HOLD",
                showlegend=False
            ))

        # Add OVERWEIGHT markers (light green triangle-up, smaller)
        if overweight_x:
            fig.add_trace(go.Scatter(
                x=overweight_x,
                y=overweight_y,
                mode="markers",
                customdata=overweight_cd,
                marker=dict(
                    symbol="triangle-up",
                    size=11,
                    color="#8BC34A",
                    line=dict(width=1, color="white")
                ),
                hoverinfo="text",
                hovertext=overweight_text,
                name="增持",
                showlegend=False
            ))

        # Add UNDERWEIGHT markers (light red triangle-down, smaller)
        if underweight_x:
            fig.add_trace(go.Scatter(
                x=underweight_x,
                y=underweight_y,
                mode="markers",
                customdata=underweight_cd,
                marker=dict(
                    symbol="triangle-down",
                    size=11,
                    color="#FF7043",
                    line=dict(width=1, color="white")
                ),
                hoverinfo="text",
                hovertext=underweight_text,
                name="减持",
                showlegend=False
            ))

        # Add trade trajectory lines
        add_trade_trajectory(fig, analysis_data, df)

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
        key=chart_key,
        on_select="rerun",
        config={
            'displayModeBar': False,       # hide toolbar for cleaner look
            'scrollZoom': False,
            'staticPlot': False,
            'responsive': True,
            'select2d': False,             # disable 2D select (only point click)
        },
    )

    # --- Handle signal marker click ---
    selected_signal: Optional[Dict] = None
    try:
        event = st.session_state.get(chart_key)
        if event is not None and hasattr(event, 'selection') and event.selection is not None:
            for point in getattr(event.selection, 'points', []):
                cd = getattr(point, 'customdata', None)
                if cd and len(cd) > 0:
                    selected_signal = json.loads(cd[0])
                    break
    except Exception:
        pass

    if selected_signal:
        st.session_state['selected_signal'] = selected_signal

    # Show caption when no analysis data has been loaded
    if not analysis_data:
        st.caption("尚无AI信号，请先运行分析")

    return selected_signal


def format_signal(signal: str, confidence: float) -> str:
    """Format AI signal with emoji and color - supports 5-tier rating."""
    if signal is None or confidence is None:
        return "⚪--(--%)"
    # 5-tier rating system
    emoji_map = {
        'BUY': '🟢',
        'OVERWEIGHT': '📈',  # Light green/up trend
        'HOLD': '🟡',
        'UNDERWEIGHT': '📉',  # Light red/down trend
        'SELL': '🔴',
        'UNKNOWN': '⚪'
    }
    # Map to Chinese display
    display_map = {
        'BUY': '买入',
        'OVERWEIGHT': '增持',
        'HOLD': '持有',
        'UNDERWEIGHT': '减持',
        'SELL': '卖出',
        'UNKNOWN': '未知'
    }
    emoji = emoji_map.get(signal, '⚪')
    display = display_map.get(signal, signal)
    return f"{emoji}{display}({confidence:.0%})"


def get_signal_color(signal: str) -> str:
    """Get color for signal - supports 5-tier rating."""
    # 5-tier color scheme: strong green -> light green -> yellow -> light red -> strong red
    color_map = {
        'BUY': '#4CAF50',           # Strong green
        'OVERWEIGHT': '#8BC34A',    # Light green
        'HOLD': '#FF9800',          # Orange/Yellow
        'UNDERWEIGHT': '#FF7043',   # Light red
        'SELL': '#F44336',          # Strong red
        'UNKNOWN': '#9E9E9E'        # Gray
    }
    return color_map.get(signal, '#9E9E9E')


def _is_market_open() -> bool:
    """Check if A-share market is currently open (9:20-11:30, 13:00-15:00 CST).

    Returns:
        True if market is open, False otherwise.
    """
    now = datetime.utcnow()
    # Convert to CST (UTC+8)
    cst_hour = (now.hour + 8) % 24
    # Monday=0 ... Friday=4
    weekday = now.weekday()
    if weekday >= 5:
        return False
    # Morning session: 9:20-11:30
    if (cst_hour == 9 and now.minute >= 20) or (10 <= cst_hour <= 11 and (cst_hour < 11 or now.minute <= 30)):
        return True
    # Afternoon session: 13:00-15:00
    if 13 <= cst_hour <= 14 or (cst_hour == 15 and now.minute == 0):
        return True
    return False


def get_next_analysis_text(
    is_high_freq: bool,
    high_freq_until: Optional[datetime],
    last_analysis_at: Optional[str] = None,
) -> str:
    """Get next analysis countdown text with real-time calculation.

    Args:
        is_high_freq: Whether the stock is in high-frequency mode.
        high_freq_until: Timestamp when high-frequency mode expires.
        last_analysis_at: ISO timestamp of the last analysis.

    Returns:
        Formatted countdown string, e.g. "⚡变盘 1:23" or "⏱️4:12".
    """
    # High-frequency mode with remaining time
    if is_high_freq and high_freq_until:
        remaining = high_freq_until - datetime.utcnow()
        if remaining.total_seconds() > 0:
            total_sec = int(remaining.total_seconds())
            minutes = total_sec // 60
            seconds = total_sec % 60
            if minutes > 0:
                return f"⚡变盘 {minutes}:{seconds:02d}"
            return f"⚡变盘 {seconds}秒"

    # Normal mode — estimate based on last analysis or fixed interval
    if _is_market_open():
        interval = 120 if is_high_freq else 300
        # If we have last_analysis_at, calculate actual remaining time
        if last_analysis_at:
            try:
                last_dt = datetime.fromisoformat(last_analysis_at.replace('Z', '+00:00')).replace(tzinfo=None)
                elapsed = (datetime.utcnow() - last_dt).total_seconds()
                remaining = max(0, interval - int(elapsed))
                mins = remaining // 60
                secs = remaining % 60
                if is_high_freq:
                    return f"⚡高频 {mins}:{secs:02d}"
                return f"⏱️{mins}:{secs:02d}"
            except Exception:
                pass
        # Fallback to static interval
        mins = interval // 60
        if is_high_freq:
            return f"⚡高频 {mins}:00"
        return f"⏱️{mins}:00"

    # Market closed
    return "💤 收盘后"


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


@st.cache_data(ttl=30, show_spinner=False)
def load_watchlist() -> List[Dict[str, Any]]:
    """Load watchlist from API. Cached for 30s to reduce rerun latency."""
    try:
        resp = requests.get(f"{API_URL}/api/v1/watchlist/", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        traceback.print_exc(file=sys.stderr)
    return []


def update_watchlist_stock(stock_id: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a watchlist stock."""
    try:
        resp = requests.put(
            f"{API_URL}/api/v1/watchlist/{stock_id}",
            json=payload,
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            st.error("股票不存在")
        else:
            detail = resp.json().get("detail", f"HTTP {resp.status_code}")
            st.error(f"更新失败: {detail}")
    except Exception as e:
        st.error(f"更新失败: {str(e)}")
        traceback.print_exc(file=sys.stderr)
    return None


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
            timeout=15
        )
        if resp.status_code == 202 or resp.status_code == 200:
            # Mark pending so auto-refresh can detect completion
            mark_analysis_pending(stock_id)
            return resp.json()
        else:
            st.session_state.setdefault("_analysis_errors", {})[str(stock_id)] = (
                f"分析触发失败: HTTP {resp.status_code}"
            )
    except Exception as e:
        st.session_state.setdefault("_analysis_errors", {})[str(stock_id)] = (
            f"分析触发失败: {str(e)}"
        )
        traceback.print_exc(file=sys.stderr)
    return None


def fetch_diff_report(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch diff report between the two most recent completed analyses for a symbol.

    Calls GET /api/v1/analysis/?symbol=<symbol>&limit=2 to find the two
    latest completed tasks, then POST /api/v1/analysis/diff-report with
    those task IDs.

    Args:
        symbol: Stock symbol (e.g. '000001').

    Returns:
        Diff report dict with keys ``analysts``, ``decision``,
        ``confidence``, ``timestamp_range``, or None on failure.
    """
    try:
        # 1. Fetch latest 2 completed analyses for this symbol
        resp = requests.get(
            f"{API_URL}/api/v1/analysis/",
            params={"symbol": symbol, "limit": 2},
            timeout=10,
        )
        if resp.status_code != 200:
            st.error(f"获取分析列表失败: HTTP {resp.status_code}")
            return None

        tasks: List[Dict] = resp.json()
        completed = [t for t in tasks if t.get("status") == "COMPLETED"]

        if len(completed) < 2:
            st.warning(f"{symbol} 至少需要 2 次已完成的分析才能对比 (当前: {len(completed)} 次)")
            return None

        # The list is already newest-first; task_id_1 = earlier, task_id_2 = later
        task_id_1 = completed[1]["task_id"]
        task_id_2 = completed[0]["task_id"]

        # 2. Request diff report
        diff_resp = requests.post(
            f"{API_URL}/api/v1/analysis/diff-report",
            json={"task_id_1": task_id_1, "task_id_2": task_id_2, "symbol": symbol},
            timeout=15,
        )
        if diff_resp.status_code != 200:
            detail = ""
            try:
                detail = diff_resp.json().get("detail", "")
            except Exception:
                pass
            st.error(f"生成差异报告失败: HTTP {diff_resp.status_code} {detail}")
            return None

        return diff_resp.json()

    except requests.Timeout:
        st.error("请求超时，请稍后重试")
    except Exception as e:
        st.error(f"获取差异报告失败: {str(e)}")
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


def invalidate_analysis_cache(watchlist_id: int) -> None:
    """Remove cached analysis history for a watchlist stock.

    Call this after an analysis completes so the next fetch picks up fresh data.
    """
    cache_key = f"analysis_history_{watchlist_id}"
    st.session_state.pop(cache_key, None)


def check_analysis_completion(watchlist_id: int) -> bool:
    """Check if a pending analysis has completed and refresh cache if so.

    Compares the stored ``previous_analysis_at`` timestamp with the current
    ``last_analysis_at`` from the watchlist record.  When a change is
    detected, the analysis history cache is invalidated and ``True`` is
    returned so the caller can trigger a ``st.rerun()``.

    Args:
        watchlist_id: The watchlist item ID to check.

    Returns:
        True if a new analysis was detected (caller should rerun), False otherwise.
    """
    pending_key = f"pending_analysis_{watchlist_id}"
    if not st.session_state.get(pending_key):
        return False

    # Fetch fresh watchlist item to compare timestamps
    try:
        resp = requests.get(f"{API_URL}/api/v1/watchlist/{watchlist_id}", timeout=3)
        if resp.status_code != 200:
            return False
        item = resp.json()
    except Exception:
        return False

    current_ts = item.get("last_analysis_at")
    previous_ts = st.session_state.get(f"previous_analysis_{watchlist_id}")

    if current_ts and current_ts != previous_ts:
        # New analysis detected — invalidate cache and clean up
        invalidate_analysis_cache(watchlist_id)
        st.session_state[f"previous_analysis_{watchlist_id}"] = current_ts
        st.session_state.pop(pending_key, None)
        return True

    return False


def mark_analysis_pending(watchlist_id: int) -> None:
    """Record that an analysis was triggered for *watchlist_id*.

    Stores the current ``last_analysis_at`` so
    :func:`check_analysis_completion` can detect when the new result lands.
    """
    try:
        resp = requests.get(f"{API_URL}/api/v1/watchlist/{watchlist_id}", timeout=3)
        if resp.status_code == 200:
            item = resp.json()
            st.session_state[f"previous_analysis_{watchlist_id}"] = item.get("last_analysis_at")
    except Exception:
        pass
    st.session_state[f"pending_analysis_{watchlist_id}"] = True


def fetch_analysis_history(
    watchlist_id: int,
    limit: int = 50,
    *,
    force_refresh: bool = False,
) -> Optional[List[Dict]]:
    """Fetch analysis history for a watchlist stock.

    Checks ``session_state`` cache first.  On miss (or when *force_refresh*
    is True), calls the API with up to 3 retries for transient errors.

    Args:
        watchlist_id: The watchlist item ID.
        limit: Maximum number of records to fetch (1-100).
        force_refresh: Bypass cache and re-fetch from API.

    Returns:
        List of analysis history items, or None if all retries fail.
    """
    cache_key = f"analysis_history_{watchlist_id}"

    # --- cache hit ---------------------------------------------------------
    if not force_refresh and cache_key in st.session_state:
        return st.session_state[cache_key]

    # --- fetch with retry ---------------------------------------------------
    last_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(
                f"{API_URL}/api/v1/watchlist/{watchlist_id}/analysis-history",
                params={"limit": limit},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                # API returns wrapped response: {watchlist_id, symbol, items, total, has_more}
                if isinstance(data, dict) and "items" in data:
                    items = data["items"]
                elif isinstance(data, list):
                    # Backward compat: handle plain list responses
                    items = data
                else:
                    items = []
                st.session_state[cache_key] = items
                return items
            # non-retryable HTTP error
            return None
        except (ConnectionError, SocketTimeout, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(1)  # wait before retry
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            last_exc = exc
            break  # non-transient error — don't retry

    # All retries exhausted
    traceback.print_exc(file=sys.stderr)
    # Return cached data as fallback even if stale
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    return None


def render_notification_settings() -> None:
    """Render notification settings management section.

    Allows users to configure desktop notification preferences:
    - Enable/disable notifications
    - Minimum importance threshold for alerts
    - Enable/disable sound
    - Send test notification
    """
    with st.expander("🔔 通知设置", expanded=False):
        st.caption("配置变盘信号桌面通知偏好")

        # Initialize defaults in session_state
        notif_key = "notification_settings"
        if notif_key not in st.session_state:
            st.session_state[notif_key] = {
                "enabled": True,
                "min_importance": 0.5,
                "sound_enabled": True,
                "analysis_complete": False,
            }
        settings = st.session_state[notif_key]

        # --- Toggle: enable notifications ---
        settings["enabled"] = st.checkbox(
            "启用桌面通知",
            value=settings["enabled"],
            help="变盘信号检测到时发送桌面通知",
            key="notif_enabled",
        )

        # --- Minimum importance threshold ---
        settings["min_importance"] = st.slider(
            "最低通知重要性",
            min_value=0.3,
            max_value=1.0,
            value=float(settings["min_importance"]),
            step=0.05,
            help="只有重要性评分超过此值的变盘信号才会触发通知",
            key="notif_min_importance",
            format="%.0f%%",
        )

        # --- Toggle: sound ---
        settings["sound_enabled"] = st.checkbox(
            "通知声音",
            value=settings["sound_enabled"],
            help="发送通知时播放提示音",
            key="notif_sound",
        )

        # --- Toggle: analysis complete notification ---
        settings["analysis_complete"] = st.checkbox(
            "分析完成通知",
            value=settings["analysis_complete"],
            help="每次分析完成时发送通知 (不仅限于变盘)",
            key="notif_analysis_complete",
        )

        # --- Test notification button ---
        st.divider()
        col_test, col_info = st.columns([1, 3])
        with col_test:
            if st.button(
                "📤 发送测试通知",
                key="notif_test_btn",
                help="发送一条测试通知以验证通知功能",
            ):
                try:
                    resp = requests.post(
                        f"{API_URL}/api/v1/watchlist/notification/test",
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        st.success("测试通知已发送，请检查桌面")
                    else:
                        st.warning("通知API不可用，通知将在服务端自动发送")
                except Exception:
                    # Fallback: show inline notification toast
                    st.toast("🔔 测试通知 - TradingAgents 监控系统", icon="🔔")
                    st.info("桌面通知测试已发送 (Streamlit toast)")

        with col_info:
            st.caption(
                "桌面通知由后端服务在检测到变盘时自动发送。"
                "此处设置控制通知偏好（当前存储在浏览器会话中）。"
            )

        # --- Summary display ---
        importance_labels = {
            range(3, 5): "低 (仅重大变盘)",
            range(5, 7): "中 (重要变盘)",
            range(7, 9): "高 (多数变盘)",
            range(9, 11): "全部 (所有变盘)",
        }
        importance_label = "中"
        imp_pct = int(settings["min_importance"] * 10)
        for rng, label in importance_labels.items():
            if imp_pct in rng:
                importance_label = label
                break

        st.markdown(
            f"""
            <div style="background:rgba(33,150,243,0.08);border:1px solid #2196F3;
                        border-radius:6px;padding:8px 12px;margin:8px 0;font-size:0.85rem;">
                <strong>当前配置</strong>: &nbsp;
                通知 {'✅ 已启用' if settings['enabled'] else '❌ 已禁用'} &nbsp;|&nbsp;
                最低重要性: <strong>{importance_label}</strong> ({settings['min_importance']:.0%}) &nbsp;|&nbsp;
                声音 {'🔊 开' if settings['sound_enabled'] else '🔇 关'} &nbsp;|&nbsp;
                分析完成 {'✅' if settings['analysis_complete'] else '❌'}
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_high_freq_status_bar() -> None:
    """Render a prominent status bar showing stocks currently in high-frequency mode.

    Displays a yellow/red banner listing all stocks that are in high-frequency
    monitoring mode, with remaining time countdown.
    """
    watchlist = st.session_state.get('watchlist_data', [])
    if not watchlist:
        return

    # Collect stocks currently in high-frequency mode
    hf_stocks: List[Dict[str, Any]] = []
    for item in watchlist:
        is_hf = item.get('is_high_frequency', False)
        hf_until_str = item.get('high_freq_until')
        if not is_hf or not hf_until_str:
            continue
        try:
            hf_until = datetime.fromisoformat(hf_until_str.replace('Z', '+00:00')).replace(tzinfo=None)
            if hf_until > datetime.utcnow():
                remaining = hf_until - datetime.utcnow()
                hf_stocks.append({
                    'symbol': item.get('symbol', '?'),
                    'name': item.get('name', ''),
                    'remaining': remaining,
                    'importance': item.get('last_confidence', 0),
                })
        except Exception:
            continue

    if not hf_stocks:
        return

    # Build the status bar
    stock_lines: List[str] = []
    for s in hf_stocks:
        total_sec = int(s['remaining'].total_seconds())
        mins = total_sec // 60
        secs = total_sec % 60
        remaining_text = f"{mins}:{secs:02d}"
        name = s['name'] or s['symbol']
        stock_lines.append(
            f"<strong>{s['symbol']} {name[:6]}</strong>"
            f" &nbsp;<span style='color:#F44336;font-weight:bold'>⚡ 剩余 {remaining_text}</span>"
        )

    stocks_html = "<br/>".join(stock_lines)
    is_urgent = any(s['remaining'].total_seconds() < 180 for s in hf_stocks)

    border_color = "#F44336" if is_urgent else "#FFC107"
    bg_color = "rgba(255, 82, 82, 0.08)" if is_urgent else "rgba(255, 193, 7, 0.08)"
    header_text = "🔥 高频监控中 - 紧急" if is_urgent else "⚡ 高频监控中"

    st.markdown(
        f"""
        <div style="background-color:{bg_color};
                    border:1px solid {border_color};
                    border-radius:6px;
                    padding:10px 14px;
                    margin:8px 0;">
            <div style="font-size:0.85rem;color:#333;margin-bottom:6px;">
                <strong>{header_text}</strong> &nbsp;
                <span style="color:#666">({len(hf_stocks)} 只股票处于高频分析模式)</span>
            </div>
            <div style="font-size:0.85rem;line-height:1.6;">
                {stocks_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_monitoring_status_overview() -> None:
    """Render a compact monitoring status overview banner.

    Shows key system metrics:
    - Total monitored stocks / active count
    - High-frequency mode count
    - Market status (open/closed)
    - Next scheduled analysis time
    - Alerts today count
    - Data last updated timestamp
    """
    watchlist = st.session_state.get('watchlist_data', [])

    # Calculate metrics
    total = len(watchlist)
    active = sum(1 for w in watchlist if w.get('is_active', True))
    hf_count = 0
    for w in watchlist:
        is_hf = w.get('is_high_frequency', False)
        hf_until_str = w.get('high_freq_until')
        if is_hf and hf_until_str:
            try:
                hf_until = datetime.fromisoformat(hf_until_str.replace('Z', '+00:00')).replace(tzinfo=None)
                if hf_until > datetime.utcnow():
                    hf_count += 1
            except Exception:
                pass

    market_open = _is_market_open()
    market_emoji = "🟢" if market_open else "🔴"
    market_text = "交易中" if market_open else "已收盘"

    # Alerts count from cached alerts
    alerts = st.session_state.get('turning_alerts', [])
    alerts_today = 0
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    for a in alerts:
        alert_time = a.get('time', '')
        if today_str in alert_time:
            alerts_today += 1

    # Last data update timestamp
    last_update = st.session_state.get('watchlist_last_update', '')

    # Build the overview metrics
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            label="监控股票",
            value=f"{active}/{total}",
            help=f"活跃/总数",
        )

    with col2:
        hf_color = "#F44336" if hf_count > 0 else "#9E9E9E"
        st.markdown(
            f'<div style="text-align:center">'
            f'<div style="font-size:0.75rem;color:#6B7280">高频模式</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:{hf_color}">'
            f'{"⚡ " + str(hf_count) if hf_count > 0 else "无"}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    with col3:
        market_color = "#4CAF50" if market_open else "#F44336"
        st.markdown(
            f'<div style="text-align:center">'
            f'<div style="font-size:0.75rem;color:#6B7280">市场状态</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:{market_color}">'
            f'{market_emoji} {market_text}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    with col4:
        alert_color = "#F44336" if alerts_today > 0 else "#9E9E9E"
        st.markdown(
            f'<div style="text-align:center">'
            f'<div style="font-size:0.75rem;color:#6B7280">今日变盘</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:{alert_color}">'
            f'{"🔥 " + str(alerts_today) if alerts_today > 0 else "0"}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    with col5:
        st.markdown(
            f'<div style="text-align:center">'
            f'<div style="font-size:0.75rem;color:#6B7280">数据更新</div>'
            f'<div style="font-size:0.85rem;color:#6B7280">'
            f'{last_update if last_update else "--"}'
            f'</div></div>',
            unsafe_allow_html=True,
        )


def show_error_banner(message: str, retry_key: str = "retry_btn") -> bool:
    """Show a styled error banner with retry button.

    Args:
        message: Error message to display.
        retry_key: Unique key for the retry button.

    Returns:
        True if retry button was clicked.
    """
    col_msg, col_btn = st.columns([6, 1])
    with col_msg:
        st.error(message)
    with col_btn:
        return st.button("🔄 重试", key=retry_key, use_container_width=False)


@st.cache_data(ttl=15)
def get_scheduler_status() -> Optional[Dict]:
    """Get scheduler status (cached 15s)."""
    try:
        resp = requests.get(f"{API_URL}/api/v1/watchlist/scheduler/status", timeout=3)
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
            try:
                error_detail = resp.json().get('detail', f'HTTP {resp.status_code}')
            except Exception:
                error_detail = resp.text or f'HTTP {resp.status_code}'
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
            try:
                error_detail = resp.json().get('detail', f'HTTP {resp.status_code}')
            except Exception:
                error_detail = resp.text or f'HTTP {resp.status_code}'
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


# ============================================================================
# Batch API Client with Caching (N+1 Optimization)
# ============================================================================

_BATCH_STATUS_TTL = 5  # seconds


def _get_cached_batch_status(symbols: List[str]) -> Optional[Dict]:
    """Return cached batch status if still fresh, else None."""
    cache_key = f"batch_status_{hash(','.join(sorted(symbols)))}"
    entry = st.session_state.get(cache_key)
    if entry is None:
        return None
    if time.time() - entry["ts"] > _BATCH_STATUS_TTL:
        return None
    return entry["data"]


def _set_cached_batch_status(symbols: List[str], data: Dict) -> None:
    """Store batch status in session_state with TTL."""
    cache_key = f"batch_status_{hash(','.join(sorted(symbols)))}"
    st.session_state[cache_key] = {"data": data, "ts": time.time()}


def invalidate_batch_status_cache(symbols: Optional[List[str]] = None) -> None:
    """Invalidate batch status cache. If symbols is None, clear all."""
    if symbols:
        cache_key = f"batch_status_{hash(','.join(sorted(symbols)))}"
        st.session_state.pop(cache_key, None)
    else:
        for key in list(st.session_state.keys()):
            if key.startswith("batch_status_"):
                del st.session_state[key]


def fetch_watchlist_status_batch(symbols: List[str]) -> Dict[str, Dict]:
    """Fetch analysis status for multiple symbols via batch API.

    Uses 5-second client-side cache and auto-chunks >50 symbols.

    Args:
        symbols: List of 6-digit A-share codes.

    Returns:
        Dict mapping symbol -> {is_analyzing, has_full_analysis_today,
        has_multiple_analyses, last_analysis_at}
    """
    if not symbols:
        return {}

    # Check cache
    cached = _get_cached_batch_status(symbols)
    if cached is not None:
        return cached

    # Auto-chunk for >50 symbols
    MAX_CHUNK = 50
    if len(symbols) > MAX_CHUNK:
        merged: Dict[str, Dict] = {}
        for i in range(0, len(symbols), MAX_CHUNK):
            merged.update(fetch_watchlist_status_batch(symbols[i : i + MAX_CHUNK]))
        return merged

    try:
        resp = requests.get(
            f"{API_URL}/api/v1/watchlist/analysis-status",
            params={"symbols": ",".join(symbols)},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _set_cached_batch_status(symbols, data)
            return data
        return {}
    except Exception:
        return {}


def _has_full_analysis_today(symbol: str) -> bool:
    """Check if a full analysis was completed today for the given symbol.

    Args:
        symbol: Stock symbol (e.g. '000001')

    Returns:
        True if at least one 'full' analysis completed today.
    """
    try:
        today_start = datetime.combine(datetime.utcnow().date(), datetime.min.time()).isoformat()
        resp = requests.get(
            f"{API_URL}/api/v1/analysis/",
            params={
                "symbol": symbol,
                "status": "COMPLETED",
                "since": today_start,
            },
            timeout=3,
        )
        if resp.status_code == 200:
            data = resp.json()
            tasks = data if isinstance(data, list) else data.get("items", data.get("tasks", []))
            for task in tasks:
                if task.get("analysis_type") == "full":
                    return True
    except Exception:
        pass
    return False


def _has_multiple_analyses_today(symbol: str, minimum: int = 2) -> bool:
    """Check if at least N analyses exist today for the given symbol.

    Args:
        symbol: Stock symbol (e.g. '000001')
        minimum: Minimum number of analyses required (default 2)

    Returns:
        True if count of completed analyses today >= minimum.
    """
    try:
        today_start = datetime.combine(datetime.utcnow().date(), datetime.min.time()).isoformat()
        resp = requests.get(
            f"{API_URL}/api/v1/analysis/",
            params={
                "symbol": symbol,
                "status": "COMPLETED",
                "since": today_start,
            },
            timeout=3,
        )
        if resp.status_code == 200:
            data = resp.json()
            tasks = data if isinstance(data, list) else data.get("items", data.get("tasks", []))
            return len(tasks) >= minimum
    except Exception:
        pass
    return False


def _is_analysis_running(symbol: str) -> bool:
    """Check if any analysis task is currently RUNNING or PENDING for the symbol.

    Args:
        symbol: Stock symbol (e.g. '000001')

    Returns:
        True if a task with RUNNING or PENDING status exists for this symbol.
    """
    try:
        resp = requests.get(
            f"{API_URL}/api/v1/analysis/",
            params={"symbol": symbol},
            timeout=3,
        )
        if resp.status_code == 200:
            data = resp.json()
            tasks = data if isinstance(data, list) else data.get("items", data.get("tasks", []))
            for task in tasks:
                status = task.get("status", "").upper()
                if status in ("RUNNING", "PENDING"):
                    return True
    except Exception:
        pass
    return False


def trigger_full_analysis(symbol: str, force_refresh: bool = False) -> Optional[Dict]:
    """Trigger a full analysis for a stock via the watchlist analyze endpoint.

    Args:
        symbol: Stock symbol (e.g. '000001')
        force_refresh: Whether to bypass analyst cache

    Returns:
        Response dict if successful, None otherwise.
    """
    try:
        resp = requests.post(
            f"{API_URL}/api/v1/watchlist/analyze",
            params={"symbol": symbol, "force_refresh": force_refresh},
            timeout=15,
        )
        if resp.status_code in (200, 202):
            return resp.json()
        else:
            st.session_state.setdefault("_analysis_errors", {})[symbol] = (
                f"全量分析触发失败: HTTP {resp.status_code}"
            )
    except Exception as e:
        st.session_state.setdefault("_analysis_errors", {})[symbol] = (
            f"全量分析触发失败: {str(e)}"
        )
        traceback.print_exc(file=sys.stderr)
    return None


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
    
    col1, col2, col3, col4 = st.columns([3, 1, 2, 1])

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
        search_clicked = st.button(
            "搜索",
            use_container_width=True,
            key="search_watchlist_btn"
        )

    if search_clicked:
        if not search_symbol:
            st.warning("请输入股票代码")
        elif len(search_symbol.strip()) == 6 and search_symbol.strip().isdigit():
            with st.spinner("正在搜索股票..."):
                resolved_name = resolve_stock_name(search_symbol.strip())
                if resolved_name:
                    st.session_state[f"_resolved_name_{search_symbol.strip()}"] = resolved_name
                    st.success(f"已找到: {search_symbol.strip()} {resolved_name}")
                else:
                    st.warning("未找到对应股票，请检查代码")
        else:
            st.warning("请输入6位A股代码")

    with col3:
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
    
    with col4:
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
                    # Clear caches to force fresh data on rerun
                    load_watchlist.clear()
                    cache_key = f"_resolved_name_{search_symbol.strip()}"
                    st.session_state.pop(cache_key, None)
                    st.session_state.pop("watchlist_name", None)
                    st.session_state.pop("watchlist_search", None)
                    st.rerun()
            else:
                st.warning("请输入股票代码")


def render_edit_stock_modal() -> None:
    """Render watchlist edit modal."""
    if not st.session_state.get("show_edit_stock") or not st.session_state.get("selected_stock"):
        return

    item = st.session_state.selected_stock
    stock_id = item.get("id", 0)
    symbol = item.get("symbol", "Unknown")

    with st.expander(f"✏️ 编辑 {symbol}", expanded=True):
        edited_name = st.text_input(
            "股票名称",
            value=item.get("name") or "",
            key=f"edit_name_{stock_id}",
        )
        edited_exchange = st.selectbox(
            "交易所",
            options=["CN", "SZ", "SH"],
            index=max(["CN", "SZ", "SH"].index(item.get("exchange")) if item.get("exchange") in ["CN", "SZ", "SH"] else 0, 0),
            key=f"edit_exchange_{stock_id}",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("保存编辑", key=f"save_edit_{stock_id}", type="primary"):
                updated = update_watchlist_stock(
                    stock_id,
                    {
                        "name": edited_name,
                        "exchange": edited_exchange,
                    },
                )
                if updated:
                    st.session_state.show_edit_stock = False
                    st.session_state.selected_stock = updated
                    st.session_state.watchlist_data = load_watchlist()
                    st.success(f"已更新 {symbol}")
                    st.rerun()
        with col2:
            if st.button("取消编辑", key=f"cancel_edit_{stock_id}"):
                st.session_state.show_edit_stock = False
                st.rerun()


def render_watchlist_table():
    """Render watchlist table with AI signals."""
    st.subheader("📋 自选股列表")
    st.caption("每5分钟AI分析，变盘时2分钟高频")
    
    # Load watchlist data (always fresh from cache)
    watchlist = load_watchlist()
    
    if not watchlist:
        st.info("暂无自选股，请添加股票开始监控")
        return

    # N+1优化: 批量获取所有股票的分析状态（替代逐只查询）
    all_symbols = [item.get("symbol") for item in watchlist if item.get("symbol")]
    status_batch: Dict[str, Dict] = {}
    if all_symbols:
        status_batch = fetch_watchlist_status_batch(all_symbols)
    
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
        
        # FINAL FIX: Single row with all buttons horizontal
        # [Stock Info 50%] [All Actions 50%]
        main_cols = st.columns([5, 5])
        
        # Left: Stock info compact display
        with main_cols[0]:
            info_parts = [f"**{symbol}**"]
            if name:
                info_parts.append(name[:10])
            if last_price:
                color = "#4CAF50" if last_change_pct and last_change_pct > 0 else "#F44336"
                sign = "+" if last_change_pct and last_change_pct > 0 else ""
                info_parts.append(f"¥{last_price:.2f}")
                if last_change_pct:
                    info_parts.append(f"<span style='color:{color}'>{sign}{last_change_pct:.1f}%</span>")
            
            st.markdown(" | ".join(info_parts), unsafe_allow_html=True)
            
            signal_color = get_signal_color(last_signal)
            signal_text = format_signal(last_signal, last_confidence)
            next_text = get_next_analysis_text(is_high_freq, high_freq_until, item.get('last_analysis_at'))
            st.markdown(f"<small>{signal_text} | {next_text} {'🔥' if is_turning else ''}</small>", unsafe_allow_html=True)
        
        # Right: All action buttons in ONE horizontal row (8 buttons)
        with main_cols[1]:
            # Compute states
            _sym_status = status_batch.get(symbol, {})
            is_analyzing = _sym_status.get("is_analyzing", False)
            has_full_today = _sym_status.get("has_full_analysis_today", False)
            has_multiple = _sym_status.get("has_multiple_analyses", False)
            if st.session_state.get("optimistic_analysis_state", {}).get(symbol) == "running":
                is_analyzing = True
            # Clear stale optimistic state once API confirms not analyzing
            if not is_analyzing and st.session_state.get("optimistic_analysis_state", {}).get(symbol):
                st.session_state.get("optimistic_analysis_state", {}).pop(symbol, None)
            
            # All 8 buttons in ONE row - no vertical stacking
            btn_cols = st.columns([0.8, 1, 1, 1, 1, 0.8, 0.8, 0.8])
            
            with btn_cols[0]:  # View
                if st.button("👁️", key=f"view_{stock_id}", help="查看"):
                    st.session_state.selected_stock = item
                    st.session_state.show_stock_detail = True
            
            with btn_cols[1]:  # Force refresh checkbox (compact)
                st.checkbox("☐", key=f"fr_{stock_id}", help="强刷", label_visibility="collapsed")
            
            with btn_cols[2]:  # Full analysis
                if is_analyzing:
                    st.button("📊", key=f"full_{stock_id}", disabled=True, help="⏳ 分析中，请等待完成")
                else:
                    if st.button("📊", key=f"full_{stock_id}", help="全量分析"):
                        st.session_state.setdefault("optimistic_analysis_state", {})[symbol] = "running"
                        result = trigger_full_analysis(symbol, st.session_state.get(f"fr_{stock_id}", False))
                        if result:
                            invalidate_batch_status_cache([symbol])
                            st.toast(f"🚀 {symbol} 全量分析已启动", icon="✅")
                        else:
                            # Failed - clear optimistic state so button re-enables
                            st.session_state.get("optimistic_analysis_state", {}).pop(symbol, None)
                        st.rerun()
            
            with btn_cols[3]:  # Incremental
                incr_disabled = not has_full_today or is_analyzing
                if incr_disabled:
                    incr_reason = "⏳ 分析中" if is_analyzing else "❗ 请先完成全量分析"
                else:
                    incr_reason = "增量分析"
                if st.button("🔄", key=f"incr_{stock_id}", disabled=incr_disabled, help=incr_reason):
                    st.session_state['incr_panel_stock_id'] = stock_id
                    st.rerun()
            
            with btn_cols[4]:  # Diff
                diff_disabled = not has_multiple or is_analyzing
                if diff_disabled:
                    diff_reason = "⏳ 分析中" if is_analyzing else "❗ 需要至少2次分析"
                else:
                    diff_reason = "差异对比"
                if st.button("📋", key=f"diff_{stock_id}", disabled=diff_disabled, help=diff_reason):
                    st.session_state.diff_report_data = fetch_diff_report(symbol)
                    st.session_state.diff_symbol = symbol
                    st.session_state.show_diff_modal = True
                    st.rerun()
            
            with btn_cols[5]:  # Edit
                if st.button("✏️", key=f"edit_{stock_id}", help="编辑"):
                    st.session_state.selected_stock = item
                    st.session_state.show_edit_stock = True
                    st.rerun()
            
            with btn_cols[6]:  # Settings
                if st.button("⚙️", key=f"set_{stock_id}", help="设置"):
                    st.session_state.selected_stock = item
                    st.session_state.show_stock_settings = True
            
            with btn_cols[7]:  # Delete
                confirm_key = f"confirm_del_{stock_id}"
                if st.session_state.get(confirm_key):
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅", key=f"y_{stock_id}"):
                            if delete_watchlist_stock(stock_id):
                                st.session_state[confirm_key] = False
                                load_watchlist.clear()
                                st.rerun()
                    with c2:
                        if st.button("❌", key=f"n_{stock_id}"):
                            st.session_state[confirm_key] = False
                            st.rerun()
                else:
                    if st.button("🗑️", key=f"del_{stock_id}", help="删除"):
                        st.session_state[confirm_key] = True
                        st.rerun()
        
        if is_turning or importance_high:
            st.markdown("</div>", unsafe_allow_html=True)
        st.divider()


def render_control_buttons():
    """Render control buttons for monitoring."""
    st.subheader("🎛️ 监控控制")

    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 2])

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
                    st.rerun()
        else:
            if st.button("⏸️ 暂停监控", use_container_width=True):
                if stop_monitoring():
                    st.session_state.monitoring_active = False
                    st.warning("监控已暂停")
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
                st.rerun()
            else:
                st.warning("自选股列表为空")
    
    with col3:
        if st.button("🔄 刷新列表", use_container_width=True):
            st.session_state.watchlist_data = load_watchlist()
            st.session_state.watchlist_last_update = datetime.utcnow().strftime("%H:%M:%S")
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
    
    with col5:
        # Show scheduler status
        scheduler_status = get_scheduler_status()
        if scheduler_status:
            is_running = scheduler_status.get('is_running', False)
            status_emoji = "🟢" if is_running else "🔴"
            status_text = "运行中" if is_running else "已停止"
            active_jobs = scheduler_status.get('active_jobs', 0)
            st.caption(f"{status_emoji} 调度器: {status_text} ({active_jobs} 个活跃任务)")
        else:
            st.caption("🔴 调度器: 未连接")


def render_monitoring_panel():
    """Render real-time monitoring panel."""
    st.subheader("📈 实时监控面板")
    st.caption("价格走势与AI信号关联")
    
    watchlist = st.session_state.get('watchlist_data', [])
    
    if not watchlist:
        st.info("添加股票以查看实时面板")
        return

    # Check if any pending analyses have completed → invalidate cache
    _need_rerun = False
    for item in watchlist:
        wid = item.get("id")
        if wid and check_analysis_completion(wid):
            _need_rerun = True
    if _need_rerun:
        st.rerun()

    # Initialize session state for multi-select
    if 'monitoring_selected_stocks' not in st.session_state:
        # Select first 4 stocks by default
        st.session_state.monitoring_selected_stocks = [
            item['id'] for item in watchlist[:4]
        ]

    # Multi-stock charts section
    st.subheader("📊 多股价格对比")
    # 显式加载控制: 避免无条件加载所有K线图
    chart_load_col1, chart_load_col2 = st.columns([1, 3])
    with chart_load_col1:
        if st.button("📈 加载K线图表", key="load_charts_btn"):
            st.session_state.load_monitoring_charts = True
    with chart_load_col2:
        if st.session_state.get("load_monitoring_charts"):
            st.caption("✅ 图表已加载")
        else:
            st.caption("👆 点击左侧按钮加载图表数据（减少初始加载时间）")
    selected_ids = st.session_state.monitoring_selected_stocks

    # Filter watchlist to get selected stocks
    selected_stocks = [item for item in watchlist if item['id'] in selected_ids]

    if st.session_state.get("load_monitoring_charts"):
        # Display charts in rows of 2 (larger charts = better resolution)
        for i in range(0, len(selected_stocks), 2):
            row_stocks = selected_stocks[i:i+2]
            cols = st.columns(2)
            for idx, stock in enumerate(row_stocks):
                with cols[idx]:
                    symbol = stock['symbol']
                    name = stock.get('name', symbol)
                    st.write(f"**{symbol} {name}**")

                    # Fetch and display chart with analysis overlay
                    df = get_stock_intraday_data(symbol)
                    if df is not None and not df.empty:
                        # Fetch analysis history for this stock
                        stock_id = stock.get('id')
                        analysis_data = None
                        if stock_id:
                            with st.spinner("加载分析数据中..."):
                                analysis_data = fetch_analysis_history(stock_id)
                            if analysis_data is None:
                                # Show error banner with retry option
                                if show_error_banner(
                                    "⚠️ 分析数据获取失败",
                                    retry_key=f"retry_monitor_{stock_id}",
                                ):
                                    st.session_state.pop(
                                        f"analysis_history_{stock_id}", None
                                    )
                                    st.rerun()
                                # Fall back to stale cache if available
                                if f"analysis_history_{stock_id}" in st.session_state:
                                    analysis_data = st.session_state[f"analysis_history_{stock_id}"]

                        clicked = render_candlestick_chart(df, analysis_data=analysis_data, height=350, chart_key=f"monitor_chart_{stock_id}")
                        # If a signal marker was clicked, open detail modal for this stock
                        if clicked and stock_id:
                            st.session_state.selected_stock = stock
                            st.session_state.show_stock_detail = True
                            st.rerun()
                    else:
                        st.caption("暂无数据")
    else:
        st.info("👆 点击上方「加载K线图表」按钮查看详细走势")

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
        
        # Price trend - real K-line chart with analysis overlay
        st.write("**价格走势**")

        detail_df = get_stock_intraday_data(symbol)
        if detail_df is not None and not detail_df.empty:
            # Fetch analysis history for detailed view
            watchlist_id = selected_item.get('id')
            analysis_data = None
            if watchlist_id:
                with st.spinner("加载分析数据中..."):
                    analysis_data = fetch_analysis_history(watchlist_id)
                if analysis_data is None:
                    # Show error banner with retry
                    if show_error_banner(
                        "⚠️ 分析历史数据获取失败，仅显示价格走势",
                        retry_key=f"retry_detail_{watchlist_id}",
                    ):
                        st.session_state.pop(
                            f"analysis_history_{watchlist_id}", None
                        )
                        st.rerun()
                    # Try to use cached data
                    cache_key = f"analysis_history_{watchlist_id}"
                    if cache_key in st.session_state:
                        analysis_data = st.session_state[cache_key]
                        st.info("使用缓存的分析数据")

            render_candlestick_chart(
                detail_df,
                title=f"{symbol} {name} 分时K线",
                height=400,
                analysis_data=analysis_data,
                chart_key=f"detail_chart_{watchlist_id}",
            )

            # Show clicked signal details below chart
            clicked_signal = st.session_state.get('selected_signal')
            if clicked_signal and clicked_signal.get('timestamp'):
                sig = clicked_signal.get('signal', 'UNKNOWN')
                conf = clicked_signal.get('confidence', 0)
                price = clicked_signal.get('price')
                ts = clicked_signal.get('timestamp', '')
                sig_color = get_signal_color(sig)
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = ts[:16] if ts else ""
                price_str = f"¥{price:.2f}" if price else "--"
                st.markdown(
                    f'<div style="background:rgba(33,150,243,0.08);border:1px solid #2196F3;'
                    f'border-radius:8px;padding:10px 14px;margin:8px 0">'
                    f'<strong>📌 点击的信号</strong><br/>'
                    f'<span style="color:{sig_color};font-weight:bold;font-size:1.1em">'
                    f'{format_signal(sig, conf)}</span>'
                    f' &nbsp;|&nbsp; 价格: {price_str} &nbsp;|&nbsp; 时间: {time_str}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
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
            
            # Analysis history with K-line chart
            st.write("**分析历史 & K线信号**")
            watchlist_id = item.get('id')
            if watchlist_id:
                with st.spinner("加载分析数据中..."):
                    analysis_data = fetch_analysis_history(watchlist_id)

                if analysis_data is None:
                    if show_error_banner(
                        "⚠️ 分析历史数据获取失败",
                        retry_key=f"retry_modal_history_{watchlist_id}"
                    ):
                        st.session_state.pop(
                            f"analysis_history_{watchlist_id}", None
                        )
                        st.rerun()
                else:
                    # Show K-line chart with signals and trajectory
                    symbol = item.get('symbol', 'Unknown')
                    name = item.get('name', symbol)
                    detail_df = get_stock_intraday_data(symbol)
                    if detail_df is not None and not detail_df.empty:
                        render_candlestick_chart(
                            detail_df,
                            title=f"{symbol} {name}",
                            height=350,
                            analysis_data=analysis_data,
                            chart_key=f"modal_chart_{watchlist_id}",
                        )
                    else:
                        st.caption("暂无价格数据")

                    # Show analysis history table - only show selected record
                    if analysis_data:
                        st.write("**历史信号详情**")

                        # Get selected signal
                        clicked_signal = st.session_state.get('selected_signal')
                        
                        if clicked_signal and clicked_signal.get('timestamp'):
                            # Only display the selected record
                            selected_ts = clicked_signal['timestamp']
                            selected_rec = None
                            for rec in analysis_data:
                                if rec.get("timestamp") == selected_ts:
                                    selected_rec = rec
                                    break
                            
                            if selected_rec:
                                ts = selected_rec.get("timestamp", "")
                                sig = selected_rec.get("signal", "UNKNOWN")
                                conf = selected_rec.get("confidence", 0)
                                price = selected_rec.get("price")
                                err = selected_rec.get("error_message")
                                sig_color = get_signal_color(sig)
                                
                                time_str = ""
                                if ts:
                                    try:
                                        dt = datetime.fromisoformat(
                                            ts.replace('Z', '+00:00')
                                        )
                                        time_str = dt.strftime("%m/%d %H:%M")
                                    except Exception:
                                        time_str = ts[:16]

                                # Display selected record with highlight
                                border = "border:2px solid #2196F3;border-radius:6px;padding:10px;background:rgba(33,150,243,0.06);margin:8px 0"

                                if err:
                                    st.markdown(
                                        f"<div style='{border}'><span style='color:#F44336'>"
                                        f"❌ {time_str} 分析失败: {err}</span></div>",
                                        unsafe_allow_html=True,
                                    )
                                else:
                                    price_str = (
                                        f"¥{price:.2f}" if price else "--"
                                    )
                                    st.markdown(
                                        f"<div style='{border}'><span style='color:{sig_color}'>"
                                        f"📌 {time_str} "
                                        f"{format_signal(sig, conf)} "
                                        f"@ {price_str}</span></div>",
                                        unsafe_allow_html=True,
                                    )
                                
                                # Show back button to view all history
                                if st.button("← 查看全部历史记录", key="view_all_history"):
                                    st.session_state.selected_signal = None
                                    st.rerun()
                            else:
                                st.caption("选中的记录不存在")
                                if st.button("← 查看全部历史记录", key="view_all_history_invalid"):
                                    st.session_state.selected_signal = None
                                    st.rerun()
                        else:
                            # No signal selected, show list for selection
                            st.caption("点击K线图表上的信号点查看详情，或选择下方记录：")
                            
                            for rec in analysis_data[:5]:
                                ts = rec.get("timestamp", "")
                                sig = rec.get("signal", "UNKNOWN")
                                conf = rec.get("confidence", 0)
                                price = rec.get("price")
                                err = rec.get("error_message")
                                sig_color = get_signal_color(sig)
                                time_str = ""
                                if ts:
                                    try:
                                        dt = datetime.fromisoformat(
                                            ts.replace('Z', '+00:00')
                                        )
                                        time_str = dt.strftime("%m/%d %H:%M")
                                    except Exception:
                                        time_str = ts[:16]

                                if err:
                                    btn_label = f"❌ {time_str} 分析失败"
                                else:
                                    price_str = f"¥{price:.2f}" if price else "--"
                                    btn_label = f"{time_str} {format_signal(sig, conf)} @ {price_str}"
                                
                                if st.button(btn_label, key=f"select_signal_{ts}"):
                                    st.session_state.selected_signal = rec
                                    st.rerun()
                    else:
                        st.caption("尚无AI信号，请先运行分析")
            else:
                st.caption("无效的股票ID")
            
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
                            st.rerun()
                        else:
                            st.error(f"保存失败: HTTP {resp.status_code}")
                    except Exception as e:
                        st.error(f"保存失败: {str(e)}")
            
            with col2:
                if st.button("取消", key=f"cancel_settings_{stock_id}"):
                    st.session_state.show_stock_settings = False
                    st.rerun()


def render_diff_modal() -> None:
    """Render diff report modal using st.expander.

    Displayed when ``st.session_state['show_diff_modal']`` is truthy.
    Reads the diff report from ``st.session_state['diff_report_data']``
    (pre-fetched on button click to avoid expensive calls every rerun).
    """
    if not st.session_state.get('show_diff_modal'):
        return

    symbol = st.session_state.get('diff_symbol', '')
    report = st.session_state.get('diff_report_data')

    with st.expander(f"📊 {symbol} 分析差异对比", expanded=True):
        if report is None:
            st.caption("报告数据为空。")
            if st.button("关闭", key="close_diff_empty"):
                st.session_state.show_diff_modal = False
                st.rerun()
            return

        # --- Time range ---
        ts_range = report.get("timestamp_range", "")
        if ts_range:
            st.caption(f"⏱️ 时间范围: {ts_range}")

        # --- Decision comparison ---
        decision = report.get("decision", {})
        signal_before = decision.get("signal_before") or "N/A"
        signal_after = decision.get("signal_after") or "N/A"
        signal_changed = decision.get("signal_changed", False)

        col1, col2 = st.columns(2)
        with col1:
            before_color = "#F44336" if signal_before in ("BUY", "SELL") else "#FFC107" if signal_before == "HOLD" else "#9E9E9E"
            st.markdown(
                f"<div style='text-align:center'>"
                f"<div style='font-size:0.85rem;color:#6B7280'>之前信号</div>"
                f"<div style='font-size:1.4rem;font-weight:700;color:{before_color}'>{signal_before}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with col2:
            after_color = "#4CAF50" if signal_after == "BUY" else "#F44336" if signal_after == "SELL" else "#FFC107" if signal_after == "HOLD" else "#9E9E9E"
            delta_text = "🔄 变化" if signal_changed else "— 无变化"
            st.markdown(
                f"<div style='text-align:center'>"
                f"<div style='font-size:0.85rem;color:#6B7280'>之后信号</div>"
                f"<div style='font-size:1.4rem;font-weight:700;color:{after_color}'>{signal_after}</div>"
                f"<div style='font-size:0.8rem;color:#6B7280'>{delta_text}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # --- Confidence comparison ---
        confidence = report.get("confidence", {})
        conf_before = confidence.get("before")
        conf_after = confidence.get("after")
        conf_delta = confidence.get("delta")
        if conf_before is not None and conf_after is not None:
            delta_str = f"{conf_delta:+.0%}" if conf_delta is not None else "N/A"
            col3, col4 = st.columns(2)
            with col3:
                st.metric("之前置信度", f"{conf_before:.0%}")
            with col4:
                st.metric("之后置信度", f"{conf_after:.0%}", delta=delta_str)

        st.divider()

        # --- Per-analyst diffs ---
        analysts = report.get("analysts", {})
        if not analysts:
            st.info("无分析师级别的差异。")
        else:
            # Friendly name mapping
            _FRIENDLY_NAMES: Dict[str, str] = {
                "market_analyst": "市场分析师",
                "social_analyst": "社交情绪分析师",
                "news_analyst": "新闻分析师",
                "fundamentals_analyst": "基本面分析师",
                "research_manager": "研究经理",
                "research_debate": "研究辩论",
                "trader": "交易员",
                "risk_debate": "风险辩论",
                "portfolio_manager": "投资组合经理",
            }

            changed_count = sum(1 for v in analysts.values() if v.get("changed"))
            st.caption(f"共 {len(analysts)} 个角色，{changed_count} 个有变化")

            for analyst_key, analyst_data in analysts.items():
                display_name = _FRIENDLY_NAMES.get(analyst_key, analyst_key)
                changed = analyst_data.get("changed", False)
                change_type = analyst_data.get("change_type", "unchanged")

                # Choose icon based on change type
                if not changed:
                    icon = "⚪"
                elif change_type == "added":
                    icon = "🟢"
                elif change_type == "removed":
                    icon = "🔴"
                else:
                    icon = "🟡"

                with st.expander(f"{icon} {display_name}"):
                    if not changed:
                        st.write("无显著变化")
                    else:
                        # Price diff if available
                        price_before = analyst_data.get("price_before")
                        price_after = analyst_data.get("price_after")
                        if price_before is not None and price_after is not None:
                            st.write(f"**价格变化**: ¥{price_before:.2f} → ¥{price_after:.2f}")

                        # Change type badge
                        _TYPE_LABELS = {
                            "added": "新增",
                            "removed": "移除",
                            "content_changed": "内容变化",
                        }
                        type_label = _TYPE_LABELS.get(change_type, change_type)
                        st.caption(f"变更类型: {type_label}")

                        # Unified diff (if present)
                        diff_summary = analyst_data.get("diff_summary")
                        if diff_summary:
                            st.code(diff_summary, language="diff")

                        # Previews
                        old_preview = analyst_data.get("old_preview", "")
                        new_preview = analyst_data.get("new_preview", "")
                        if old_preview or new_preview:
                            prev_cols = st.columns(2)
                            with prev_cols[0]:
                                if old_preview:
                                    st.caption("之前内容摘要")
                                    st.text(old_preview[:300])
                            with prev_cols[1]:
                                if new_preview:
                                    st.caption("之后内容摘要")
                                    st.text(new_preview[:300])

        # Close button
        if st.button("关闭", key="close_diff"):
            st.session_state.show_diff_modal = False
            st.session_state.diff_report_data = None
            st.session_state.diff_symbol = None
            st.rerun()


def render_watchlist_manager():
    """Main entry point for watchlist management page."""
    try:
        # Display deferred analysis errors (stored by trigger_full_analysis)
        _errors = st.session_state.pop("_analysis_errors", {})
        if _errors:
            for _sym, _msg in _errors.items():
                st.error(f"**{_sym}** {_msg}")
        
        st.title("📊 自选股实时监控")
        st.caption("AI驱动变盘检测")
        
        # --- Monitoring Status Overview (compact banner) ---
        render_monitoring_status_overview()
        
        st.divider()
        
        # --- High-Frequency Mode Status Bar (prominent, only shown when active) ---
        render_high_freq_status_bar()
        
        # --- Search and add section ---
        render_add_stock_section()
        
        st.divider()
        
        # --- Watchlist table ---
        render_watchlist_table()
        
        # --- Incremental analysis panel (full-width, rendered outside table) ---
        watchlist = st.session_state.get('watchlist_data', [])
        if watchlist:
            render_incremental_analysis_section(watchlist)
        
        st.divider()
        
        # --- Control buttons ---
        render_control_buttons()
        
        st.divider()
        
        # --- Real-time monitoring panel ---
        render_monitoring_panel()
        
        st.divider()
        
        # --- Turning signal history ---
        render_turning_history()
        
        st.divider()
        
        # --- Notification settings ---
        render_notification_settings()
        
        # --- Modals (rendered last, on top of content) ---
        if st.session_state.get('show_stock_detail'):
            render_stock_detail_modal()
        
        if st.session_state.get('show_stock_settings'):
            render_stock_settings_modal()

        if st.session_state.get('show_edit_stock'):
            render_edit_stock_modal()
        
        if st.session_state.get('show_diff_modal'):
            render_diff_modal()
        
        # --- Auto-refresh logic ---
        if st.session_state.get('auto_refresh', True):
            # Use a shorter delay and incremental refresh
            time.sleep(30)  # Refresh every 30 seconds
            st.session_state.refresh_alerts = True
            # Update last refresh timestamp
            st.session_state.watchlist_last_update = datetime.utcnow().strftime("%H:%M:%S")
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
