# Plan: Add Real-time Steps and Logs to Analysis Detail Page

## Overview
Enhance the analysis detail page to display real-time analysis progress with step-by-step agent execution status and activity logs.

## Current State
- Detail page shows static results after analysis completes
- No visibility into which agents are running during analysis
- Progress updates are minimal

## Requirements
1. Show all analysis steps in a timeline view
2. Display which agent is currently running
3. Show activity logs with timestamps
4. Auto-refresh during analysis (PENDING/RUNNING status)
5. Manual refresh button

## Analysis Steps to Display
1. 🚀 graph_setup - 初始化分析图
2. 📊 market_analyst - 市场分析师 (技术分析、趋势识别)
3. 💭 sentiment_analyst - 情绪分析师 (社交媒体情绪分析)
4. 📰 news_analyst - 新闻分析师 (新闻事件影响评估)
5. 🏢 fundamentals_analyst - 基本面分析师 (财务报表分析)
6. 🐂 bull_researcher - 看涨研究员 (多头观点论证)
7. 🐻 bear_researcher - 看跌研究员 (空头观点论证)
8. 💼 trader - 交易员 (交易策略制定)
9. ⚠️ risk_manager - 风控经理 (风险评估与审核)
10. 👔 portfolio_manager - 投资组合经理 (最终决策与执行)

## Data Source
- `result_data.agents_progress` - Dict of agent statuses
- `result_data.current_agent` - Currently executing agent
- `result_data.progress_pct` - Overall progress percentage

## Implementation Steps

### Step 1: Modify render_history_detail function
**File**: `web/components/history_manager.py`

Add a new section BEFORE the decision section (around line 875) that:
1. Checks if status is PENDING or RUNNING
2. Displays progress bar with percentage
3. Shows all analysis steps with status icons
4. Displays activity logs
5. Auto-refreshes every 3 seconds using time.sleep() + st.rerun()

### Step 2: Add UI Components
- Progress bar (st.progress)
- Timeline view of steps with icons
- Scrollable logs container (st.code)
- Refresh button
- Auto-refresh mechanism

### Step 3: Handle Data Flow
- Read agents_progress from result_data
- Map agent IDs to display names
- Generate logs based on completed/in-progress agents
- Auto-refresh until status is COMPLETED or FAILED

## Technical Details

### Status Mapping
- `completed` → ✅ Green
- `in_progress` → 🔄 Blue
- `failed` → ❌ Red
- `not_started` → ⏳ Gray

### Auto-refresh Logic
```python
if status in ("PENDING", "RUNNING"):
    import time
    time.sleep(3)
    st.rerun()
```

### Log Generation
Build activity log based on agents_progress:
- Task start time
- Each completed agent
- Current in-progress agent
- Timestamps based on created_at

## Testing
1. Create a new analysis task
2. Navigate to detail page while running
3. Verify steps are displayed with correct status
4. Verify logs update
5. Verify auto-refresh works
6. Verify completed analysis shows final results

## Success Criteria
- [ ] All 10 analysis steps visible during execution
- [ ] Current agent highlighted with 🔄 icon
- [ ] Activity logs show with timestamps
- [ ] Page auto-refreshes every 3 seconds during analysis
- [ ] Manual refresh button works
- [ ] No errors when viewing completed analyses
