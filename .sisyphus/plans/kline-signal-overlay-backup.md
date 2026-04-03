# K线信号叠加与买卖连线可视化

## TL;DR

> **问题**: 自选股K线图只显示价格数据，AI分析信号（BUY/SELL/HOLD）只在表格中显示为文本，没有与K线图关联。用户无法直观看到信号产生时的价格位置和时机。
> 
> **方案**: 在K线图上叠加信号标记（箭头+置信度），并用线条连接连续买卖信号形成交易轨迹（盈利=绿实线，亏损=红虚线）
> 
> **交付物**: 后端API + 增强K线图渲染 + 错误状态提示
> **估算**: 中等复杂度（33个任务）
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
- `webapi/routers/watchlist.py` - 当前没有 analysis-history 端点
- `webapi/models/database.py` - `WatchlistAnalysis` 模型已有但未充分利用

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
- [ ] K线图显示BUY(🟢↑)、SELL(🔴↓)、HOLD(🟡→)标记
- [ ] 连续买卖信号用线条连接
- [ ] 分析失败时显示红色错误提示
- [ ] 端到端测试通过

### Must Have
- 信号标记准确对应K线时间点
- 盈利/亏损连线样式区分
- API权限验证（只能查看自己的数据）
- 错误状态友好提示

### Must NOT Have
- 不修改分析引擎核心逻辑（遵守Upstream Isolation Principle）
- 不引入新的数据源
- 不实现实时推送（SSE）

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
  - Define response model with fields: timestamp, signal, confidence, price
  
  **References**:
  - `webapi/schemas/watchlist.py` - existing schemas
  
  **Acceptance Criteria**:
  - [ ] Schema defined with proper types
  - [ ] Includes all required fields

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
    1. curl -s http://localhost:8000/api/v1/watchlist/1/analysis-history | python -m json.tool
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

- [ ] 1.5 Add ownership validation (403 if not owner)

  **What to do**:
  - Check current user owns the watchlist item
  - Return 403 if not owner
  
  **References**:
  - Existing routes with ownership check
  
  **Acceptance Criteria**:
  - [ ] Returns 403 for non-owner access
  - [ ] Returns 200 for owner access

- [ ] 1.6 Add 404 handling for non-existent watchlist

  **What to do**:
  - Return 404 if watchlist ID doesn't exist
  
  **Acceptance Criteria**:
  - [ ] Returns 404 for invalid ID

- [ ] 1.7 Test API endpoint with curl

  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Steps:
    1. Start API server
    2. curl -s http://localhost:8000/api/v1/watchlist/1/analysis-history
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

- [ ] 2.2 Add error handling with retry logic

  **What to do**:
  - Wrap API call in try-except
  - Add retry mechanism for transient errors
  
  **Acceptance Criteria**:
  - [ ] Retries on network error
  - [ ] Returns empty list on persistent error

- [ ] 2.3 Cache analysis history in session_state

  **What to do**:
  - Store fetched data in st.session_state
  - Avoid redundant API calls
  
  **Acceptance Criteria**:
  - [ ] Data cached after first fetch
  - [ ] Cache invalidated on refresh

- [ ] 2.4 Add refresh mechanism after trigger_quick_analysis

  **What to do**:
  - Clear cache after triggering analysis
  - Auto-refresh after analysis completes
  
  **Acceptance Criteria**:
  - [ ] Cache cleared on analysis trigger
  - [ ] New data fetched after completion

- [ ] 3.1 Modify `render_candlestick_chart()` signature

  **What to do**:
  - Add `analysis_data: Optional[List[Dict]] = None` parameter
  - Update all call sites
  
  **References**:
  - `web/components/watchlist_manager.py:63-129`
  
  **Acceptance Criteria**:
  - [ ] Function accepts analysis_data parameter
  - [ ] Backward compatible (None = no markers)

- [ ] 3.2 Add signal-to-Kline mapping function

  **What to do**:
  - Create function to map analysis timestamp to K-line x-axis position
  - Use nearest neighbor matching
  
  **Acceptance Criteria**:
  - [ ] Returns x-index for each analysis timestamp
  - [ ] Handles timestamps outside K-line range

- [ ] 3.3 Implement BUY signal marker

  **What to do**:
  - Add green upward arrow annotation
  - Show confidence percentage
  
  **References**:
  - Plotly `add_annotation()` documentation
  
  **Acceptance Criteria**:
  - [ ] Green arrow displayed at BUY timestamp
  - [ ] Arrow points upward
  - [ ] Confidence label shown

- [ ] 3.4 Implement SELL signal marker

  **What to do**:
  - Add red downward arrow annotation
  - Show confidence percentage
  
  **Acceptance Criteria**:
  - [ ] Red arrow displayed at SELL timestamp
  - [ ] Arrow points downward
  - [ ] Confidence label shown

- [ ] 3.5 Implement HOLD signal marker

  **What to do**:
  - Add yellow horizontal line annotation
  - Show confidence percentage
  
  **Acceptance Criteria**:
  - [ ] Yellow line displayed at HOLD timestamp
  - [ ] Horizontal orientation
  - [ ] Confidence label shown

- [ ] 3.6 Add "尚无AI信号" caption

  **What to do**:
  - Display caption when analysis_data is empty
  
  **Acceptance Criteria**:
  - [ ] Caption shown when no analysis
  - [ ] Caption hidden when analysis exists

- [ ] 4.1 Implement trade pair detection

  **What to do**:
  - Identify BUY→SELL and SELL→BUY sequences
  - Pair consecutive trading signals
  
  **Acceptance Criteria**:
  - [ ] Correctly pairs BUY followed by SELL
  - [ ] Correctly pairs SELL followed by BUY
  - [ ] Skips HOLD signals in pairing

- [ ] 4.2 Add profit/loss calculation

  **What to do**:
  - Calculate P&L for each trade pair
  - BUY→SELL: profit if sell > buy
  - SELL→BUY: profit if buy < sell
  
  **Acceptance Criteria**:
  - [ ] Correct profit calculation
  - [ ] Correct loss calculation
  - [ ] Returns P&L percentage

- [ ] 4.3 Draw green solid line for profitable trades

  **What to do**:
  - Use Plotly `add_shape()` with line
  - Color: #4CAF50
  - Style: solid
  
  **Acceptance Criteria**:
  - [ ] Green line connects profitable pairs
  - [ ] Line style is solid

- [ ] 4.4 Draw red dashed line for loss trades

  **What to do**:
  - Use Plotly `add_shape()` with line
  - Color: #F44336
  - Style: dashed
  
  **Acceptance Criteria**:
  - [ ] Red line connects loss pairs
  - [ ] Line style is dashed

- [ ] 4.5 Add hover tooltip with trade details

  **What to do**:
  - Add hover text to connecting lines
  - Show entry price, exit price, P&L
  
  **Acceptance Criteria**:
  - [ ] Hover shows trade details
  - [ ] Format: "Entry: ¥X.XX, Exit: ¥X.XX, P&L: +X.X%"

- [ ] 5.1 Update `render_monitoring_panel()`

  **What to do**:
  - Fetch analysis history
  - Pass to render_candlestick_chart()
  
  **Acceptance Criteria**:
  - [ ] Fetches analysis data
  - [ ] Displays signals on charts

- [ ] 5.2 Update multi-stock charts

  **What to do**:
  - Each stock chart shows its own signals
  
  **Acceptance Criteria**:
  - [ ] Multi-stock view shows all signals
  - [ ] No signal overlap between stocks

- [ ] 5.3 Update detail view chart

  **What to do**:
  - Detail view shows full trajectory
  
  **Acceptance Criteria**:
  - [ ] Detail view shows complete trade history
  - [ ] Trajectory lines visible

- [ ] 5.4 Add signal marker click handler

  **What to do**:
  - Click signal scrolls to analysis detail
  
  **Acceptance Criteria**:
  - [ ] Click handler registered
  - [ ] Scrolls to correct position

- [ ] 6.1 Add error banner component

  **What to do**:
  - Create reusable error banner
  - Red background, error message, retry button
  
  **Acceptance Criteria**:
  - [ ] Banner displays on API error
  - [ ] Retry button re-fetches data

- [ ] 6.2 Add loading spinner

  **What to do**:
  - Show spinner during analysis fetch
  
  **Acceptance Criteria**:
  - [ ] Spinner shown during loading
  - [ ] Spinner hidden after complete

- [ ] 7.1 Test API with curl

  **QA Scenario**:
  ```
  Tool: Bash
  Steps:
    1. curl http://localhost:8000/api/v1/watchlist/1/analysis-history
    2. Verify JSON structure
    3. Verify field types
  Expected: Valid JSON with required fields
  ```

- [ ] 7.2 Test K-line with single signal

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Steps:
    1. Navigate to watchlist page
    2. Select stock with one analysis
    3. Verify signal marker visible
  Expected: Single marker displayed correctly
  ```

- [ ] 7.3 Test K-line with multiple signals

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Steps:
    1. Select stock with multiple analyses
    2. Verify all markers visible
    3. Verify no overlap
  Expected: All markers displayed correctly
  ```

- [ ] 7.4 Test trajectory lines

  **QA Scenario**:
  ```
  Tool: Playwright (browser)
  Steps:
    1. Select stock with BUY→SELL sequence
    2. Verify green/red line visible
    3. Hover over line verify tooltip
  Expected: Trajectory line with correct color and tooltip
  ```

- [ ] 7.5 Test error states

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

- [ ] 7.6 E2E test: trigger analysis → see signal

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

- [ ] F1. **API Compliance Audit** - `oracle`
  - Verify all API endpoints return correct format
  - Verify error codes (404, 403, 200)
  - Verify ownership validation works

- [ ] F2. **Chart Rendering Review** - `visual-engineering`
  - All signal markers display correctly
  - Trajectory lines render properly
  - Colors match spec (green/red/yellow)

- [ ] F3. **Error Handling Verification** - `unspecified-high`
  - Network errors show retry button
  - API errors show clear messages
  - Loading states work correctly

- [ ] F4. **E2E Integration Test** - `deep`
  - Full flow: add stock → trigger analysis → see signal on K-line
  - Multiple stocks with signals
  - Error recovery flow

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
curl -s http://localhost:8000/api/v1/watchlist/1/analysis-history | python -m json.tool

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
