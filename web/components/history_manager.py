"""History Manager Component for TradingAgents Web UI."""
import json
import os
import sys
import threading
import traceback
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

# Import unified signal extractor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapi.utils.signal_extractor import extract_decision_with_fallback


def _extract_from_api_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Build a history record from an API task response.

    Priority:
    1. Use DB fields ``decision`` / ``confidence`` if present.
    2. Fallback to ``extract_decision_with_fallback`` on the raw result.
    """
    result_data = task.get("result", {}) or {}

    db_decision = task.get("decision")
    db_confidence = task.get("confidence")

    if db_decision and db_decision != "UNKNOWN":
        decision = db_decision
        confidence = (db_confidence / 100.0) if isinstance(db_confidence, (int, float)) else 0.0
    else:
        decision, confidence = extract_decision_with_fallback(result_data)

    return {
        "task_id": task.get("task_id"),
        "symbol": task.get("symbol", ""),
        "exchange": task.get("exchange", "CN"),
        "created_at": task.get("created_at", ""),
        "updated_at": task.get("updated_at", ""),
        "status": task.get("status", "PENDING"),
        "decision": decision,
        "confidence": confidence,
        "reasoning": "",
        "risk_level": "",
        "indicators": {},
        "raw_result": result_data,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _get_stock_name(symbol: str) -> str:
    """Fetch stock name for a given symbol, cached for 1 hour."""
    if not symbol or symbol == "Unknown":
        return ""
    try:
        from tradingagents.dataflows.ashare_provider import AshareProvider

        quote = AshareProvider().get_realtime_quote(symbol)
        if quote and quote.get("name"):
            return str(quote["name"])
    except Exception:
        pass
    return ""


# History storage path - store in project directory for persistence
HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
DELETED_IDS_FILE = os.path.join(HISTORY_DIR, "deleted_ids.json")

# API URL - use same default as app.py
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8002")

STATUS_CONFIG = {
    "PENDING": ("⏳", "等待中", "#FFA500"),
    "RUNNING": ("🔄", "分析中", "#2196F3"),
    "COMPLETED": ("✅", "完成", "#4CAF50"),
    "FAILED": ("❌", "失败", "#F44336"),
    "CANCELLED": ("⏹️", "已取消", "#9E9E9E"),
}

STEP_NAMES = {
    "graph_setup": "初始化分析图",
    "market_analyst": "市场分析师",
    "sentiment_analyst": "情绪分析师",
    "news_analyst": "新闻分析师",
    "fundamentals_analyst": "基本面分析师",
    "bull_researcher": "看涨研究员",
    "bear_researcher": "看跌研究员",
    "research_manager": "研究经理",
    "trader": "交易员",
    "risk_manager": "风控经理",
    "portfolio_manager": "投资组合经理",
    "propagate": "多智能体分析",
    "completed": "分析完成",
    "error": "执行失败",
}

DECISION_TEXT_MAP = {
    "BUY": ("买入", "#4CAF50"),
    "OVERWEIGHT": ("增持", "#2E7D32"),
    "HOLD": ("持有", "#FF9800"),
    "UNDERWEIGHT": ("减持", "#FB8C00"),
    "SELL": ("卖出", "#F44336"),
    "UNKNOWN": ("未知", "#9E9E9E"),
}

CORE_STEPS = [
    "graph_setup",
    "market_analyst",
    "sentiment_analyst",
    "news_analyst",
    "fundamentals_analyst",
    "bull_researcher",
    "bear_researcher",
    "research_manager",
    "trader",
    "risk_manager",
    "portfolio_manager",
]


def ensure_history_dir():
    """Ensure history directory exists."""
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)


def load_deleted_ids() -> set[str]:
    """Load set of deleted task IDs (tombstone)."""
    if not os.path.exists(DELETED_IDS_FILE):
        return set()
    try:
        with open(DELETED_IDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('deleted_ids', []))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return set()


def save_deleted_ids(deleted_ids: set[str]):
    """Save deleted task IDs to tombstone file."""
    ensure_history_dir()
    with open(DELETED_IDS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'deleted_ids': list(deleted_ids)}, f, indent=2)


def load_history_fast() -> List[Dict[str, Any]]:
    """Fast loading with short timeout to avoid UI blocking."""
    ensure_history_dir()

    # Try API with short timeout (1.5s to avoid UI blocking)
    try:
        resp = requests.get(f"{API_URL}/api/v1/analysis/", params={"limit": 50}, timeout=1.5)
        if resp.status_code == 200:
            api_tasks = resp.json()
            return [_extract_from_api_task(task) for task in api_tasks]
    except Exception:
        # API unavailable or slow - fall through to local cache
        pass

    # FALLBACK: Use local cache only
    local_records = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'records' in data:
                    local_records = data['records']
                elif isinstance(data, list):
                    local_records = data
        except Exception:
            traceback.print_exc(file=sys.stderr)

    return local_records


def load_history() -> List[Dict[str, Any]]:
    """Load analysis history from API (primary) with local cache fallback.
    
    PostgreSQL is the source of truth. Local JSON is only used as:
    - Cache when API is unavailable
    - Export/backup (not active merge source)
    
    Returns:
        List of history records from API (or local cache if API down)
    """
    ensure_history_dir()

    # PRIMARY: Try to fetch from API (PostgreSQL is source of truth)
    api_records: List[Dict[str, Any]] = []
    api_available = False
    try:
        resp = requests.get(f"{API_URL}/api/v1/analysis/", params={"limit": 50}, timeout=5)
        if resp.status_code == 200:
            api_available = True
            api_tasks = resp.json()
            for task in api_tasks:
                api_records.append(_extract_from_api_task(task))
    except Exception:
        # API unavailable, will fall back to local cache
        pass

    # If API is available, use it as source of truth (ignore local merge)
    if api_available:
        return api_records

    # FALLBACK: API unavailable, use local cache only
    local_records = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'records' in data:
                    local_records = data['records']
                elif isinstance(data, list):
                    local_records = data
        except Exception:
            traceback.print_exc(file=sys.stderr)

    return local_records


def save_history(records: List[Dict[str, Any]]):
    """Save analysis history to file.
    
    Args:
        records: List of history records to save
    """
    ensure_history_dir()
    data = {
        "version": "1.0",
        "records": records
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_to_history(task_id: str, symbol: str, result: Dict[str, Any]):
    """Add a new analysis to history.
    
    Args:
        task_id: API task ID
        symbol: Stock symbol
        result: Analysis result data
    """
    records = load_history_fast()  # Use fast version (1.5s timeout) for better UX
    
    # Check if already exists
    for record in records:
        if record.get("task_id") == task_id:
            return
    
    # Extract key fields from result
    record = {
        "task_id": task_id,
        "symbol": symbol,
        "exchange": result.get("exchange", "CN"),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "status": result.get("status", "COMPLETED"),
        "decision": result.get("decision", "UNKNOWN"),
        "confidence": result.get("confidence", 0),
        "reasoning": result.get("reasoning", ""),
        "risk_level": result.get("risk_level", ""),
        "indicators": result.get("indicators", {}),
        "raw_result": result
    }
    
    records.append(record)
    
    # Keep only last 100 records
    records = sorted(records, key=lambda x: x.get("created_at", ""), reverse=True)[:100]
    save_history(records)


def load_local_history() -> List[Dict[str, Any]]:
    """Load history from local file only (no API call).
    
    Returns:
        List of local history records
    """
    ensure_history_dir()
    
    if not os.path.exists(HISTORY_FILE):
        return []
    
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'records' in data:
                return data['records']
            elif isinstance(data, list):
                return data
    except Exception:
        traceback.print_exc(file=sys.stderr)
    
    return []


def delete_from_history(task_id: str) -> bool:
    """Delete an analysis from history via API.

    Calls DELETE /api/v1/analysis/{task_id} first, then removes the
    local cache entry.  Falls back to local-only delete when the API is
    unreachable so the UI still works offline.

    Thread-safe: does not call st.* when run from a background thread.

    Args:
        task_id: Task ID to delete

    Returns:
        True if deletion succeeded, False otherwise
    """
    # Try API delete first
    api_ok = False
    try:
        resp = requests.delete(
            f"{API_URL}/api/v1/analysis/{task_id}",
            timeout=2,  # Reduced from 5s for faster feedback
        )
        if resp.status_code == 204:
            api_ok = True
        elif resp.status_code == 404:
            # Task may already be deleted or only exists locally
            api_ok = True  # Treat as success so local cleanup proceeds
        # Other status codes: still try local cleanup
    except Exception:
        # API unreachable — fall back to local-only delete
        traceback.print_exc(file=sys.stderr)

    # Always clean up local cache (whether API succeeded or was unreachable)
    records = load_local_history()
    records = [r for r in records if r.get("task_id") != task_id]
    save_history(records)

    if api_ok:
        # Also remove from tombstone since the server handled it
        deleted_ids = load_deleted_ids()
        deleted_ids.discard(task_id)
        save_deleted_ids(deleted_ids)
    else:
        # API was unreachable — keep tombstone so API records don't resurrect it
        deleted_ids = load_deleted_ids()
        deleted_ids.add(task_id)
        save_deleted_ids(deleted_ids)

    return True


def get_history_item(task_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific history item by task_id.
    
    Args:
        task_id: Task ID to find
        
    Returns:
        History record or None
    """
    records = load_history_fast()  # Use fast version (1.5s timeout) for better UX
    for record in records:
        if record.get("task_id") == task_id:
            return record
    return None


def get_local_history_item(task_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific local history item by task_id without API calls."""
    ensure_history_dir()

    if not os.path.exists(HISTORY_FILE):
        return None

    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'records' in data:
                records = data['records']
            elif isinstance(data, list):
                records = data
            else:
                records = []

        for record in records:
            if record.get("task_id") == task_id:
                return record
    except Exception:
        traceback.print_exc(file=sys.stderr)

    return None


def load_history_detail(task_id: str) -> Optional[Dict[str, Any]]:
    """Load one history detail from API directly by task_id."""
    try:
        resp = requests.get(f"{API_URL}/api/v1/analysis/{task_id}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        traceback.print_exc(file=sys.stderr)
    return None


def get_task_progress(task_id: str) -> Optional[Dict[str, Any]]:
    """Fetch real-time progress for a task from API.
    
    Args:
        task_id: Task ID
        
    Returns:
        Dict with progress info or None
    """
    try:
        # First get the task to check status
        resp = requests.get(f"{API_URL}/api/v1/analysis/{task_id}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "PENDING")
            
            if status in ("COMPLETED", "FAILED"):
                # Task is complete - calculate actual duration from updated_at - created_at
                created_at = data.get("created_at", "")
                updated_at = data.get("updated_at", "")
                elapsed = 0
                if created_at and updated_at:
                    try:
                        start_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        elapsed = (end_dt.replace(tzinfo=None) - start_dt.replace(tzinfo=None)).total_seconds()
                    except:
                        # Fallback: use created_at to now
                        try:
                            start_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            elapsed = (datetime.now() - start_dt.replace(tzinfo=None)).total_seconds()
                        except:
                            pass
                return {
                    "status": status,
                    "progress": 100 if status == "COMPLETED" else 0,
                    "elapsed": elapsed,
                    "remaining": 0,
                    "message": data.get("message", ""),
                }
            
            # For PENDING/RUNNING tasks, try to get detailed progress
            try:
                progress_resp = requests.get(f"{API_URL}/api/v1/analysis/{task_id}/progress", timeout=5)
                if progress_resp.status_code == 200:
                    # SSE endpoint returns event stream, parse it
                    text = progress_resp.text
                    import re
                    # Find JSON data in SSE format: data: {...}
                    # Use a pattern that finds 'data: ' followed by JSON object
                    match = re.search(r'data:\s*(\{.*\})', text, re.DOTALL)
                    if match:
                        progress_data = json.loads(match.group(1))
                        return progress_data
            except:
                pass
            
            # Fallback: calculate from task data
            created_at = data.get("created_at", "")
            elapsed = 0
            if created_at:
                try:
                    start_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    elapsed = (datetime.now() - start_dt.replace(tzinfo=None)).total_seconds()
                except:
                    pass
            
            # Progress estimation: API uses estimated_total = 60 * analyst_count + 60
            # With 4 analysts (market+news+fundamentals+sentiment), that's 300s = 5 minutes
            # But actual execution takes longer, so use 600s = 10 minutes as estimate
            estimated_total = 600  # 10 minutes default estimate
            
            # Calculate remaining, but if negative (overtime), show as 0 but flag as overtime
            overtime = elapsed > estimated_total
            remaining = max(0, estimated_total - elapsed)
            
            # Progress percentage based on elapsed time vs estimated 300s total
            if elapsed < 60:
                progress = min(15, (elapsed / 60) * 15)
            elif elapsed < 120:
                progress = 15 + min(25, ((elapsed - 60) / 60) * 25)
            elif elapsed < 180:
                progress = 40 + min(25, ((elapsed - 120) / 60) * 25)
            elif elapsed < 240:
                progress = 65 + min(20, ((elapsed - 180) / 60) * 20)
            elif elapsed < estimated_total:
                progress = 85 + min(15, ((elapsed - 240) / 60) * 15)
            else:
                progress = min(99, 95 + ((elapsed - estimated_total) / 120) * 4)  # Slowly increase past 95%, every 2 min adds 4%
            
            return {
                "status": status,
                "progress": round(progress, 1),
                "elapsed": elapsed,
                "remaining": round(remaining, 1),
                "message": data.get("message", ""),
            }
    except Exception as e:
        pass
    return None


def extract_task_timing(task: Dict[str, Any], result_data: Optional[Dict[str, Any]] = None) -> tuple[int, Optional[int]]:
    """Extract elapsed and remaining time from task/result data."""
    data = result_data if isinstance(result_data, dict) else task.get("raw_result", {}) or {}
    if not isinstance(data, dict):
        data = {}

    elapsed_time = data.get("elapsed_time")
    remaining_time = data.get("remaining_time")

    try:
        elapsed = max(0, int(elapsed_time)) if elapsed_time is not None else 0
    except (TypeError, ValueError):
        elapsed = 0

    if remaining_time is None:
        remaining = None
    else:
        try:
            remaining = max(0, int(remaining_time))
        except (TypeError, ValueError):
            remaining = None

    if elapsed == 0:
        created_at = task.get("created_at", "")
        updated_at = task.get("updated_at", "")
        if created_at:
            try:
                start_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00')).replace(tzinfo=None)
                if updated_at and task.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
                    end_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00')).replace(tzinfo=None)
                else:
                    end_dt = datetime.now()
                elapsed = max(0, int((end_dt - start_dt).total_seconds()))
            except Exception:
                elapsed = 0

    return elapsed, remaining


def simplify_step_status(agents_progress: Dict[str, Any], current_agent: str) -> List[tuple[str, str, str]]:
    """Build simplified core step statuses for detail rendering."""
    items: List[tuple[str, str, str]] = []
    for step_id in CORE_STEPS:
        raw_status = agents_progress.get(step_id, "not_started") if isinstance(agents_progress, dict) else "not_started"
        if step_id == current_agent and raw_status == "not_started":
            raw_status = "in_progress"
        items.append((step_id, STEP_NAMES.get(step_id, step_id), raw_status))
    return items


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human readable string."""
    return format_time(seconds)


def render_history_manager() -> Optional[str]:
    """Render history manager UI.
    
    Returns:
        Selected task_id if user clicks view, None otherwise
    """
    try:
        st.header("📚 分析历史")

        # Initialize session state for caching
        if 'history_cache' not in st.session_state:
            st.session_state.history_cache = []
            st.session_state.history_cache_time = 0
        
        # Check if we need to refresh (cache for 3 seconds to avoid blocking)
        current_time = datetime.now().timestamp()
        cache_age = current_time - st.session_state.history_cache_time
        
        # Use cached data immediately if available and fresh (< 3 seconds)
        # This prevents blocking on every Streamlit rerun
        if st.session_state.history_cache and cache_age < 3:
            records = st.session_state.history_cache
        else:
            # Load with shorter timeout to avoid UI blocking
            # If API is slow, use cached data
            try:
                records = load_history_fast()
                st.session_state.history_cache = records
                st.session_state.history_cache_time = current_time
            except Exception:
                # On error, use cached data if available
                records = st.session_state.history_cache or []
        
        # Add a manual refresh button
        col_refresh, col_info = st.columns([1, 5])
        with col_refresh:
            if st.button("🔄 刷新", key="refresh_history", help="手动刷新历史记录"):
                st.session_state.history_cache = []
                st.session_state.history_cache_time = 0
                st.rerun()
        with col_info:
            if records:
                # Format cache age nicely
                # If cache is extremely old (> 1 day), treat it as stale and reset
                if cache_age > 86400:  # > 1 day means stale session state
                    st.session_state.history_cache_time = current_time
                    cache_text = "已刷新"
                elif st.session_state.history_cache_time == 0:
                    cache_text = "已刷新"
                elif cache_age < 3:
                    cache_text = "刚刚"
                elif cache_age < 60:
                    cache_text = f"{int(cache_age)} 秒前"
                elif cache_age < 3600:
                    cache_text = f"{int(cache_age / 60)} 分钟前"
                else:
                    cache_text = f"{int(cache_age / 3600)} 小时前"
                st.caption(f"共 {len(records)} 条记录 | {cache_text}")

        if not records:
            st.info("暂无分析历史记录")
            st.caption("完成一次股票分析后，记录将显示在这里")
            return None

        # Search and filter
        col1, col2 = st.columns([3, 1])
        with col1:
            search = st.text_input("🔍 搜索股票代码", placeholder="输入股票代码筛选...")
        with col2:
            sort_by = st.selectbox(
                "排序方式",
                options=["时间倒序", "时间正序", "股票代码"],
                index=0
            )

        # Filter records
        filtered_records = records
        if search:
            filtered_records = [
                r for r in records
                if search.upper() in r.get("symbol", "").upper()
            ]

        # Sort records
        if sort_by == "时间倒序":
            filtered_records = sorted(
                filtered_records,
                key=lambda x: x.get("created_at", ""),
                reverse=True
            )
        elif sort_by == "时间正序":
            filtered_records = sorted(
                filtered_records,
                key=lambda x: x.get("created_at", "")
            )
        elif sort_by == "股票代码":
            filtered_records = sorted(
                filtered_records,
                key=lambda x: x.get("symbol", "")
            )

        st.divider()

        # Display history list
        selected_task_id = None

        for idx, record in enumerate(filtered_records):
            task_id = record.get("task_id", "")
            symbol = record.get("symbol", "Unknown")
            created_at = record.get("created_at", "")
            updated_at = record.get("updated_at", "")
            status = record.get("status", "")
            decision = record.get("decision", "")
            raw_result = record.get("raw_result", {}) or {}
            if not isinstance(raw_result, dict):
                raw_result = {}

            # Format date
            try:
                dt = datetime.fromisoformat(created_at)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = created_at[:16] if created_at else "Unknown"

            # Card layout: 4 columns [2, 2, 1.5, 1.5]
            col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1.5])
            elapsed, _ = extract_task_timing(record, raw_result)
            status_icon, status_text, status_color = STATUS_CONFIG.get(status, ("⚪", status or "未知", "#9E9E9E"))

            with col1:
                name = _get_stock_name(symbol)
                if name:
                    st.markdown(
                        f"### 📊 {symbol} <span style='font-size:0.8rem;color:#6B7280;'> {name}</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(f"### 📊 {symbol}")
                st.caption(f"🕐 {date_str}")
                st.caption(f"{status_icon} {status_text}")

            with col2:
                if status == "RUNNING":
                    progress_pct = int(raw_result.get("progress_pct", 0) or 0)
                    current_agent = raw_result.get("current_agent", "")
                    step_name = STEP_NAMES.get(current_agent, current_agent) if current_agent else "分析中"
                    progress_indeterminate = bool(raw_result.get("is_progress_indeterminate"))
                    st.progress(progress_pct / 100, text=f"{progress_pct}%")
                    st.caption(f"📍 当前: {step_name}")
                    st.caption(f"⏱️ 已用: {format_time(elapsed)}")
                    if progress_indeterminate:
                        st.caption("⏳ 剩余: 计算中...")
                elif status == "COMPLETED":
                    decision_info = DECISION_TEXT_MAP.get(decision, (decision or "未知", "#9E9E9E"))
                    decision_text, decision_color = decision_info

                    result_error = raw_result.get("error")
                    if result_error:
                        st.markdown(f"<span style='color: #F44336'>❌ 分析失败</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<span style='color: {decision_color}; font-weight: bold;'>{decision_text}</span>", unsafe_allow_html=True)
                        if elapsed > 0:
                            st.caption(f"⏱️ 耗时: {format_time(elapsed)}")
                elif status == "FAILED":
                    st.markdown(f"<span style='color: #F44336'>❌ 失败</span>", unsafe_allow_html=True)
                    if elapsed > 0:
                        st.caption(f"⏱️ 已运行: {format_time(elapsed)}")
                else:
                    st.markdown(
                        f"<span style='color: {status_color}; font-weight: 600;'>{status_icon} {status_text}</span>",
                        unsafe_allow_html=True,
                    )
                    if elapsed > 0:
                        st.caption(f"⏱️ 已等待: {format_time(elapsed)}")

            with col3:
                if st.button("👁️ 查看", key=f"view_{task_id}", help="查看详情", use_container_width=True):
                    selected_task_id = task_id

            with col4:
                if st.button("🗑️ 删除", key=f"del_{task_id}", help="删除记录", use_container_width=True):
                    # Optimistic delete: instantly remove from cache, fire API in background
                    st.session_state.history_cache = [
                        r for r in st.session_state.get("history_cache", [])
                        if r.get("task_id") != task_id
                    ]
                    st.session_state.history_cache_time = datetime.now().timestamp()
                    # Fire-and-forget: delete from API in background thread
                    threading.Thread(
                        target=delete_from_history, args=(task_id,), daemon=True
                    ).start()
                    st.rerun()

            st.divider()

        # Summary stats
        st.divider()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("总记录数", len(records))
        with col2:
            running_count = sum(1 for r in records if r.get("status") in ("PENDING", "RUNNING"))
            st.metric("分析中", running_count)
        with col3:
            buy_count = sum(1 for r in records if r.get("decision") == "BUY")
            st.metric("买入", buy_count)
        with col4:
            sell_count = sum(1 for r in records if r.get("decision") == "SELL")
            st.metric("卖出", sell_count)

        return selected_task_id
    except Exception:
        traceback.print_exc(file=sys.stderr)
        st.error("历史记录页面加载失败，请稍后重试")
        return None


def render_history_detail(task_id: str):
    """Render detailed view of a history item.
    
    Args:
        task_id: Task ID to display
    """
    try:
        # Try to get fresh data from API first
        api_data = load_history_detail(task_id)

        # Use API data if available, otherwise fall back to local record
        record = None
        raw_result = {}
        analysis_error = None  # Store error message if analysis failed
        if api_data:
            symbol = api_data.get("symbol", "Unknown")
            created_at = api_data.get("created_at", "")
            status = api_data.get("status", "")
            result_data = api_data.get("result", {}) or {}
            # Check if analysis failed (inner result error OR top-level FAILED status/error)
            if isinstance(result_data, dict) and result_data.get("status") == "error":
                analysis_error = result_data.get("error", "分析执行失败")
            elif api_data.get("status") == "FAILED":
                analysis_error = api_data.get("error", "分析执行失败")
            elif api_data.get("error"):
                analysis_error = api_data.get("error", "分析执行失败")
            final_state = result_data.get("final_state", {}) if isinstance(result_data, dict) else {}
            raw_result = result_data
            # Try to get local record for indicators
            record = get_local_history_item(task_id)
        else:
            record = get_local_history_item(task_id)
            if not record:
                st.error("未找到该历史记录")
                return
            symbol = record.get("symbol", "Unknown")
            created_at = record.get("created_at", "")
            status = record.get("status", "")
            # Backward compatibility: read raw_result if present, otherwise use record directly
            raw_result = record.get("raw_result") or record
            if not isinstance(raw_result, dict):
                raw_result = {}
            # Local fallback: use raw_result as result_data (not just final_state)
            # so we have access to top-level error, status, signal fields
            result_data = raw_result
            # Check if analysis failed (local data)
            # Handle both "error" (old format) and "FAILED" (new format) statuses
            if isinstance(raw_result, dict):
                if raw_result.get("status") in ("error", "FAILED") or raw_result.get("error"):
                    analysis_error = raw_result.get("error") or "分析执行失败"
            final_state = raw_result.get("final_state", {}) if isinstance(raw_result, dict) else {}

        # Ensure final_state is always a dict (never None)
        if not isinstance(final_state, dict):
            final_state = {}
        if not isinstance(result_data, dict):
            result_data = {}
        if not isinstance(raw_result, dict):
            raw_result = {}

        # Extract recommendation and summary from result
        recommendation = ""
        summary = ""
        decision = "UNKNOWN"
        confidence = 0
        risk_level = ""
        key_points = []
        reasoning = ""

        # Try api_data top-level fields FIRST (DB-persisted correct values)
        if api_data and isinstance(api_data, dict):
            db_decision = api_data.get("decision")
            db_confidence = api_data.get("confidence")
            if db_decision and db_decision != "UNKNOWN":
                decision = db_decision
                if isinstance(db_confidence, (int, float)) and db_confidence > 0:
                    confidence = db_confidence

        # Extract from final_state (TradingAgents result structure)
        if isinstance(final_state, dict):
            # Try to extract decision/recommendation from messages
            messages = final_state.get("messages", [])
            if messages and len(messages) > 0:
                # Handle both string and dict message formats
                last_msg = messages[-1] if messages else {}

                # If last_msg is a string, use it directly
                if isinstance(last_msg, str):
                    content = last_msg
                elif isinstance(last_msg, dict):
                    content = last_msg.get("content", "")
                else:
                    content = str(last_msg) if last_msg else ""

                if content:
                    # Try to find FINAL TRANSACTION PROPOSAL in content
                    if "FINAL TRANSACTION PROPOSAL:" in content:
                        proposal_section = content.split("FINAL TRANSACTION PROPOSAL:")[-1].split("---")[0]
                        recommendation = proposal_section.strip()

            # Get reports from final_state
            market_report = final_state.get("market_report", "")
            sentiment_report = final_state.get("sentiment_report", "")
            news_report = final_state.get("news_report", "")
            fundamentals_report = final_state.get("fundamentals_report", "")

            # Use first report as summary if no explicit summary
            summary = final_state.get("summary", "") or market_report or ""

            # Try to extract risk level
            risk_level = final_state.get("risk_level", "")
            if not risk_level and final_state.get("investment_debate_state"):
                debate = final_state.get("investment_debate_state", {})
                risk_level = debate.get("risk_assessment", "")

        # Fallback: use extract_decision_with_fallback for 5-tier + Chinese support
        if decision == "UNKNOWN":
            fallback_decision, fallback_conf = extract_decision_with_fallback(
                result_data or raw_result
            )
            if fallback_decision and fallback_decision != "UNKNOWN":
                decision = fallback_decision
            if confidence == 0 and fallback_conf > 0:
                # Display expects 0-100 range; fallback returns 0-1
                confidence = fallback_conf * 100

        # Fallback to result_data fields (only overwrite if still UNKNOWN/0)
        if isinstance(result_data, dict):
            recommendation = recommendation or result_data.get("recommendation", "")
            if decision == "UNKNOWN":
                decision = result_data.get("decision", decision)
            if confidence == 0:
                result_conf = result_data.get("confidence", 0)
                if isinstance(result_conf, (int, float)) and result_conf > 0:
                    # Display expects 0-100 range
                    confidence = result_conf if result_conf > 1.0 else result_conf * 100
            risk_level = risk_level or result_data.get("risk_level", "")
            summary = summary or result_data.get("summary", "")
            key_points = result_data.get("key_points", key_points)
            reasoning = result_data.get("reasoning", reasoning)

        # Final fallback to local record fields
        if (not decision or decision == "UNKNOWN") and record:
            decision = record.get("decision", "UNKNOWN")
            confidence = confidence or record.get("confidence", 0)
            reasoning = reasoning or record.get("reasoning", "")

        # Format date
        try:
            dt = datetime.fromisoformat(created_at)
            date_str = dt.strftime("%Y年%m月%d日 %H:%M")
        except Exception:
            date_str = created_at

        status_icon, status_text, _ = STATUS_CONFIG.get(status, ("⚪", status or "未知", "#9E9E9E"))
        elapsed_time, remaining_time = extract_task_timing(
            {"created_at": created_at, "updated_at": api_data.get("updated_at", "") if api_data else record.get("updated_at", "") if record else "", "status": status},
            result_data,
        )
        current_agent = result_data.get("current_agent", "") if isinstance(result_data, dict) else ""
        progress_pct = int(result_data.get("progress_pct", 0) or 0) if isinstance(result_data, dict) else 0
        progress_indeterminate = bool(result_data.get("is_progress_indeterminate")) if isinstance(result_data, dict) else False

        # Inject compact typography styles for tab/expander content
        st.markdown("""<style>
            .stTabContent h1 { font-size: 1.1rem !important; font-weight: 700; margin-top: 0.5rem; margin-bottom: 0.25rem; }
            .stTabContent h2 { font-size: 1.0rem !important; font-weight: 600; margin-top: 0.4rem; margin-bottom: 0.2rem; }
            .stTabContent h3 { font-size: 0.9rem !important; font-weight: 600; margin-top: 0.3rem; margin-bottom: 0.15rem; }
            .stTabContent h4 { font-size: 0.85rem !important; font-weight: 600; margin-top: 0.3rem; margin-bottom: 0.15rem; }
            .stTabContent p { font-size: 0.85rem !important; line-height: 1.5; margin-bottom: 0.3rem; }
            .stTabContent li { font-size: 0.85rem !important; line-height: 1.4; }
            .stTabContent ul, .stTabContent ol { margin-top: 0.2rem; margin-bottom: 0.3rem; }
            .stTabContent table { font-size: 0.8rem !important; }
            .stTabContent th { font-size: 0.8rem !important; padding: 4px 8px !important; }
            .stTabContent td { font-size: 0.8rem !important; padding: 4px 8px !important; }
            .stExpander h1, .stExpander h2, .stExpander h3, .stExpander h4 { font-size: 0.85rem !important; font-weight: 600; margin-top: 0.2rem; margin-bottom: 0.15rem; }
            .stExpander p { font-size: 0.8rem !important; line-height: 1.4; margin-bottom: 0.2rem; }
            .stExpander li { font-size: 0.8rem !important; line-height: 1.3; }
        </style>""", unsafe_allow_html=True)

        name = _get_stock_name(symbol)
        if name:
            st.markdown(
                f"<h4 style='margin:0 0 0.25rem 0;font-size:1.2rem;font-weight:700;'>📊 {symbol} <span style='font-size:0.75rem;color:#6B7280;font-weight:400;'>({name})</span> 分析详情</h4>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<h4 style='margin:0 0 0.25rem 0;font-size:1.2rem;font-weight:700;'>📊 {symbol} 分析详情</h4>",
                unsafe_allow_html=True,
            )
        st.caption(f"📅 {date_str} | {status_icon} {status_text}")

        st.divider()

        # Real-time progress section (only for PENDING/RUNNING tasks)
        if status in ("PENDING", "RUNNING"):
            st.markdown("<div style='font-size:0.9rem;font-weight:600;color:#374151;margin-bottom:0.5rem;'>🔄 实时分析进度</div>", unsafe_allow_html=True)
            agents_progress = result_data.get("agents_progress", {})

            st.progress(progress_pct / 100, text=f"整体进度: {progress_pct}%")

            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"⏱️ 已用时间: {format_time(elapsed_time)}")
            with col2:
                if remaining_time is not None and not progress_indeterminate:
                    st.caption(f"⏳ 预计剩余: {format_time(remaining_time)}")
                else:
                    st.caption("⏳ 预计剩余: 计算中...")

            current_step_name = STEP_NAMES.get(current_agent, current_agent or "分析处理中")
            current_step_desc = "正在持续接收流式进度更新" if progress_pct > 0 else "任务已创建，等待执行"
            st.info(f"{status_icon} **{current_step_name}** - {current_step_desc}")

            simplified_steps = simplify_step_status(agents_progress, current_agent)
            for step_id, step_name, step_status in simplified_steps:
                if step_status == "completed":
                    st.caption(f"✅ {step_name}")
                elif step_status == "in_progress":
                    st.caption(f"🔄 {step_name}")
                elif step_status == "failed":
                    st.caption(f"❌ {step_name}")

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("🔄 刷新进度", key=f"refresh_{task_id}"):
                    st.rerun()
            with col2:
                auto_refresh_key = f"auto_refresh_{task_id}"
                default_value = st.session_state.get(auto_refresh_key, True)
                auto_refresh = st.checkbox("🔄 自动刷新", value=default_value, key=auto_refresh_key)
                if auto_refresh and status == "RUNNING":
                    import time
                    time.sleep(3)
                    st.rerun()
        else:
            # Decision section for completed/failed tasks
            decision_colors = {
                "BUY": "green",
                "SELL": "red",
                "HOLD": "orange",
                "UNKNOWN": "gray"
            }

            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                st.markdown("<div style='font-size:0.9rem;font-weight:600;color:#374151;margin-bottom:0.5rem;'>📈 交易建议</div>", unsafe_allow_html=True)
                if analysis_error:
                    st.error("❌ 分析失败")
                else:
                    decision_text, color = DECISION_TEXT_MAP.get(decision, (decision, "gray"))
                    st.markdown(f"<div style='font-size:1.3rem;font-weight:700;color:{color};margin:0.25rem 0;'>{decision_text}</div>", unsafe_allow_html=True)
            with col2:
                st.markdown("<div style='font-size:0.9rem;font-weight:600;color:#374151;margin-bottom:0.5rem;'>📊 置信度</div>", unsafe_allow_html=True)
                if analysis_error:
                    with st.expander("查看错误详情"):
                        st.code(analysis_error, language=None)
                elif confidence > 0:
                    st.progress(confidence / 100, text=f"{confidence}%")
                else:
                    st.info("计算中...")
            with col3:
                st.markdown("<div style='font-size:0.9rem;font-weight:600;color:#374151;margin-bottom:0.5rem;'>⚠️ 风险等级</div>", unsafe_allow_html=True)
                if analysis_error:
                    st.write("未知")
                elif risk_level:
                    st.write(risk_level)
                else:
                    st.write("中等")

            metrics_col1, metrics_col2 = st.columns(2)
            with metrics_col1:
                st.caption(f"⏱️ 已用时间: {format_time(elapsed_time)}")
            with metrics_col2:
                st.caption("✅ 分析完成" if status == "COMPLETED" else "❌ 分析失败")

            st.divider()

        # Show reports in tabs for better readability
        # Get final_state from either API or local data
        final_state_for_tabs = None
        if api_data and api_data.get("final_state"):
            final_state_for_tabs = api_data["final_state"]
        elif result_data and result_data.get("final_state"):
            final_state_for_tabs = result_data["final_state"]

        if final_state_for_tabs:
            reports = {
                'final_trade_decision': '🎯 最终交易决策',
                'fundamentals_report': '💰 基本面分析',
                'market_report': '📈 市场分析',
                'sentiment_report': '💭 情绪分析',
                'news_report': '📰 新闻分析',
                'risk_assessment_report': '⚠️ 风险评估'
            }

            available_reports = {k: v for k, v in reports.items() if k in final_state_for_tabs and final_state_for_tabs[k]}
            if available_reports:
                st.markdown("<div style='font-size:0.9rem;font-weight:600;color:#374151;margin-bottom:0.5rem;'>📚 分析报告</div>", unsafe_allow_html=True)
                tabs = st.tabs(list(available_reports.values()))
                for i, (tab, (report_key, report_name)) in enumerate(zip(tabs, available_reports.items())):
                    with tab:
                        st.markdown(final_state_for_tabs[report_key])

        # Show LLM agent outputs if available (post-analysis review)
        llm_streams = None
        if api_data and api_data.get("llm_streams"):
            llm_streams = api_data["llm_streams"]
        elif result_data and result_data.get("llm_streams"):
            llm_streams = result_data["llm_streams"]

        if llm_streams and isinstance(llm_streams, dict) and any(llm_streams.values()):
            with st.expander("🤖 智能体详细输出 (LLM Streams)", expanded=False):
                st.caption("各分析智能体的完整输出文本，用于审计和调试")
                agent_display_names = {
                    "market_analyst": "📊 市场分析师",
                    "sentiment_analyst": "💭 情绪分析师",
                    "news_analyst": "📰 新闻分析师",
                    "fundamentals_analyst": "🏢 基本面分析师",
                    "market_index_analyst": "📈 大盘分析师",
                    "persona_agents": "🎭 投资大师人设分析",
                    "bull_researcher": "🐂 看涨研究员",
                    "bear_researcher": "🐻 看跌研究员",
                    "research_manager": "🔍 研究经理",
                    "trader": "💼 交易员",
                    "portfolio_manager": "👔 投资组合经理",
                }
                for agent_key, display_name in agent_display_names.items():
                    content = llm_streams.get(agent_key)
                    if content and isinstance(content, str) and content.strip():
                        with st.expander(display_name):
                            st.markdown(content)

        # Show individual persona signals if available
        persona_signals = None
        if api_data and api_data.get("result", {}).get("final_state", {}).get("persona_signals"):
            persona_signals = api_data["result"]["final_state"]["persona_signals"]
        elif result_data and result_data.get("final_state", {}).get("persona_signals"):
            persona_signals = result_data["final_state"]["persona_signals"]

        if persona_signals and isinstance(persona_signals, dict):
            persona_display_names = {
                "warren_buffett": ("🎩 沃伦·巴菲特", "价值投资"),
                "michael_burry": ("🔍 迈克尔·布瑞", "深度价值/逆向"),
                "nassim_taleb": ("🎲 纳西姆·塔勒布", "尾部风险/反脆弱"),
                "stanley_druckenmiller": ("🌍 斯坦利·德鲁肯米勒", "宏观趋势/动量"),
                "cathie_wood": ("🚀 凯瑟琳·伍德", "颠覆式创新"),
                "charlie_munger": ("🏛️ 查理·芒格", "护城河/思维模型"),
            }
            with st.expander("🎭 投资大师人设评估", expanded=False):
                st.caption("6 位投资大师基于量化数据和人设理念的独立评估")
                # Summary row
                bullish = sum(1 for s in persona_signals.values() if isinstance(s, dict) and s.get("signal") == "bullish")
                bearish = sum(1 for s in persona_signals.values() if isinstance(s, dict) and s.get("signal") == "bearish")
                neutral = sum(1 for s in persona_signals.values() if isinstance(s, dict) and s.get("signal") == "neutral")
                avg_conf = 0
                conf_count = 0
                for s in persona_signals.values():
                    if isinstance(s, dict) and s.get("confidence"):
                        avg_conf += s["confidence"]
                        conf_count += 1
                if conf_count > 0:
                    avg_conf = avg_conf // conf_count
                signal_color = "🔴" if bearish > bullish else ("🟢" if bullish > bearish else "🟡")
                st.markdown(f"**投票汇总**: {signal_color} 看涨 {bullish}/6 | 看跌 {bearish}/6 | 中性 {neutral}/6 | 平均置信度 {avg_conf}/100")
                st.divider()
                # Individual persona cards
                cols = st.columns(3)
                for idx, (name, (display, philosophy)) in enumerate(persona_display_names.items()):
                    sig = persona_signals.get(name, {})
                    if not isinstance(sig, dict):
                        continue
                    signal = sig.get("signal", "N/A")
                    confidence = sig.get("confidence", 0)
                    reasoning = sig.get("reasoning", "")
                    signal_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(signal, "⚪")
                    with cols[idx % 3]:
                        st.markdown(f"**{display}**")
                        st.caption(philosophy)
                        st.markdown(f"{signal_emoji} **{signal.upper()}** | 置信度: **{confidence}/100**")
                        if reasoning:
                            st.markdown(f"<div style='font-size:0.8rem;color:#666;'>{reasoning}</div>", unsafe_allow_html=True)

        # Show summary as markdown if available (outside tabs)
        if summary:
            st.markdown("<div style='font-size:0.9rem;font-weight:600;color:#374151;margin-bottom:0.5rem;'>📋 分析摘要</div>", unsafe_allow_html=True)
            st.markdown(summary)

        # Show technical indicators if available
        indicators = {}
        if record and isinstance(record, dict):
            indicators = record.get("indicators", {})
        if not isinstance(indicators, dict):
            indicators = {}
        if indicators:
            with st.expander("📈 技术指标"):
                # Display indicators in a more readable format
                if isinstance(indicators, dict):
                    for key, value in indicators.items():
                        col_k, col_v = st.columns([1, 2])
                        with col_k:
                            st.write(f"**{key}**")
                        with col_v:
                            if isinstance(value, (int, float)):
                                st.write(f"{value:.4f}" if isinstance(value, float) else value)
                            else:
                                st.write(str(value))
                else:
                    st.json(indicators)

        # Execution info
        execution_time = raw_result.get("execution_time", 0) if isinstance(raw_result, dict) else 0
        if execution_time:
            st.caption(f"⏱️ 执行时间: {execution_time:.2f}秒")

        st.divider()

        # Back button
        if st.button("← 返回历史列表", use_container_width=True):
            st.session_state.current_view = "history"
            st.session_state.selected_task_id = None
            st.rerun()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        st.error("历史详情页面加载失败，请稍后重试")


def format_time(seconds: int) -> str:
    """格式化秒数为可读时间"""
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
