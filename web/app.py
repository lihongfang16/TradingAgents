"""TradingAgents - AI股票分析 Streamlit主应用"""
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import streamlit as st
import requests

# 添加项目根目录到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.components.sidebar import render_sidebar
from web.components.analysis_form import render_analysis_form
from web.components.progress import render_progress, render_results
from web.components.history_manager import render_history_manager, render_history_detail
from web.components.watchlist_manager import render_watchlist_manager

# API配置
API_URL = os.getenv("API_URL", "http://127.0.0.1:8002")


def poll_for_result(task_id: str, api_url: str, max_attempts: int = 60, sleep_seconds: int = 2) -> Optional[dict[str, Any]]:
    """
    轮询获取分析结果。
    
    Args:
        task_id: 任务ID
        api_url: API基础URL
        max_attempts: 最大轮询次数
        sleep_seconds: 每次轮询间隔秒数
    
    Returns:
        结果字典，失败返回None
    """
    result_url = f"{api_url}/api/v1/analysis/{task_id}"
    
    for attempt in range(max_attempts):
        try:
            response = requests.get(result_url, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 202:
                # 任务还在处理中
                pass
            elif response.status_code == 404:
                st.warning(f"任务不存在或已过期: {task_id}")
                return None
            else:
                st.warning(f"API返回状态码: {response.status_code}")
                
        except requests.exceptions.Timeout:
            st.warning(f"请求超时 (尝试 {attempt + 1}/{max_attempts})")
        except requests.exceptions.ConnectionError:
            st.error("无法连接到API服务，请检查服务是否运行")
            return None
        except Exception as e:
            st.error(f"轮询出错: {str(e)}")
            return None
        
        if attempt < max_attempts - 1:
            time.sleep(sleep_seconds)
    
    st.warning("轮询超时，任务可能仍在处理中")
    return None


def main():
    """主应用入口"""
    # 页面配置
    st.set_page_config(
        page_title="TradingAgents - AI股票分析",
        page_icon="📈",
        layout="wide"
    )
    
    # 渲染侧边栏配置
    llm_config = render_sidebar()
    
    # 初始化 session state
    if "current_view" not in st.session_state:
        st.session_state.current_view = "analysis"
    if "selected_task_id" not in st.session_state:
        st.session_state.selected_task_id = None
    
    # 导航按钮
    st.divider()
    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("📝 新建分析", use_container_width=True, type="primary"):
            st.session_state.current_view = "analysis"
            st.session_state.selected_task_id = None
            st.rerun()
    with nav_col2:
        if st.button("📊 自选股管理", use_container_width=True):
            st.session_state.current_view = "watchlist"
            st.rerun()
    with nav_col3:
        if st.button("📚 历史记录", use_container_width=True):
            st.session_state.current_view = "history"
            st.rerun()
    st.divider()
    
    # 根据 current_view 渲染不同内容
    if st.session_state.current_view == "watchlist":
        render_watchlist_manager()
        return
    
    if st.session_state.current_view == "history":
        if st.session_state.selected_task_id:
            render_history_detail(st.session_state.selected_task_id)
            if st.button("← 返回列表", key="back_to_history_list"):
                st.session_state.selected_task_id = None
                st.rerun()
        else:
            selected_task_id = render_history_manager()
            if selected_task_id:
                st.session_state.selected_task_id = selected_task_id
                st.rerun()
        return
    
    # current_view == "analysis" 时，渲染分析表单
    form_data = render_analysis_form()
    
    # 表单提交处理
    if form_data["submitted"]:
        # 验证输入
        symbol = form_data.get("symbol", "").strip()
        analysts = form_data.get("analysts", [])
        
        if not symbol:
            st.error("请输入股票代码")
            return
        
        if not analysts:
            st.error("请至少选择一个分析师")
            return
        
        # 构建请求payload
        payload = {
            "symbol": symbol,
            "date": form_data.get("date", ""),
            "source": form_data.get("source", "mairui"),
            "exchange": form_data.get("exchange", "CN"),
            "analysts": analysts,
            "depth": form_data.get("depth", "normal"),
            "force_refresh": form_data.get("force_refresh", False),
            "llm_provider": llm_config.get("llm_provider", "minimax"),
            "deep_model": llm_config.get("deep_model", "MiniMax-M2.7-highspeed"),
            "quick_model": llm_config.get("quick_model", "MiniMax-M2.7-highspeed"),
            "enable_memory": llm_config.get("enable_memory", True),
            "debug_mode": llm_config.get("debug_mode", False),
        }
        
        try:
            # 提交分析任务
            with st.spinner("正在提交分析任务..."):
                response = requests.post(
                    f"{API_URL}/api/v1/analysis/",
                    json=payload,
                    timeout=30
                )
            
            if response.status_code == 200 or response.status_code == 202:
                result = response.json()
                task_id = result.get("task_id")
                
                if not task_id:
                    st.error("未获取到任务ID，请检查API响应")
                    st.json(result)
                    return
                
                st.success(f"任务已提交，任务ID: {task_id}")

                # 切换到历史视图查看进度
                st.session_state.current_view = "history"
                st.session_state.selected_task_id = task_id
                st.rerun()
                    
            elif response.status_code == 422:
                st.error("请求参数验证失败，请检查输入")
                st.json(response.json())
            elif response.status_code == 500:
                st.error("服务器内部错误，请稍后重试")
            else:
                st.error(f"API返回错误: {response.status_code}")
                try:
                    st.json(response.json())
                except:
                    st.text(response.text)
                    
        except requests.exceptions.ConnectionError:
            st.error(f"无法连接到API服务 ({API_URL})，请确保服务正在运行")
        except requests.exceptions.Timeout:
            st.error("请求超时，请稍后重试")
        except Exception as e:
            st.error(f"发生错误: {str(e)}")
    else:
        # 欢迎信息
        st.title("📈 TradingAgents - AI股票分析")
        st.markdown("""
        欢迎使用AI股票分析系统！请按照以下步骤操作：
        
        1. **配置LLM** - 在左侧边栏选择AI模型提供商和参数
        2. **填写分析参数** - 输入股票代码、选择分析师和研究深度
        3. **开始分析** - 点击按钮提交分析任务
        
        系统将自动协调多个AI智能体进行市场分析、新闻分析、基本面分析和社交情绪分析，
        最终给出综合交易建议。
        """)


if __name__ == "__main__":
    main()
