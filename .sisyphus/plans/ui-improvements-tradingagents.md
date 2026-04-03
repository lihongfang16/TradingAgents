# TradingAgents A-share UI 改进计划

## 状态
**[REVISED]** - 根据 Momus 审查和 Oracle 技术分析更新

## 参考来源
TradingAgents-CN (`D:\1.MyProjects\Other\tradingAgents-cn`):
- `web/components/async_progress_display.py` - 进度显示组件
- `web/components/analysis_results.py` - 分析结果展示

## 核心问题（已识别）

### 问题 1：进度显示失真（60% 卡住）
**根因**: `tradingagents/core/analysis_runner.py` 只在 `propagate()` 开始时上报一次 60%，之后直到返回前都不再更新。

**解决方案**: 使用 LangGraph 流式更新（streaming）跟踪真实节点完成事件

### 问题 2：时间估算不准确
**根因**: 当前使用硬编码估算（600s），没有基于实际执行数据

**解决方案**: 基于历史数据分析预估，或使用不确定进度显示（spinner）代替精确百分比

---

## 任务 0：后端进度精度修复（优先）

### 0.1 修改 `tradingagents/graph/propagation.py`
支持可配置的 stream_mode：
```python
def get_graph_args(self, callbacks=None, stream_mode="values", version=None):
    config = {"recursion_limit": self.max_recur_limit}
    if callbacks:
        config["callbacks"] = callbacks
    args = {"config": config, "stream_mode": stream_mode}
    if version:
        args["version"] = version
    return args
```

### 0.2 修改 `tradingagents/graph/trading_graph.py`
使用 graph.stream() 替代阻塞式 invoke，支持进度回调：
```python
def propagate(self, company_name, trade_date, progress_callback=None):
    init_agent_state = self.propagator.create_initial_state(company_name, trade_date)
    args = self.propagator.get_graph_args(
        stream_mode=["updates", "values"],
        version="v2",
    )
    
    final_state = None
    for chunk in self.graph.stream(init_agent_state, **args):
        if chunk["type"] == "updates" and progress_callback:
            for node_name, state_update in chunk["data"].items():
                progress_callback({"node": node_name, "state": state_update})
        elif chunk["type"] == "values":
            final_state = chunk["data"]
    
    self.curr_state = final_state
    return final_state, self.process_signal(final_state["final_trade_decision"])
```

### 0.3 修改 `tradingagents/core/analysis_runner.py`
节点到步骤的映射：
```python
NODE_TO_STEP = {
    "Market Analyst": "market_analyst",
    "Social Analyst": "sentiment_analyst",
    "News Analyst": "news_analyst",
    "Fundamentals Analyst": "fundamentals_analyst",
    "Bull Researcher": "bull_researcher",
    "Bear Researcher": "bear_researcher",
    "Trader": "trader",
    "Portfolio Manager": "portfolio_manager",
}
RISK_NODES = {"Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"}
IGNORE_NODES = {
    "tools_market", "tools_social", "tools_news", "tools_fundamentals",
    "Msg Clear Market", "Msg Clear Social", "Msg Clear News", "Msg Clear Fundamentals",
}
```

进度计算（基于阶段）：
- graph_setup: 0-10%
- analysts: 10-55%
- bull/bear debate: 60-74%
- trader: 80%
- risk debate: 85-94%
- portfolio manager: 95-100%

---

## 改进目标
改进历史任务列表和详情页的进度显示与内容展示

---

## 任务 1：历史列表改进 (history_manager.py - render_history_manager)

### 当前问题
- 列表显示过于简单，只有状态和日期
- 运行中任务不显示进度信息
- 布局不够清晰

### 改进内容

#### 1.1 卡片式布局改进
```python
# 新的布局结构
col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1.5])

with col1:
    # 股票代码作为标题
    st.markdown(f"### 📊 {symbol}")
    # 时间作为副标题
    st.caption(f"🕐 {date_str}")

with col2:
    # 根据状态显示不同信息
    if status == "RUNNING":
        # 显示进度条和当前步骤
        st.progress(progress_pct / 100, text=f"{progress_pct}%")
        st.caption(f"📍 当前: {step_name}")
    elif status == "COMPLETED":
        # 显示决策结果
        st.markdown(f"**<span style='color: {decision_color};'>{decision_cn}</span>**", unsafe_allow_html=True)
        st.caption(f"⏱️ 耗时: {duration_text}")
```

#### 1.2 步骤名称映射
```python
step_names = {
    "graph_setup": "初始化分析图",
    "market_analyst": "市场分析师",
    "sentiment_analyst": "情绪分析师",
    "news_analyst": "新闻分析师",
    "fundamentals_analyst": "基本面分析师",
    "bull_researcher": "看涨研究员",
    "bear_researcher": "看跌研究员",
    "trader": "交易员",
    "risk_manager": "风控经理",
    "portfolio_manager": "投资组合经理",
    "propagate": "多智能体分析"
}
```

#### 1.3 状态配置
```python
status_config = {
    "PENDING": ("⏳", "等待中", "#FFA500"),
    "RUNNING": ("🔄", "分析中", "#2196F3"),
    "COMPLETED": ("✅", "完成", "#4CAF50"),
    "FAILED": ("❌", "失败", "#F44336")
}
```

#### 1.4 决策颜色映射
```python
decision_text_map = {
    "BUY": ("买入", "#4CAF50"),
    "SELL": ("卖出", "#F44336"),
    "HOLD": ("持有", "#FF9800"),
    "UNKNOWN": ("未知", "#9E9E9E")
}
```

---

## 任务 2：详情页改进 (history_manager.py - render_history_detail)

### 当前问题
- 实时进度部分信息不够清晰
- 报告内容没有使用标签页组织
- 缺少时间指标显示
- 刷新控制不够完善

### 改进内容

#### 2.1 时间指标显示（运行中任务）
```python
# 在进度部分添加时间信息
col1, col2 = st.columns(2)
with col1:
    st.caption(f"⏱️ 已用时间: {format_time(elapsed_time)}")
with col2:
    if status == "completed":
        st.caption("✅ 分析完成")
    elif status == "failed":
        st.caption("❌ 分析失败")
    else:
        st.caption(f"⏳ 预计剩余: {format_time(remaining_time)}")
```

#### 2.2 简化步骤显示
```python
# 简化进度显示，只显示核心信息
st.progress(min(progress_percentage / 100.0, 1.0))
st.info(f"{status_icon} **{current_step_name}** - {current_step_description}")
```

#### 2.3 刷新控制
```python
# 添加刷新控制按钮
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 刷新进度", key=f"refresh_{task_id}"):
        st.rerun()
with col2:
    auto_refresh_key = f"auto_refresh_{task_id}"
    default_value = st.session_state.get(auto_refresh_key, True)
    auto_refresh = st.checkbox("🔄 自动刷新", value=default_value, key=auto_refresh_key)
    if auto_refresh and status == "RUNNING":
        time.sleep(3)
        st.rerun()
```

#### 2.4 报告标签页（已完成任务）
```python
# 使用标签页组织不同报告
reports = {
    'final_trade_decision': '🎯 最终交易决策',
    'fundamentals_report': '💰 基本面分析',
    'technical_report': '📈 技术面分析',
    'market_sentiment_report': '💭 市场情绪分析',
    'risk_assessment_report': '⚠️ 风险评估',
    'news_analysis_report': '📰 新闻分析'
}

if reports:
    tab_names = list(reports.values())
    tabs = st.tabs(tab_names)
    for i, (tab, (report_key, report_name)) in enumerate(zip(tabs, reports.items())):
        with tab:
            if report_key in result_data:
                st.markdown(result_data[report_key])
```

---

## 任务 3：添加时间格式化函数

```python
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
```

---

## 文件修改清单

1. **web/components/history_manager.py**
   - 修改 `render_history_manager()` 函数（约第632-717行）
   - 修改 `render_history_detail()` 函数（约第740-1070行）
   - 添加 `format_time()` 辅助函数

---

## 预期效果

### 历史列表
- 更清晰的卡片式布局
- 运行中任务显示实时进度
- 已完成任务显示决策结果和耗时

### 详情页
- 时间指标清晰显示
- 报告内容使用标签页组织
- 更好的刷新控制
- 进度可视化改进

---

## 执行优先级（修正）

1. **最高优先级**：任务 0 - 后端进度精度修复（必须先解决根因）
2. 高优先级：任务 1 - 历史列表改进
3. 高优先级：任务 2 - 详情页时间指标和刷新控制
4. 中优先级：任务 3 - 报告标签页组织

---

## 任务 4：时间估算方案

### 方案选择：混合方案

#### 4.1 后端提供已用时间
在 `AnalysisTask` 模型中添加 `elapsed_time` 字段，由后端计算：
```python
# webapi/services/analysis_service.py - _update_task_progress
elapsed_time = (datetime.now() - task.created_at).total_seconds()
task.elapsed_time = int(elapsed_time)
```

#### 4.2 预估时间策略
- **方案 A**: 基于历史数据（需要额外实现）
- **方案 B**: 基于分析师数量估算（已实现但粗糙）
- **推荐方案**: 不确定进度显示 - 在长时间运行的步骤（如 propagate）中，使用 spinner 代替精确百分比

#### 4.3 UI 降级显示
当无法准确预估剩余时间时，显示 "计算中..." 或仅显示已用时间：
```python
if remaining_time > 0 and status == "RUNNING":
    st.metric("预计剩余", format_time(remaining_time))
else:
    st.metric("预计剩余", "计算中...")
```

---

## 任务 5：可执行 QA 场景

### QA 1：后端进度精度（任务 0）
**工具**: curl, Python
**步骤**:
1. 启动 API 服务: `python run_api.py`
2. 创建分析任务: `curl -X POST http://localhost:8005/api/v1/analysis/ -d '{"symbol": "000001", "analysts": ["market"]}'`
3. 每 5 秒查询任务进度: `curl http://localhost:8005/api/v1/analysis/{task_id}`
4. 观察 `progress_pct` 字段是否平滑增加（不是一直停留在 60%）
5. 验证 `current_agent` 是否正确更新

**预期结果**:
- 进度百分比从 0% 逐步增加到 100%
- 在 propagate 阶段也能看到进度变化
- 当前步骤正确显示正在执行的 agent

### QA 2：历史列表显示（任务 1）
**工具**: 浏览器访问 http://localhost:8501
**步骤**:
1. 打开 Streamlit UI，进入"历史记录"页面
2. 观察列表布局是否为卡片式
3. 如果有运行中任务，验证：
   - 是否显示进度条
   - 是否显示当前步骤名称（中文）
   - 进度条是否实时更新
4. 如果有已完成任务，验证：
   - 是否显示决策结果（买入/卖出/持有）带颜色
   - 是否显示分析耗时

**预期结果**:
- 卡片式布局清晰美观
- 运行中任务显示进度条和中文步骤名
- 已完成任务显示彩色决策结果和耗时

### QA 3：详情页显示（任务 2）
**工具**: 浏览器访问 http://localhost:8501
**步骤**:
1. 点击历史列表中的"查看"按钮进入详情页
2. 对于运行中任务，验证：
   - 是否显示已用时间
   - 刷新按钮是否有效
   - 自动刷新复选框是否可用
   - 勾选自动刷新后，页面是否每 3 秒刷新
3. 对于已完成任务，验证：
   - 是否以标签页组织不同报告
   - 是否能切换不同报告查看

**预期结果**:
- 时间指标清晰显示
- 刷新控制正常工作
- 报告标签页可正常切换

### QA 4：时间格式化函数（任务 3）
**工具**: Python REPL
**步骤**:
```python
from web.components.history_manager import format_time
print(format_time(45))      # 预期: "45秒"
print(format_time(125))     # 预期: "2分5秒"
print(format_time(3665))    # 预期: "1小时1分"
```

**预期结果**: 所有测试用例输出正确格式

---

## 文件修改清单（更新）

### 后端文件（任务 0）
1. **tradingagents/graph/propagation.py**
   - 修改 `get_graph_args()` 支持 stream_mode 参数
   
2. **tradingagents/graph/trading_graph.py**
   - 修改 `propagate()` 方法使用 graph.stream() 替代 invoke
   - 添加 progress_callback 参数支持
   
3. **tradingagents/core/analysis_runner.py**
   - 添加 NODE_TO_STEP 映射
   - 修改进度报告逻辑，使用流式更新

### 前端文件（任务 1-3）
4. **web/components/history_manager.py**
   - 修改 `render_history_manager()` 函数（约第632-717行）
   - 修改 `render_history_detail()` 函数（约第740-1070行）
   - 添加 `format_time()` 辅助函数
