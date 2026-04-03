# K线信号叠加与买卖连线可视化

## TL;DR

> **问题**: 自选股K线图只显示价格数据，AI分析信号（BUY/SELL/HOLD）只在表格中显示为文本，没有与K线图关联。用户无法直观看到信号产生时的价格位置和时机。
> 
> **方案**: 在K线图上叠加信号标记（箭头+置信度），并用线条连接连续买卖信号形成交易轨迹（盈利=绿实线，亏损=红虚线）
> 
> **交付物**: 后端API + 增强K线图渲染 + 错误状态提示
> **估算**: 中等复杂度（42个任务，7个Wave + OpenSpec工作流）
> **并行度**: 后端和前端可并行开发

---

## Context

### 原始问题
用户反馈："分析结果并没有实时显示出来，分析失败就提示失败，没有失败就显示在k线中"

### 当前实现问题
1. `render_candlestick_chart()` 只渲染原始价格数据（OHLCV），**没有任何分析标注**
2. AI信号只在 `render_watchlist_table()` 和 `render_monitoring_panel()` 中显示为**文本标签**，不在K线图上
3. 没有获取分析历史数据的API，只有 `last_signal` 最后一次信号
4. 错误处理不完善，没有明确的"分析失败"状态提示

### 相关文件
- `web/components/watchlist_manager.py:63-129` - `render_candlestick_chart()` 纯价格K线
- `web/components/watchlist_manager.py:706-845` - `render_monitoring_panel()` 信号文本显示
- `webapi/routers/watchlist.py:32-81` - Pydantic schemas (内联定义，非独立文件)
- `webapi/routers/watchlist.py:608-643` - `quick_analyze` 端点
- `webapi/models/database.py:277-356` - `WatchlistAnalysis` ORM模型
- `webapi/services/analysis_service.py` - 分析完成回调逻辑

---

## Work Objectives

### Core Objective
实现K线图与AI分析信号的叠加显示，用买卖连线可视化交易轨迹，提升分析结果的可读性。

### Concrete Deliverables
1. **后端API**: `GET /api/v1/watchlist/{id}/analysis-history`
2. **前端增强**: `render_candlestick_chart()` 支持信号标记叠加
3. **轨迹可视化**: 买卖信号连线（盈利=绿实线，亏损=红虚线）
4. **错误处理**: 分析失败时显示明确错误信息

### Definition of Done
- [ ] API返回分析历史时间序列（timestamp, signal, confidence, price）
- [ ] K线图显示BUY(🟢▲)、SELL(🔴▼)、HOLD(🟡◆)标记
- [ ] 连续买卖信号用线条连接
- [ ] 分析失败时显示红色错误提示
- [ ] 端到端测试通过

### Must Have
- 信号标记准确对应K线时间点
- 盈利/亏损连线样式区分
- ~~API权限验证（暂不需要，当前无用户系统）~~
- 错误状态友好提示

### Must NOT Have
- 不修改分析引擎核心逻辑（遵守Upstream Isolation Principle）
- 不引入新的数据源
- 不实现实时推送（SSE）

---

## Prerequisites (Wave 0 - Must Complete First)

**CRITICAL**: Before Tasks 1.1-1.6 can work, the following data persistence foundation must be in place:

1. **Database Schema** (`webapi/models/database.py:277-356`):
   - Add `price` column (Float, nullable) to WatchlistAnalysis
   - Add `error_message` column (Text, nullable) to WatchlistAnalysis

2. **Data Persistence** (`webapi/services/analysis_service.py:401-440`):
   - When AnalysisTask completes, find corresponding WatchlistAnalysis by analysis_id
   - Copy signal/confidence from AnalysisTask.result to WatchlistAnalysis
   - Copy current stock price at analysis time
   - If failed, copy error message
   - Set completed_at timestamp

**Implementation Options**:
- Option A: Modify `analysis_service.py` completion handler to update WatchlistAnalysis
- Option B: Add callback/observer pattern for analysis completion
- Option C: Change new endpoint to join with AnalysisTask table instead

**Recommended**: Option A - direct persistence on completion.

---

## Verification Strategy

### Test Decision
- **测试策略**: 端到端测试 + 手动验证
- **Agent-Executed QA**: 每个任务包含自动化验证场景

### QA Policy
每个任务必须包含可执行的QA场景，使用 curl/浏览器验证。

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (Prerequisites - Database & Data Flow):
├── 0.1 Add price column to WatchlistAnalysis model (Alembic migration)
├── 0.2 Add error_message column to WatchlistAnalysis model
├── 0.3 Create test data setup script for QA scenarios
└── 0.4 Add analysis completion callback to persist results

Wave 1 (Backend - Foundation):
├── 1.1 Add get_analysis_history() to WatchlistAnalysis model
├── 1.2 Create WatchlistAnalysisHistoryResponse schema  
├── 1.3 Implement GET /analysis-history endpoint
└── 1.4 Add limit parameter and error handling

Wave 2 (Frontend - Data Layer):
├── 2.1 Add get_analysis_history() function
├── 2.2 Add error handling with retry
├── 2.3 Cache in session_state
└── 2.4 Refresh after trigger_quick_analysis

Wave 3 (Frontend - Chart Enhancement):
├── 3.1 Modify render_candlestick_chart() signature
├── 3.2 Add signal-to-Kline mapping
├── 3.3 Implement BUY/SELL/HOLD markers
├── 3.4 Add "尚无AI信号" caption
└── 3.5 Error banner component

Wave 4 (Frontend - Trajectory):
├── 4.1 Trade pair detection logic
├── 4.2 Profit/loss calculation
├── 4.3 Green solid line for profit
├── 4.4 Red dashed line for loss
└── 4.5 Hover tooltip with trade details

Wave 5 (Integration):
├── 5.1 Update render_monitoring_panel()
├── 5.2 Update multi-stock charts
├── 5.3 Update detail view
└── 5.4 Click handler for signal markers

Wave FINAL (Verification):
├── API test with curl
├── Single signal K-line test
├── Multiple signals test
├── Trajectory lines test
├── Error states test
└── E2E test
```

---

## TODOs

### OpenSpec Workflow (Plan Activation)

- [ ] **SPEC-0** 同步计划到 OpenSpec 变更文档

  **What to do**:
  - 将审核通过的计划内容写入 `openspec/changes/kline-signal-overlay/` 目录
  - 更新 `proposal.md` - 确认提案内容与计划一致
  - 更新 `design.md` - 确认设计方案与计划一致
  - 更新 `specs/*/spec.md` - 确认各规格与任务对应
  - 更新 `tasks.md` - 确认任务列表与计划 TODOs 一致
  - 添加本计划文件引用到 `.openspec/plans/kline-signal-overlay.md`
  
  **References**:
  - `openspec/changes/kline-signal-overlay/proposal.md` - 提案文档
  - `openspec/changes/kline-signal-overlay/design.md` - 设计文档
  - `openspec/changes/kline-signal-overlay/specs/*/spec.md` - 规格文档
  - `openspec/changes/kline-signal-overlay/tasks.md` - 任务列表
  
  **Acceptance Criteria**:
  - [ ] 计划内容已同步到 OpenSpec 变更文档
  - [ ] 各文档引用已更新
  - [ ] 任务列表与计划 TODOs 完全一致

  **QA Scenario**:
  ```
  Tool: Bash (file check)
  Steps:
    1. ls -la openspec/changes/kline-signal-overlay/
    2. Verify proposal.md, design.md, specs/, tasks.md exist
    3. diff openspec/changes/kline-signal-overlay/tasks.md <(grep "^-\s" .sisyphus/plans/kline-signal-overlay.md | head -50)
  Expected: All OpenSpec files exist and content matches plan
  ```

### Wave 0: Database & Data Persistence (Prerequisites - Must Complete First)

- [ ] 0.1 Add `price` column to WatchlistAnalysis model

  **What to do**:
  - Add `price` column (Float, nullable) to WatchlistAnalysis class in `webapi/models/database.py`
  - Create Alembic migration file
  - Run migration to apply schema change
  
  **References**:
  - `webapi/models/database.py:277-356` - WatchlistAnalysis class definition
  - `alembic/versions/` - existing migrations
  
  **Acceptance Criteria**:
  - [ ] price column added to model
  - [ ] Migration file created
  - [ ] Migration applied successfully
  - [ ] Column visible in database schema
  
  **QA Scenario**:
  ```
  Tool: Bash (psql)
  Steps:
    1. alembic revision --autogenerate -m "add price to watchlist_analysis"
    2. alembic upgrade head
    3. psql -d tradingagents -c "\d watchlist_analyses" | grep price
  Expected: "price" column appears in schema with type "double precision"
  ```

- [ ] 0.2 Add `error_message` column to WatchlistAnalysis model

  **What to do**:
  - Add `error_message` column (Text, nullable) to WatchlistAnalysis class
  - Update Alembic migration to include this column
  - Apply migration
  
  **References**:
  - `webapi/models/database.py:277-356` - WatchlistAnalysis class
  
  **Acceptance Criteria**:
  - [ ] error_message column added to model
  - [ ] Migration includes both price and error_message
  - [ ] Column visible in database schema
  
  **QA Scenario**:
  ```
  Tool: Bash (psql)
  Steps:
    1. psql -d tradingagents -c "\d watchlist_analyses" | grep error_message
  Expected: "error_message" column appears with type "text"
  ```

- [ ] 0.3 Create test data setup script

  **What to do**:
  - Create a script/utility to populate test data for QA scenarios
  - Create watchlist entry for stock 000001
  - Insert mock analysis history with various signals (BUY, SELL, HOLD)
  - Insert profitable and loss-making trade pairs
  - This script will be used by QA scenarios that need deterministic data
  
  **Acceptance Criteria**:
  - [ ] Script creates watchlist entry for stock 000001
  - [ ] Script inserts BUY signal at price 10.0
  - [ ] Script inserts SELL signal at price 12.0 (profitable)
  - [ ] Script inserts HOLD signal
  - [ ] Script returns watchlist_id for use in QA
  
  **QA Scenario**:
  ```
  Tool: Python
  Steps:
    1. python scripts/setup_test_data.py
    2. psql -c "SELECT symbol, last_signal FROM watchlist WHERE symbol='000001'"
    3. psql -c "SELECT signal, price FROM watchlist_analyses WHERE watchlist_id=(SELECT id FROM watchlist WHERE symbol='000001')"
  Expected: Returns watchlist entry with signals and prices
  ```

- [ ] 0.4 Add analysis completion callback to persist results

  **What to do**:
  - Locate analysis completion handler in `analysis_service.py` (around lines 401-511)
  - When AnalysisTask completes:
    1. Update WatchlistAnalysis record (signal, confidence, price, error_message, completed_at)
    2. ALSO update Watchlist record (last_analysis_at, last_signal, last_confidence)
  - The Watchlist table is what the UI polls for refresh detection
  
  **Implementation Details**:
  - Hook into `analysis_service.py` where task status changes to "completed" or "failed"
  - Query WatchlistAnalysis by analysis_id to get watchlist_id
  - Update WatchlistAnalysis fields: signal, confidence, price, error_message, completed_at
  - Update Watchlist fields: last_analysis_at=now(), last_signal, last_confidence
  
  **References**:
  - `webapi/services/analysis_service.py:401-511` - analysis completion logic
  - `webapi/models/database.py:200-276` - Watchlist model (for UI refresh)
  - `webapi/models/database.py:277-356` - WatchlistAnalysis model
  - `webapi/routers/watchlist.py:627-636` - WatchlistAnalysis creation with analysis_id
  
  **Acceptance Criteria**:
  - [ ] WatchlistAnalysis updated: signal, confidence, price, error_message, completed_at
  - [ ] Watchlist updated: last_analysis_at, last_signal, last_confidence
  - [ ] Both updates in same transaction
  
  **QA Scenario**:
  ```
  Tool: Bash (curl + psql)
  Steps:
    1. Create watchlist entry for stock 000001, get watchlist_id
    2. curl -X POST http://localhost:8000/api/v1/watchlist/{watchlist_id}/quick-analyze
    3. Wait 30 seconds for completion
    4. psql -c "SELECT last_signal, last_confidence FROM watchlist WHERE id={watchlist_id}"
    5. psql -c "SELECT signal, confidence FROM watchlist_analyses WHERE watchlist_id={watchlist_id} ORDER BY id DESC LIMIT 1"
  Expected: Both queries return matching signal and confidence values
  ```

### Wave 1: Backend API

- [ ] 1.1 Add `get_analysis_history()` method to WatchlistAnalysis model

  **What to do**:
  - Add classmethod to query analysis history by watchlist_id
  - Support limit parameter (default 50)
  - Order by created_at DESC
  
  **References**:
  - `webapi/models/database.py:WatchlistAnalysis`
  
  **Acceptance Criteria**:
  - [ ] Method returns List[WatchlistAnalysis]
  - [ ] Respects limit parameter
  - [ ] Ordered by timestamp descending
  
  **QA Scenario**:
  ```
  Tool: Bash (python)
  Steps:
    1. python -c "from webapi.models.database import WatchlistAnalysis; print(WatchlistAnalysis.get_analysis_history(1, limit=5))"
  Expected: Returns list of analysis records
  ```

- [ ] 1.2 Create Pydantic schema `WatchlistAnalysisHistoryResponse`

  **What to do**:
  - Define response model with fields: timestamp, signal, confidence, price, error_message
  - Add to `webapi/routers/watchlist.py` after line 81
  
  **References**:
  - `webapi/routers/watchlist.py:32-81` - existing schemas (defined inline)
  
  **Acceptance Criteria**:
  - [ ] Schema defined with proper types
  - [ ] Includes all required fields
  
  **QA Scenario**:
  ```
  Tool: Python
  Steps:
    1. python -c "from webapi.routers.watchlist import WatchlistAnalysisHistoryResponse; s = WatchlistAnalysisHistoryResponse(timestamp='2024-01-01T10:00:00', signal='BUY', confidence=0.85, price=10.5, error_message=None); print(s.json())"
  Expected: Valid JSON with all fields
  ```

- [ ] 1.3 Implement `GET /api/v1/watchlist/{id}/analysis-history` endpoint

  **What to do**:
  - Add route handler in watchlist router
  - Call service layer to fetch data
  - Return formatted response
  
  **References**:
  - `webapi/routers/watchlist.py` - existing routes
  
  **Acceptance Criteria**:
  - [ ] Endpoint returns 200 with analysis list
  - [ ] Returns correct data format
  
  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Steps:
    1. python scripts/setup_test_data.py  # Get {watchlist_id}
    2. curl -s http://localhost:8000/api/v1/watchlist/{watchlist_id}/analysis-history | python -m json.tool
  Expected: JSON array with analysis records
  ```

- [ ] 1.4 Add query parameter `limit` with default 50

  **What to do**:
  - Add limit query param to endpoint
  - Validate limit (1-100)
  
  **Acceptance Criteria**:
  - [ ] Default limit is 50
  - [ ] Respects user-provided limit
  - [ ] Validates range
  
  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Steps:
    1. python scripts/setup_test_data.py  # Get {watchlist_id}
    2. curl -s "http://localhost:8000/api/v1/watchlist/{watchlist_id}/analysis-history?limit=2" | python -m json.tool | grep -c '"timestamp"'
  Expected: Returns at most 2 records (count matches)
  ```

- [ ] 1.5 Add 404 handling for non-existent watchlist

  **What to do**:
  - Return 404 if watchlist ID doesn't exist
  
  **Acceptance Criteria**:
  - [ ] Returns 404 for invalid ID
  
  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Steps:
    1. curl -s -w "\nHTTP %{http_code}\n" http://localhost:8000/api/v1/watchlist/99999/analysis-history
  Expected: HTTP 404
  ```

- [ ] 1.6 Test API endpoint with curl

  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Steps:
    1. python scripts/setup_test_data.py  # Get {watchlist_id}
    2. curl -s http://localhost:8000/api/v1/watchlist/{watchlist_id}/analysis-history
    3. Verify response format and data
  Expected: Returns analysis history in correct format
  ```

- [ ] 2.1 Add `get_analysis_history(stock_id: int)` function

  **What to do**:
  - Create function to call API endpoint
  - Handle response parsing
  
  **References**:
  - `web/components/watchlist_manager.py:load_watchlist()`
  
  **Acceptance Criteria**:
  - [ ] Function fetches analysis history
  - [ ] Returns parsed data
  
  **QA Scenario**:
  ```
  Tool: Python (manual test via browser console or script)
  Steps:
    1. Run: python scripts/setup_test_data.py (creates test data, outputs watchlist_id)
    2. Call get_analysis_history({watchlist_id}) with ID from step 1
    3. Print returned data structure
  Expected: Returns list of dicts with keys: timestamp, signal, confidence, price, error_message
  ```

- [ ] 2.2 Add error handling with retry logic

  **What to do**:
  - Wrap API call in try-except
  - Add retry mechanism (max 3 attempts with 1s delay) for transient errors
  
  **Acceptance Criteria**:
  - [ ] Retries on network error (ConnectionError, Timeout)
  - [ ] Returns empty list on persistent failure after retries
  
  **QA Scenario**:
  ```
  Tool: Python + manual network interruption
  Steps:
    1. Temporarily block API port (e.g., Windows Firewall block 8000)
    2. Call get_analysis_history() in Python
    3. Observe retry behavior in logs
    4. Unblock port
  Expected: Function attempts 3 times then returns empty list gracefully
  ```

- [ ] 2.3 Cache analysis history in session_state

  **What to do**:
  - Store fetched data in st.session_state with key pattern `analysis_history_{stock_id}`
  - Check cache before making API call
  
  **Acceptance Criteria**:
  - [ ] Data cached after first fetch
  - [ ] Subsequent calls use cached data
  - [ ] Cache format matches API response
  
  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Prerequisites: Setup test data with `python scripts/setup_test_data.py`
  Steps:
    1. Open watchlist page for watchlist_id={watchlist_id}
    2. Add temporary logging to get_analysis_history() function
    3. Observe console/log output - should see "Fetching analysis history" once
    4. Trigger Streamlit rerun (change any widget)
    5. Observe console/log output - should NOT see another "Fetching"
  Expected: API call made only once; subsequent reruns use cached data
  ```

- [ ] 2.4 Add refresh mechanism after analysis completion

  **What to do**:
  - Store `last_analysis_at` timestamp for each stock in session_state
  - When analysis triggered, record expected completion time or task_id
  - Poll or check `last_analysis_at` changes to detect completion
  - Clear cache and refresh when new analysis detected (NOT immediately after trigger)
  
  **Implementation Approach**:
  ```python
  # After trigger_quick_analysis returns task_id
  st.session_state[f'pending_analysis_{stock_id}'] = task_id
  st.session_state[f'last_check_{stock_id}'] = time.time()
  
  # On each rerun, check if pending analysis completed
  if st.session_state.get(f'pending_analysis_{stock_id}'):
      # Check current last_analysis_at from watchlist data
      current = get_watchlist_item(stock_id)['last_analysis_at']
      if current > st.session_state.get(f'previous_analysis_{stock_id}'):
          # Analysis completed! Clear cache and refresh
          clear_analysis_cache(stock_id)
          del st.session_state[f'pending_analysis_{stock_id}']
          st.rerun()
  ```
  
  **Acceptance Criteria**:
  - [ ] Cache NOT cleared immediately (analysis still running)
  - [ ] Cache cleared when analysis actually completes
  - [ ] New signal appears on chart automatically after completion
  
  **QA Scenario**:
  ```
  Tool: Browser + observation
  Steps:
    1. Open watchlist, note "尚无AI信号" on stock
    2. Click "立即分析"
    3. Observe spinner/loading state
    4. Wait for analysis to complete (20-60s)
    5. Verify new signal marker appears on K-line without manual refresh
  Expected: Signal appears automatically after async analysis completes
  ```

- [ ] 3.1 Modify `render_candlestick_chart()` signature

  **What to do**:
  - Add `analysis_data: Optional[List[Dict]] = None` parameter
  - Update all call sites to pass None (backward compatible)
  
  **References**:
  - `web/components/watchlist_manager.py:63-129`
  
  **Acceptance Criteria**:
  - [ ] Function accepts analysis_data parameter
  - [ ] Backward compatible (None = no markers)
  - [ ] All existing call sites updated
  
  **QA Scenario**:
  ```
  Tool: Python
  Steps:
    1. Call render_candlestick_chart(df, title="Test")  # old way
    2. Call render_candlestick_chart(df, title="Test", analysis_data=[])  # new way
    3. Call render_candlestick_chart(df, title="Test", analysis_data=[{"signal":"BUY",...}])  # with data
  Expected: All three calls execute without error
  ```

- [ ] 3.2 Add signal-to-Kline mapping function

  **What to do**:
  - Create function `map_signal_to_kline(analysis_timestamp, kline_df)`
  - Use nearest neighbor matching to find closest K-line index
  - Handle timestamps outside K-line range gracefully
  
  **Acceptance Criteria**:
  - [ ] Returns x-index for each analysis timestamp
  - [ ] Handles timestamps outside K-line range (returns nearest or None)
  - [ ] Correctly matches within 1-minute tolerance
  
  **QA Scenario**:
  ```
  Tool: Python
  Steps:
    1. Create test K-line DataFrame with 10:00, 10:01, 10:02 timestamps
    2. Call map_signal_to_kline("10:01:30", df)  # halfway between
    3. Call map_signal_to_kline("09:55:00", df)  # before start
    4. Call map_signal_to_kline("10:01:00", df)  # exact match
  Expected: Returns index 1 for halfway, 0 for before, 1 for exact
  ```

- [ ] 3.3 Implement BUY signal marker

  **What to do**:
  - Use Plotly `go.Scatter` with `mode='markers+text'` (NOT `add_annotation()`)
  - Marker: green triangle-up (#4CAF50), size 12
  - Text: confidence percentage, positioned above marker
  - Use `customdata` to store signal details for click handling
  - Note: Use Scatter trace (not annotations) to enable click interaction in Task 5.4
  
  **Implementation**:
  ```python
  fig.add_trace(go.Scatter(
      x=[x_position],
      y=[price],
      mode='markers+text',
      marker=dict(symbol='triangle-up', color='#4CAF50', size=12),
      text=[f'{confidence:.0%}'],
      textposition='top center',
      customdata=[{'signal': 'BUY', 'confidence': confidence, 'timestamp': ts}],
      hovertemplate='Signal: BUY<br>Confidence: %{text}<br>Price: ¥%{y:.2f}<extra></extra>',
      showlegend=False
  ))
  ```
  
  **Acceptance Criteria**:
  - [ ] Green triangle marker at BUY timestamp position
  - [ ] Confidence percentage text above marker
  - [ ] Hover tooltip shows signal details
  - [ ] customdata populated for click handling
  
  **QA Scenario**:
  ```
  Tool: Browser (visual inspection)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with BUY signal
  Steps:
    1. Open watchlist page with test stock
    2. Verify K-line chart displays green triangle-up marker
    3. Take screenshot
  Expected: Green triangle-up marker (▲) visible at correct position on chart
  ```
  Tool: Browser (visual inspection)
  Steps:
    1. Create test data with BUY signal at timestamp T
    2. Render chart with analysis_data containing BUY
    3. Take screenshot
  Expected: Green upward arrow visible at correct x-position on chart
  ```

- [ ] 3.4 Implement SELL signal marker

  **What to do**:
  - Use Plotly `go.Scatter` with `mode='markers+text'`
  - Marker: red triangle-down (#F44336), size 12
  - Text: confidence percentage, positioned below marker
  - Use `customdata` to store signal details
  
  **Implementation**:
  ```python
  fig.add_trace(go.Scatter(
      x=[x_position],
      y=[price],
      mode='markers+text',
      marker=dict(symbol='triangle-down', color='#F44336', size=12),
      text=[f'{confidence:.0%}'],
      textposition='bottom center',
      customdata=[{'signal': 'SELL', 'confidence': confidence, 'timestamp': ts}],
      hovertemplate='Signal: SELL<br>Confidence: %{text}<br>Price: ¥%{y:.2f}<extra></extra>',
      showlegend=False
  ))
  ```
  
  **Acceptance Criteria**:
  - [ ] Red triangle-down marker at SELL timestamp position
  - [ ] Confidence percentage text below marker
  - [ ] customdata populated for click handling
  
  **QA Scenario**:
  ```
  Tool: Browser (visual inspection)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with SELL signal
  Steps:
    1. Open watchlist page for watchlist_id={watchlist_id}
    2. Verify K-line chart displays red triangle-down marker
    3. Take screenshot
  Expected: Red triangle-down marker (▼) visible at correct position
  ```

- [ ] 3.5 Implement HOLD signal marker

  **What to do**:
  - Use Plotly `go.Scatter` with `mode='markers+text'`
  - Marker: yellow diamond (#FF9800), size 10
  - Text: confidence percentage, positioned above marker
  - Use `customdata` to store signal details
  
  **Implementation**:
  ```python
  fig.add_trace(go.Scatter(
      x=[x_position],
      y=[price],
      mode='markers+text',
      marker=dict(symbol='diamond', color='#FF9800', size=10),
      text=[f'{confidence:.0%}'],
      textposition='top center',
      customdata=[{'signal': 'HOLD', 'confidence': confidence, 'timestamp': ts}],
      hovertemplate='Signal: HOLD<br>Confidence: %{text}<br>Price: ¥%{y:.2f}<extra></extra>',
      showlegend=False
  ))
  ```
  
  **Acceptance Criteria**:
  - [ ] Yellow diamond marker at HOLD timestamp position
  - [ ] Confidence percentage text visible
  - [ ] customdata populated for click handling
  
  **QA Scenario**:
  ```
  Tool: Browser (visual inspection)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with HOLD signal
  Steps:
    1. Open watchlist page with test stock
    2. Verify K-line chart displays yellow diamond marker
    3. Take screenshot
  Expected: Yellow diamond marker (◆) visible at correct position
  ```

- [ ] 3.6 Add "尚无AI信号" caption

  **What to do**:
  - Display caption below chart when analysis_data is None or empty
  - Use st.caption() for subtle styling
  - Hide caption when analysis data exists
  
  **Acceptance Criteria**:
  - [ ] Caption "尚无AI信号，请先运行分析" shown when no analysis
  - [ ] Caption hidden when analysis_data has items
  
  **QA Scenario**:
  ```
  Tool: Browser (Playwright)
  Prerequisites: Run python scripts/setup_test_data.py to create test data
  Steps:
    1. View stock with no analysis history
    2. Verify caption visible
    3. Run analysis, wait for completion
    4. Verify caption disappears and markers appear
  Expected: Caption shows/hides correctly based on data presence
  ```

- [ ] 4.1 Implement trade pair detection

  **What to do**:
  - Iterate through analysis history in chronological order
  - Identify BUY→SELL and SELL→BUY sequences
  - Skip HOLD signals (don't start or end pairs)
  - Return list of pairs: [(entry_signal, exit_signal), ...]
  
  **Acceptance Criteria**:
  - [ ] Correctly pairs BUY followed by SELL
  - [ ] Correctly pairs SELL followed by BUY
  - [ ] Skips HOLD signals in pairing logic
  - [ ] Handles incomplete pairs (e.g., ends with BUY)
  
  **QA Scenario**:
  ```
  Tool: Python
  Steps:
    1. Test data: [BUY@10:00, HOLD@10:05, SELL@10:10, BUY@10:15]
    2. Call detect_trade_pairs()
    3. Verify pairs: [(BUY@10:00, SELL@10:10)]
    4. Verify incomplete: [BUY@10:15]
  Expected: Returns one complete pair, one incomplete BUY
  ```

- [ ] 4.2 Add profit/loss calculation

  **What to do**:
  - For each complete trade pair:
    - BUY→SELL: P&L = (sell_price - buy_price) / buy_price * 100
    - SELL→BUY: P&L = (sell_price - buy_price) / sell_price * 100 (short)
  - Return percentage with sign
  
  **Acceptance Criteria**:
  - [ ] Correct profit calculation for long trades
  - [ ] Correct profit calculation for short trades
  - [ ] Returns P&L percentage with proper sign (+/-)
  
  **QA Scenario**:
  ```
  Tool: Python
  Steps:
    1. Test: BUY@10.0, SELL@12.0 → P&L = +20%
    2. Test: BUY@10.0, SELL@8.0 → P&L = -20%
    3. Test: SELL@12.0, BUY@10.0 → P&L = +16.67%
  Expected: Correct P&L percentages calculated
  ```

- [ ] 4.3 Draw green solid line for profitable trades

  **What to do**:
  - Use Plotly `go.Scatter` trace (NOT `add_shape()` because shapes don't support hover)
  - Mode: 'lines', Color: #4CAF50, Line style: solid
  - Connect entry signal to exit signal
  - Add to figure with `showlegend=False`
  
  **Implementation**:
  ```python
  fig.add_trace(go.Scatter(
      x=[entry_x, exit_x],
      y=[entry_y, exit_y],
      mode='lines',
      line=dict(color='#4CAF50', width=2),
      hoverinfo='skip',  # Hover handled in 4.5
      showlegend=False
  ))
  ```
  
  **Acceptance Criteria**:
  - [ ] Green solid line connects profitable pairs
  - [ ] Line drawn as Scatter trace (not shape)
  
  **QA Scenario**:
  ```
  Tool: Browser (visual inspection)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with BUY→SELL profitable pair
  Steps:
    1. Open watchlist page for watchlist_id={watchlist_id}
    2. Render chart with trajectory enabled
    3. Take screenshot
  Expected: Green solid line connects the two signal markers
  ```

- [ ] 4.4 Draw red dashed line for loss trades

  **What to do**:
  - Use Plotly `go.Scatter` trace (NOT `add_shape()`)
  - Mode: 'lines', Color: #F44336, Line style: dash
  - Connect entry signal to exit signal
  - Add to figure with `showlegend=False`
  
  **Implementation**:
  ```python
  fig.add_trace(go.Scatter(
      x=[entry_x, exit_x],
      y=[entry_y, exit_y],
      mode='lines',
      line=dict(color='#F44336', width=2, dash='dash'),
      hoverinfo='skip',  # Hover handled in 4.5
      showlegend=False
  ))
  ```
  
  **Acceptance Criteria**:
  - [ ] Red dashed line connects loss pairs
  - [ ] Line style is dash
  
  **QA Scenario**:
  ```
  Tool: Browser (visual inspection)
  Steps:
    1. Create test data with loss-making BUY→SELL pair
    2. Render chart with trajectory enabled
    3. Take screenshot
  Expected: Red dashed line connects the two signal markers
  ```
  Tool: Browser (visual inspection)
  Steps:
    1. Create test data with loss-making BUY→SELL pair
    2. Render chart with trajectory enabled
    3. Take screenshot
  Expected: Red dashed line connects the two signal markers
  ```

- [ ] 4.5 Add hover tooltip with trade details

  **What to do**:
  - Use Plotly `go.Scatter` line trace (NOT `add_shape()`) for trajectory lines
  - Set `mode='lines'` and `hovertemplate` for custom tooltip
  - Format: "Entry: ¥X.XX | Exit: ¥X.XX | P&L: +X.X%"
  - Note: `add_shape()` does NOT support hover, must use Scatter trace
  
  **Implementation**:
  ```python
  fig.add_trace(go.Scatter(
      x=[entry_x, exit_x],
      y=[entry_y, exit_y],
      mode='lines',
      line=dict(color='#4CAF50' if profit else '#F44336', 
                dash='solid' if profit else 'dash'),
      hovertemplate='Entry: ¥%{customdata[0]:.2f}<br>Exit: ¥%{customdata[1]:.2f}<br>P&L: %{customdata[2]:+.1f}%<extra></extra>',
      customdata=[[entry_price, exit_price, pnl_pct]],
      showlegend=False
  ))
  ```
  
  **Acceptance Criteria**:
  - [ ] Trajectory lines drawn as Scatter traces
  - [ ] Hovering over line shows tooltip
  - [ ] Tooltip displays entry price, exit price, P&L
  
  **QA Scenario**:
  ```
  Tool: Browser
  Steps:
    1. Render chart with trade trajectory using Scatter traces
    2. Hover mouse over connecting line
    3. Observe tooltip content
  Expected: Tooltip appears with formatted trade details
  ```

- [x] 5.1 Update `render_monitoring_panel()`

  **What to do**:
  - Call get_analysis_history() for each selected stock
  - Pass analysis_data to render_candlestick_chart()
  - Handle errors gracefully
  
  **Acceptance Criteria**:
  - [ ] Analysis history fetched for displayed stocks
  - [ ] Signals rendered on K-line charts
  - [ ] Errors don't crash the panel
  
  **QA Scenario**:
  ```
  Tool: Browser (Playwright)
  Prerequisites: Run python scripts/setup_test_data.py to create test data
  Steps:
    1. Open monitoring panel with 2+ stocks selected
    2. Verify each chart shows signals if analysis exists
    3. Verify "尚无AI信号" shown if no analysis
  Expected: All charts display correctly with or without signals
  ```

- [x] 5.2 Update multi-stock charts

  **What to do**:
  - Ensure each stock fetches its own analysis history
  - Pass correct stock_id to get_analysis_history()
  - Isolate data between stocks
  
  **Acceptance Criteria**:
  - [ ] Each stock displays only its own signals
  - [ ] No cross-contamination between stocks
  
  **QA Scenario**:
  ```
  Tool: Browser (Playwright)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with different signals per stock
  Steps:
    1. Select 2 stocks: A (has BUY signal), B (has SELL signal)
    2. Verify Stock A chart shows green BUY arrow
    3. Verify Stock B chart shows red SELL arrow
  Expected: Each chart shows only its own signals
  ```

- [x] 5.3 Update detail view chart

  **What to do**:
  - Fetch full analysis history for selected stock
  - Render with trajectory visualization enabled
  - Show complete trade history
  
  **Acceptance Criteria**:
  - [ ] Detail view shows all historical signals
  - [ ] Trajectory lines visible if trades exist
  
  **QA Scenario**:
  ```
  Tool: Browser
  Steps:
    1. Select stock with multiple analyses
    2. Open detail view
    3. Verify all signals visible on large chart
    4. Verify trajectory lines shown
  Expected: Complete trade history visualized on detail chart
  ```

- [x] 5.4 Add signal marker click handler

  **What to do**:
  - Use st.plotly_chart's `on_select` parameter for click handling
  - Access `customdata` from selected marker to get signal details
  - Scroll to analysis detail section on click
  - Highlight corresponding analysis record
  - Note: This works because markers are Scatter traces (3.3-3.5), not annotations
  
  **Implementation**:
  ```python
  selected_points = st.plotly_chart(fig, on_select='rerun', key='kline_chart')
  if selected_points and selected_points.selection.points:
      point = selected_points.selection.points[0]
      customdata = point.customdata[0]  # {'signal': 'BUY', 'confidence': 0.85, 'timestamp': '2024-01-01T10:00:00'}
      # Scroll to analysis detail and highlight
      st.session_state.selected_analysis = customdata
      st.rerun()
  ```
  
  **Acceptance Criteria**:
  - [ ] Clicking signal marker triggers on_select callback
  - [ ] Page scrolls to analysis detail section
  - [ ] Corresponding analysis record highlighted
  
  **QA Scenario**:
  ```
  Tool: Browser
  Steps:
    1. Click on BUY signal marker (Scatter trace) on chart
    2. Verify st.plotly_chart on_select triggers
    3. Verify page scrolls to analysis detail section
    4. Verify the BUY analysis is highlighted
  Expected: Click interaction works via on_select callback
  ```

- [x] 6.1 Add error banner component

  **What to do**:
  - Create reusable function `show_error_banner(message, on_retry=None)`
  - Use st.error() with custom styling
  - Add retry button that calls on_retry callback
  
  **Acceptance Criteria**:
  - [ ] Red error banner displays on API error
  - [ ] Retry button visible and clickable
  - [ ] Clicking retry re-attempts the failed operation
  
  **QA Scenario**:
  ```
  Tool: Browser + manual intervention
  Steps:
    1. Stop API server
    2. Load watchlist page
    3. Verify error banner appears
    4. Click retry button
    5. Start API server
    6. Click retry again
  Expected: Banner shows on error, retry button works
  ```

- [x] 6.2 Add loading spinner

  **What to do**:
  - Use st.spinner() while fetching analysis history
  - Show "加载分析数据中..." message
  - Hide spinner when complete or error
  
  **Acceptance Criteria**:
  - [ ] Spinner shown during initial data fetch
  - [ ] Spinner hidden after data loaded
  - [ ] Spinner hidden on error (shows error instead)
  
  **QA Scenario**:
  ```
  Tool: Browser
  Steps:
    1. Clear session state / hard refresh
    2. Navigate to watchlist with analysis data
    3. Observe spinner appears during load
    4. Verify spinner disappears and data appears
  Expected: Loading indicator visible during fetch, gone after complete

- [x] 7.1 Test API with curl

  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Prerequisites: Setup test data with `python scripts/setup_test_data.py`
  Steps:
    1. curl http://localhost:8000/api/v1/watchlist/{watchlist_id}/analysis-history
    2. Verify JSON structure
    3. Verify field types
  Expected: Valid JSON with required fields
  ```

- [x] 7.2 Test K-line with single signal

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with single signal
  Steps:
    1. Navigate to watchlist page for watchlist_id={watchlist_id}
    2. Select stock with one analysis
    3. Verify signal marker visible
  Expected: Single marker displayed correctly
  ```

- [x] 7.3 Test K-line with multiple signals

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with multiple signals
  Steps:
    1. Select stock with multiple analyses
    2. Verify all markers visible
    3. Verify no overlap
  Expected: All markers displayed correctly
  ```

- [x] 7.4 Test trajectory lines

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Prerequisites: Run python scripts/setup_test_data.py to create test data with BUY→SELL sequence
  Steps:
    1. Select stock with BUY→SELL sequence
    2. Verify green/red line visible
    3. Hover over line verify tooltip
  Expected: Trajectory line with correct color and tooltip
  ```

- [x] 7.5 Test error states

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Steps:
    1. Stop API server
    2. Refresh watchlist page
    3. Verify error message displayed
    4. Click retry button
  Expected: Error message with retry functionality
  ```

- [x] 7.6 E2E test: trigger analysis → see signal

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Steps:
    1. Add stock to watchlist
    2. Click "立即分析" button
    3. Wait for analysis complete
    4. Verify signal marker appears on K-line
  Expected: New signal visible on chart after analysis
  ```

---

## Final Verification Wave

- [x] F1. **API Compliance Audit** - `oracle`

  **What to verify**:
  - API endpoint returns correct JSON format
  - Error codes work correctly (404 for not found, 200 for success)
  - Data format matches specification
  
  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Prerequisites: Setup test data with `python scripts/setup_test_data.py`
  Steps:
    1. Test success: curl -s http://localhost:8000/api/v1/watchlist/{watchlist_id}/analysis-history | python -m json.tool
    2. Verify response has: timestamp, signal, confidence, price, error_message fields
    3. Test 404: curl -s -w "\n%{http_code}\n" http://localhost:8000/api/v1/watchlist/99999/analysis-history
    4. Verify returns HTTP 404
    5. Test limit param: curl -s "http://localhost:8000/api/v1/watchlist/{watchlist_id}/analysis-history?limit=2" | python -m json.tool | jq length
    6. Verify returns at most 2 records
  Expected: All API behaviors match specification
  ```

- [x] F2. **Chart Rendering Review** - `visual-engineering`

  **What to verify**:
  - BUY signals show green triangle-up markers (▲)
  - SELL signals show red triangle-down markers (▼)
  - HOLD signals show yellow diamond markers (◆)
  - Trajectory lines connect signals (green solid for profit, red dashed for loss)
  - Confidence percentages visible above/below markers
  
  **QA Scenario**:
  ```
  Tool: Browser (visual inspection + screenshots)
  Prerequisites: Run python scripts/setup_test_data.py (creates test data with BUY, SELL, HOLD, profit/loss pairs)
  Steps:
    1. Open watchlist page with test stock (has BUY signal at price 10.0)
    2. Take screenshot, verify green triangle-up marker (▲) visible
    3. Verify SELL signal at price 12.0 shows red triangle-down marker (▼)
    4. Verify profitable BUY→SELL pair has green solid line connecting markers
    5. Verify HOLD signal shows yellow diamond marker (◆)
  Expected: All visual elements render correctly: green ▲, red ▼, yellow ◆, solid/dashed lines
  ```

- [x] F3. **Error Handling Verification** - `unspecified-high`

  **What to verify**:
  - Network errors display retry button
  - API errors show clear error messages
  - Loading spinner appears during data fetch
  - Graceful degradation when API unavailable
  
  **QA Scenario**:
  ```
  Tool: Browser + manual intervention
  Steps:
    1. Start with API server running, verify data loads normally
    2. Stop API server
    3. Refresh page, verify error banner appears with retry button
    4. Click retry button, verify retry attempted
    5. Start API server
    6. Click retry button, verify data loads successfully
    7. During normal operation, verify spinner appears briefly then disappears
  Expected: All error states handled gracefully with user feedback
  ```

- [x] F4. **E2E Integration Test** - `deep`

  **What to verify**:
  - Complete user flow works end-to-end
  - Data persists through the pipeline
  - Multiple stocks handled correctly
  
  **QA Scenario**:
  ```
  Tool: Browser (full manual E2E test)
  Steps:
    1. Add new stock to watchlist (symbol: 000001)
    2. Verify "尚无AI信号" caption shown on K-line
    3. Click "立即分析" button
    4. Wait for analysis to complete (check for completion indicator)
    5. Verify signal marker (BUY/SELL/HOLD) appears on K-line
    6. Verify signal displayed in watchlist table
    7. Click into detail view
    8. Verify full-size chart shows signal with confidence
    9. Add second stock and run analysis
    10. Verify each stock shows only its own signals
   Expected: Complete flow from adding stock to seeing signal on K-line works seamlessly
   ```

- [ ] **F5. Archive OpenSpec Change** - `quick`

  **What to do**:
  - 执行 OpenSpec 归档工作流，将完成的变更永久保存
  - 运行 `/openspec-archive` 或手动执行归档步骤
  - 验证归档完成并记录归档时间戳
  
  **References**:
  - `.openspec/skills/openspec-archive-change/` - 归档 skill
  
  **Acceptance Criteria**:
  - [ ] OpenSpec 变更已归档
  - [ ] 归档时间戳已记录
  - [ ] 变更状态更新为 "archived"

  **QA Scenario**:
  ```
  Tool: Bash (git + file check)
  Steps:
    1. git log openspec/changes/kline-signal-overlay/ --oneline | head -5
    2. cat openspec/changes/kline-signal-overlay/STATUS
    3. Verify status is "archived" and has completion timestamp
  Expected: Change is archived with timestamp
  ```

---

## Commit Strategy

- Backend API: `feat(api): add analysis history endpoint`
- Frontend data layer: `feat(web): fetch analysis history`
- Chart enhancement: `feat(web): overlay signal markers on K-line`
- Trajectory: `feat(web): add trade trajectory visualization`
- Error handling: `feat(web): improve error states`

---

## Success Criteria

### Verification Commands
```bash
# API test
curl -s http://localhost:8000/api/v1/watchlist/{watchlist_id}/analysis-history | python -m json.tool

# Health check
curl -s http://localhost:8000/docs
```

### Final Checklist
- [ ] API returns correct analysis history format
- [ ] K-line shows BUY/SELL/HOLD markers
- [ ] Trajectory lines connect signals
- [ ] Error states display properly
- [ ] E2E flow works end-to-end
- [ ] No regression in existing features
