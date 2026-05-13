"""Streamlit Progress Display and Results Rendering Components."""
import streamlit as st
import requests
import json
import time
from typing import Dict, Any, Optional, Generator


def render_progress(task_id: str, api_url: str) -> Generator[Dict[str, Any], None, None]:
    """
    Render progress display with SSE streaming from FastAPI backend.
    
    Args:
        task_id: The task ID returned from analysis submission
        api_url: Base API URL (e.g., "http://localhost:8000")
    
    Yields:
        Dict with progress info:
            - progress_pct (int): 0-100 progress percentage
            - current_agent (str): Name of currently running agent
            - status (str): Status message
            - logs (list): Recent log entries (max 10)
            - done (bool): Whether analysis is complete
    
    Example:
        >>> for progress in render_progress("task_123", "http://localhost:8000"):
        ...     st.write(f"Progress: {progress['progress_pct']}%")
    """
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_container = st.container()
    log_entries: list = []
    
    sse_url = f"{api_url}/api/v1/analysis/{task_id}/progress"
    
    try:
        # Use requests to stream SSE
        with requests.get(sse_url, stream=True, timeout=30) as response:
            response.raise_for_status()
            
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    # SSE format: "data: {...json...}"
                    if line.startswith("data: "):
                        json_str = line[6:]  # Remove "data: " prefix
                        try:
                            data = json.loads(json_str)
                        except json.JSONDecodeError:
                            continue
                        
                        # Extract progress info
                        progress_pct = data.get("progress_pct", 0)
                        current_agent = data.get("current_agent", "")
                        status = data.get("status", "处理中...")
                        
                        # Update logs (keep last 10)
                        new_logs = data.get("logs", [])
                        log_entries.extend(new_logs)
                        log_entries = log_entries[-10:]
                        
                        # Update UI
                        progress_bar.progress(progress_pct / 100)
                        status_text.text(f"{status} ({current_agent})" if current_agent else status)
                        
                        # Update log display
                        with log_container:
                            st.caption("📋 最新日志")
                            for log in log_entries[-10:]:
                                # Handle both dict format (new) and string format (legacy)
                                if isinstance(log, dict):
                                    timestamp = log.get("timestamp", "")[:19] if log.get("timestamp") else ""
                                    agent = log.get("agent", "")
                                    message = log.get("message", "")
                                    log_text = f"[{timestamp}] {agent}: {message}" if agent else f"[{timestamp}] {message}"
                                else:
                                    log_text = str(log)
                                st.text(log_text)
                        
                        # Yield control back to Streamlit
                        yield data
                        
                        # Check if done
                        if data.get("done", False) or data.get("status") == "completed":
                            break
                        
    except requests.exceptions.Timeout:
        status_text.error("请求超时，请检查API服务是否运行")
        yield {"error": "timeout", "done": True}
    except requests.exceptions.ConnectionError:
        status_text.error("无法连接到API服务")
        yield {"error": "connection_error", "done": True}
    except requests.exceptions.HTTPError as e:
        status_text.error(f"HTTP错误: {e}")
        yield {"error": str(e), "done": True}
    except Exception as e:
        status_text.error(f"未知错误: {str(e)}")
        yield {"error": str(e), "done": True}


def render_results(task: Dict[str, Any]) -> None:
    """
    Render the final analysis results.
    
    Args:
        task: Task result dict with keys:
            - status (str): "success" or "error"
            - signal (dict): Trading signal with decision, confidence, risk_score
            - final_state (dict): Full agent state
            - error (str): Error message if status is "error"
    """
    if task.get("status") == "error":
        st.error(f"分析失败: {task.get('error', '未知错误')}")
        return
    
    signal = task.get("signal", {})
    final_state = task.get("final_state", {})
    
    # Decision Display
    st.subheader("📊 分析结果")
    
    decision = signal.get("decision", "HOLD")
    confidence = signal.get("confidence", 0.0)
    risk_score = signal.get("risk_score", 0.0)
    
    # Decision badge with color (5-tier rating support)
    decision_colors = {
        "BUY": "🟢",
        "OVERWEIGHT": "🟢",
        "HOLD": "🟡",
        "UNDERWEIGHT": "🔴",
        "SELL": "🔴"
    }
    decision_icon = decision_colors.get(decision, "⚪")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            label="交易决策",
            value=f"{decision_icon} {decision}",
            help="基于多智能体分析的交易建议"
        )
    
    with col2:
        st.metric(
            label="置信度",
            value=f"{confidence * 100:.1f}%",
            help="决策的置信水平"
        )
    
    with col3:
        risk_label = "低" if risk_score < 0.3 else "中" if risk_score < 0.7 else "高"
        st.metric(
            label="风险等级",
            value=f"{risk_label} ({risk_score:.2f})",
            help="1=高风险, 0=低风险"
        )
    
    st.divider()
    
    # Signal Details
    if signal:
        st.subheader("📈 信号详情")
        
        with st.expander("查看完整信号数据", expanded=False):
            st.json(signal)
    
    # Final State / Agent Insights
    if final_state:
        st.subheader("🧠 智能体分析摘要")
        
        # Extract agent thoughts if available
        agent_thoughts = final_state.get("agent_thoughts", {})
        if agent_thoughts:
            for agent_name, thought in agent_thoughts.items():
                with st.expander(f"💭 {agent_name}", expanded=False):
                    st.text(thought)
        else:
            # Fallback: show entire final_state
            with st.expander("查看完整状态数据", expanded=False):
                st.json(final_state)
    
    # Timestamp
    timestamp = task.get("timestamp", "")
    if timestamp:
        st.caption(f"分析完成时间: {timestamp}")


if __name__ == "__main__":
    # Quick test
    import streamlit as st
    st.set_page_config(page_title="Progress Test")
    
    st.write("### 进度条测试")
    
    # Mock render_progress usage
    class MockProgress:
        def __init__(self):
            self.progress = 0
    
    mock = MockProgress()
    
    # Example task result
    example_task = {
        "status": "success",
        "progress_pct": 100,
        "signal": {
            "decision": "BUY",
            "confidence": 0.85,
            "risk_score": 0.25,
            "reasoning": "基于市场趋势和基本面分析"
        },
        "final_state": {
            "agent_thoughts": {
                "market": "市场呈现上升趋势",
                "fundamentals": "财务指标稳健"
            }
        },
        "timestamp": "2026-03-24T12:00:00"
    }
    
    if st.button("显示结果"):
        render_results(example_task)
