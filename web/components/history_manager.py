"""History Manager Component for TradingAgents Web UI."""
import json
import os
import sys
import traceback
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st


# History storage path - store in project directory for persistence
HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
DELETED_IDS_FILE = os.path.join(HISTORY_DIR, "deleted_ids.json")

# API URL - use same default as app.py
API_URL = os.environ.get("API_URL", "http://localhost:8005")


def ensure_history_dir():
    """Ensure history directory exists."""
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)


def load_deleted_ids() -> set:
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


def save_deleted_ids(deleted_ids: set):
    """Save deleted task IDs to tombstone file."""
    ensure_history_dir()
    with open(DELETED_IDS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'deleted_ids': list(deleted_ids)}, f, indent=2)


def load_history() -> List[Dict[str, Any]]:
    """Load analysis history from API (primary) with local cache fallback.
    
    PostgreSQL is the source of truth. Local JSON is only used as:
    - Cache when API is unavailable
    - Export/backup (not active merge source)
    
    Returns:
        List of history records from API (or local cache if API down)
    """
    ensure_history_dir()
    
    # Helper to extract decision from final_state messages
    def extract_decision_from_result(result_data):
        """Extract decision, confidence from result.final_state.messages if available."""
        decision = ""
        confidence = 0
        
        final_state = result_data.get("final_state", {}) if isinstance(result_data, dict) else {}
        if not final_state:
            return decision, confidence
        
        messages = final_state.get("messages", [])
        if messages:
            # Get last message content
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                content = last_msg.get("content", "")
            elif hasattr(last_msg, 'content'):
                content = last_msg.content
            else:
                content = str(last_msg) if last_msg else ""
            
            # Extract decision from "FINAL TRANSACTION PROPOSAL: **BUY/SELL/HOLD**"
            if "FINAL TRANSACTION PROPOSAL:" in content:
                proposal_section = content.split("FINAL TRANSACTION PROPOSAL:")[-1].split("---")[0].strip()
                if "**买入**" in proposal_section or "BUY" in proposal_section.upper():
                    decision = "BUY"
                elif "**卖出**" in proposal_section or "SELL" in proposal_section.upper():
                    decision = "SELL"
                elif "**持有**" in proposal_section or "HOLD" in proposal_section.upper():
                    decision = "HOLD"
        
        return decision, confidence
    
    # PRIMARY: Try to fetch from API (PostgreSQL is source of truth)
    api_records = []
    api_available = False
    try:
        resp = requests.get(f"{API_URL}/api/v1/analysis/", params={"limit": 50}, timeout=5)
        if resp.status_code == 200:
            api_available = True
            api_tasks = resp.json()
            for task in api_tasks:
                result_data = task.get("result", {}) or {}
                decision, confidence = extract_decision_from_result(result_data)
                
                # Convert API task to history record format
                record = {
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
                    "raw_result": result_data
                }
                api_records.append(record)
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
    records = load_history()
    
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
            timeout=5,
        )
        if resp.status_code == 204:
            api_ok = True
        elif resp.status_code == 404:
            st.error("任务不存在")
            return False
        else:
            st.error(f"删除失败: {resp.status_code}")
            return False
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
    records = load_history()
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


def render_history_manager() -> Optional[str]:
    """Render history manager UI.
    
    Returns:
        Selected task_id if user clicks view, None otherwise
    """
    try:
        st.header("📚 分析历史")

        records = load_history()

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
        
        # Pre-compute running tasks count and limit progress fetches to avoid N+1
        running_tasks = [r for r in filtered_records if r.get("status") in ("PENDING", "RUNNING")]
        progress_fetch_count = 0

        for idx, record in enumerate(filtered_records):
            task_id = record.get("task_id", "")
            symbol = record.get("symbol", "Unknown")
            created_at = record.get("created_at", "")
            updated_at = record.get("updated_at", "")
            status = record.get("status", "")
            decision = record.get("decision", "")

            # Format date
            try:
                dt = datetime.fromisoformat(created_at)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = created_at[:16] if created_at else "Unknown"

            # Status emoji and text
            status_emoji = {
                "PENDING": "⏳",
                "RUNNING": "🔄",
                "COMPLETED": "✅",
                "FAILED": "❌"
            }.get(status, "⚪")

            # Translate decision to Chinese
            decision_text_map = {
                "BUY": "买入",
                "SELL": "卖出",
                "HOLD": "持有",
                "UNKNOWN": "未知"
            }
            decision_cn = decision_text_map.get(decision, decision) if decision else ""

            status_text = {
                "PENDING": "等待中",
                "RUNNING": "分析中",
                "COMPLETED": decision_cn if decision_cn else "完成",
                "FAILED": "失败"
            }.get(status, status)

            # Single row layout: symbol | status/progress | date | buttons
            col1, col2, col3, col4, col5 = st.columns([1.5, 3, 1.2, 1, 1])

            with col1:
                st.write(f"**{symbol}**")
            with col2:
                if status in ("PENDING", "RUNNING"):
                    # Only fetch progress for first 3 running tasks to avoid N+1
                    if progress_fetch_count < 3:
                        progress_info = get_task_progress(task_id)
                        progress_fetch_count += 1  # FIX: increment counter after fetch
                        if progress_info:
                            prog = progress_info.get("progress", 0)
                            elapsed = progress_info.get("elapsed", 0)
                            remaining = progress_info.get("remaining", 0)
                            msg = progress_info.get("message", "")
                            elapsed_str = format_duration(int(elapsed)) if isinstance(elapsed, (int, float)) else str(elapsed)
                            
                            # Show remaining time or overtime indicator
                            # If progress is near 100%, treat as completed even if status hasn't updated yet
                            if prog >= 99 or remaining > 0:
                                if remaining > 0:
                                    remaining_str = format_duration(int(remaining))
                                    progress_text = f"📊 {int(prog)}% | ⏱️ {elapsed_str} | ⏳ 剩余: {remaining_str}"
                                else:
                                    # Progress near 100% or remaining = 0, task essentially complete
                                    # Calculate actual duration from updated_at - created_at
                                    # But if they are nearly identical (< 1 second), updated_at wasn't properly set
                                    # Fall back to elapsed from progress_info
                                    use_elapsed = True
                                    if updated_at and created_at:
                                        try:
                                            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                            updated_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                                            actual_duration = (updated_dt - created_dt.replace(tzinfo=None)).total_seconds()
                                            # Only use actual duration if > 1 second (updated_at was properly set)
                                            if actual_duration > 1:
                                                elapsed_str = format_duration(int(actual_duration))
                                                use_elapsed = False
                                        except Exception:
                                            pass  # Fall through to use elapsed
                                    if use_elapsed:
                                        # updated_at wasn't set properly, use elapsed from progress_info
                                        pass  # Keep original elapsed_str
                                    progress_text = f"✅ 分析完成 | ⏱️ {elapsed_str}"
                            else:
                                # Task still in progress, show overtime warning
                                is_running = status in ("PENDING", "RUNNING")
                                overtime = elapsed > 600  # More than 10 minutes
                                long_running = elapsed > 900  # More than 15 minutes
                                if long_running and is_running:
                                    progress_text = f"📊 {int(prog)}% | ⏱️ {elapsed_str} | 🔄 长时间运行中"
                                elif overtime and is_running:
                                    progress_text = f"📊 {int(prog)}% | ⏱️ {elapsed_str} | ⚠️ 超时运行中"
                                else:
                                    progress_text = f"📊 {int(prog)}% | ⏱️ {elapsed_str} | ⏳ 即将完成"
                            
                            st.progress(prog / 100, text=progress_text)
                            if msg:
                                st.caption(f"📍 {msg[:30]}...")
                        else:
                            st.write("🔄 分析中...")
                    else:
                        st.write("🔄 分析中...")
                else:
                    # Show duration for completed/failed tasks
                    # Check if task actually failed (result has error)
                    raw_result = record.get("raw_result", {}) or {}
                    result_error = None
                    if isinstance(raw_result, dict):
                        result_error = raw_result.get("error")
                    
                    if result_error:
                        # Task failed but status is COMPLETED
                        st.write(f"❌ 分析失败")
                    else:
                        # Normal completed task
                        updated_at = record.get("updated_at", "")
                        duration_text = ""
                        if created_at and updated_at:
                            try:
                                created_dt = datetime.fromisoformat(created_at)
                                updated_dt = datetime.fromisoformat(updated_at)
                                duration = (updated_dt - created_dt).total_seconds()
                                duration_text = f" (⏱️ {format_duration(int(duration))})"
                            except Exception:
                                pass
                        st.write(f"{status_emoji} {status_text}{duration_text}")
            with col3:
                st.caption(date_str)
            with col4:
                if st.button("查看", key=f"view_{task_id}", help="查看详情", use_container_width=True):
                    selected_task_id = task_id
            with col5:
                if st.button("删除", key=f"del_{task_id}", help="删除记录", use_container_width=True):
                    delete_from_history(task_id)
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
                    # Extract decision
                    if "**BUY**" in content or "买入" in content:
                        decision = "BUY"
                    elif "**SELL**" in content or "卖出" in content:
                        decision = "SELL"
                    elif "**HOLD**" in content or "持有" in content:
                        decision = "HOLD"

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

        # Fallback to result_data fields
        if isinstance(result_data, dict) and not recommendation:
            recommendation = result_data.get("recommendation", "")
            decision = result_data.get("decision", decision)
            confidence = result_data.get("confidence", confidence)
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

        st.header(f"📊 {symbol} 分析详情")
        st.caption(f"📅 {date_str} | 状态: {status}")

        st.divider()

        # Decision section
        decision_colors = {
            "BUY": "green",
            "SELL": "red",
            "HOLD": "orange",
            "UNKNOWN": "gray"
        }

        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            st.subheader("📈 交易建议")
            if analysis_error:
                st.error("❌ 分析失败")
            else:
                decision_text = {"BUY": "买入", "SELL": "卖出", "HOLD": "持有"}.get(decision, decision)
                color = decision_colors.get(decision, "gray")
                st.markdown(f"### <span style='color: {color}'>{decision_text}</span>", unsafe_allow_html=True)
        with col2:
            st.subheader("📊 置信度")
            if analysis_error:
                with st.expander("查看错误详情"):
                    st.code(analysis_error, language=None)
            elif confidence > 0:
                st.progress(confidence / 100, text=f"{confidence}%")
            else:
                st.info("计算中...")
        with col3:
            st.subheader("⚠️ 风险等级")
            if analysis_error:
                st.write("未知")
            elif risk_level:
                st.write(risk_level)
            else:
                st.write("中等")

        st.divider()

        # Show reports in tabs for better readability
        if api_data and final_state:
            tabs_to_show = []

            if final_state.get("market_report"):
                tabs_to_show.append(("📊 市场分析", final_state.get("market_report", "")))
            if final_state.get("sentiment_report"):
                tabs_to_show.append(("💭 情绪分析", final_state.get("sentiment_report", "")))
            if final_state.get("news_report"):
                tabs_to_show.append(("📰 新闻分析", final_state.get("news_report", "")))
            if final_state.get("fundamentals_report"):
                tabs_to_show.append(("🏢 基本面", final_state.get("fundamentals_report", "")))

            if len(tabs_to_show) > 0:
                tabs = st.tabs([t[0] for t in tabs_to_show])
                for i, (label, content) in enumerate(tabs_to_show):
                    with tabs[i]:
                        st.markdown(content)

        # Show summary as markdown if available (outside tabs)
        if summary:
            st.subheader("📋 分析摘要")
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
