# K线信号叠加与买卖连线可视化

## TL;DR

> **问题**: 自选股K线图只显示价格数据，AI分析信号（BUY/SELL/HOLD）只在表格中显示为文本，没有与K线图关联。用户无法直观看到信号产生时的价格位置和时机。
> 
> **方案**: 在K线图上叠加信号标记（箭头+置信度），并用线条连接连续买卖信号形成交易轨迹（盈利=绿实线，亏损=红虚线）
> 
> **交付物**: 后端API + 增强K线图渲染 + 错误状态提示
> **估算**: 中等复杂度（38个任务）
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
5. `WatchlistAnalysis` 模型缺少 price 字段和 error 状态字段
6. 分析完成后数据没有回填到 `WatchlistAnalysis` 记录

### 相关文件
- `web/components/watchlist_manager.py:63-129` - `render_candlestick_chart()` 纯价格K线
- `web/components/watchlist_manager.py:706-845` - `render_monitoring_panel()` 信号文本显示
- `webapi/routers/watchlist.py:32-81` - Pydantic schemas (内联定义)
- `webapi/routers/watchlist.py:608-643` - `quick_analyze` 端点
- `webapi/models/database.py:277-356` - `WatchlistAnalysis` ORM模型

---

## Work Objectives

### Core Objective
实现K线图与AI分析信号的叠加显示，用买卖连线可视化交易轨迹，提升分析结果的可读性。

### Concrete Deliverables
1. **数据库增强**: 添加 price, error_message 字段到 WatchlistAnalysis
2. **分析结果回填**: 任务完成后更新 WatchlistAnalysis 记录
3. **后端API**: `GET /api/v1/watchlist/{id}/analysis-history`
4. **前端增强**: `render_candlestick_chart()` 支持信号标记叠加
5. **轨迹可视化**: 买卖信号连线（盈利=绿实线，亏损=红虚线）
6. **错误处理**: 分析失败时显示明确错误信息

### Definition of Done
- [ ] WatchlistAnalysis 包含 price 和 error_message 字段
- [ ] 分析完成后自动回填 signal/confidence/price/error
- [ ] API返回分析历史时间序列（timestamp, signal, confidence, price, error）
- [ ] K线图显示BUY(🟢↑)、SELL(🔴↓)、HOLD(🟡→)标记
- [ ] 连续买卖信号用线条连接
- [ ] 分析失败时显示红色错误提示
- [ ] 端到端测试通过

### Must Have
- 信号标记准确对应K线时间点
- 盈利/亏损连线样式区分
- 错误状态友好提示

### Must NOT Have
- 不修改分析引擎核心逻辑（遵守Upstream Isolation Principle）
- 不引入新的数据源
- 不实现实时推送（SSE）
- ~~API权限验证（暂不需要，当前无用户系统）~~

---

## Verification Strategy

### Test Decision
- **测试策略**: 端到端测试 + 手动验证
- **Agent-Executed QA**: 每个任务包含自动化验证场景

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Backend - Database & Data Flow):
├── 0.1 Add price column to WatchlistAnalysis model (Alembic migration)
├── 0.2 Add error_message column to WatchlistAnalysis model
├── 0.3 Modify analysis completion callback to update WatchlistAnalysis
├── 1.1 Add get_analysis_history() method to WatchlistAnalysis model
├── 1.2 Create WatchlistAnalysisHistoryResponse schema in router
├── 1.3 Implement GET /analysis-history endpoint
└── 1.4 Add limit parameter and error handling

Wave 2 (Frontend - Data Layer):
├── 2.1 Add get_analysis_history() function
├── 2.2 Add error handling with retry
├── 2.3 Cache analysis history in session_state
└── 2.4 Refresh after trigger_quick_analysis

Wave 3 (Frontend - Chart Enhancement):
├── 3.1 Modify render_candlestick_chart() signature
├── 3.2 Add signal-to-Kline mapping function
├── 3.3 Implement BUY signal marker (green upward arrow)
├── 3.4 Implement SELL signal marker (red downward arrow)
├── 3.5 Implement HOLD signal marker (yellow horizontal line)
└── 3.6 Add "尚无AI信号" caption when empty

Wave 4 (Frontend - Trajectory):
├── 4.1 Implement trade pair detection (BUY→SELL, SELL→BUY)
├── 4.2 Add profit/loss calculation logic
├── 4.3 Draw green solid line for profitable trades
├── 4.4 Draw red dashed line for loss trades
├── 4.5 Add hover tooltip with trade details
└── 4.6 Ensure HOLD signals don't create connections

Wave 5 (Frontend - Error Handling):
├── 5.1 Add error banner component for API errors
├── 5.2 Add retry button for network errors
├── 5.3 Display specific error messages from API
└── 5.4 Add loading spinner during analysis fetch

Wave 6 (Integration):
├── 6.1 Update render_monitoring_panel() to fetch analysis history
├── 6.2 Update multi-stock charts to show signals
├── 6.3 Update detail view chart to show trajectory
└── 6.4 Add signal marker click handler

Wave FINAL (Verification):
├── DB migration test
├── API test with curl
├── Single signal K-line test
├── Multiple signals test
├── Trajectory lines test
├── Error states test
└── E2E test: trigger analysis → see signal
```

---

## TODOs

### Wave 0: Database & Data Flow (Prerequisites)

- [ ] 0.1 Add price column to WatchlistAnalysis model

  **What to do**:
  - Add `price` column (Float, nullable) to WatchlistAnalysis model
  - Create Alembic migration
  - Apply migration
  
  **References**:
  - `webapi/models/database.py:277-356` - WatchlistAnalysis class
  
  **Acceptance Criteria**:
  - [ ] price column exists in database
  - [ ] Migration applies without error
  
  **QA Scenario**:
  ```
  Tool: Bash
  Steps:
    1. alembic revision --autogenerate -m "add price to watchlist_analysis"
    2. alembic upgrade head
    3. psql -c "\d watchlist_analyses" | grep price
  Expected: price column exists
  ```

- [ ] 0.2 Add error_message column to WatchlistAnalysis model

  **What to do**:
  - Add `error_message` column (Text, nullable) to model
  - Update Alembic migration
  
  **Acceptance Criteria**:
  - [ ] error_message column exists
  
  **QA Scenario**:
  ```
  Tool: Bash
  Steps:
    1. psql -c "\d watchlist_analyses" | grep error_message
  Expected: error_message column exists
  ```

- [ ] 0.3 Modify analysis completion to update WatchlistAnalysis

  **What to do**:
  - Find where AnalysisTask status changes to "completed" or "failed"
  - Add callback to update corresponding WatchlistAnalysis record
  - Extract signal/confidence/price/error from AnalysisTask result
  
  **References**:
  - `webapi/services/analysis_service.py` - analysis completion logic
  - `webapi/models/database.py:277-356` - WatchlistAnalysis
  
  **Acceptance Criteria**:
  - [ ] WatchlistAnalysis updated when analysis completes
  - [ ] Signal, confidence, price populated on success
  - [ ] Error_message populated on failure
  
  **QA Scenario**:
  ```
  Tool: Bash + Python
  Steps:
    1. Trigger quick analysis via API
    2. Wait for completion
    3. Query DB: SELECT signal, confidence, price FROM watchlist_analyses WHERE id=X
  Expected: Fields populated correctly
  ```

### Wave 1: Backend API

- [ ] 1.1 Add get_analysis_history() to WatchlistAnalysis model

  **What to do**:
  - Add classmethod to query by watchlist_id
  - Support limit parameter (default 50)
  - Order by created_at DESC
  
  **References**:
  - `webapi/models/database.py:277-356` - WatchlistAnalysis
  
  **Acceptance Criteria**:
  - [ ] Returns List[WatchlistAnalysis]
  - [ ] Respects limit parameter
  - [ ] Ordered by timestamp descending
  
  **QA Scenario**:
  ```
  Tool: Python REPL
  Steps:
    1. from webapi.models.database import WatchlistAnalysis
    2. result = WatchlistAnalysis.get_analysis_history(1, limit=5)
    3. print(len(result), result[0].signal if result else None)
  Expected: Returns list with correct fields
  ```

- [ ] 1.2 Create WatchlistAnalysisHistoryResponse schema

  **What to do**:
  - Add schema in `webapi/routers/watchlist.py` (inline with existing schemas)
  - Fields: timestamp, signal, confidence, price, error_message
  
  **References**:
  - `webapi/routers/watchlist.py:32-81` - existing schemas
  
  **Acceptance Criteria**:
  - [ ] Schema defined with correct types
  
  **QA Scenario**:
  ```
  Tool: Python REPL
  Steps:
    1. from webapi.routers.watchlist import WatchlistAnalysisHistoryResponse
    2. schema = WatchlistAnalysisHistoryResponse(timestamp="2024-01-01", signal="BUY", confidence=0.85, price=10.5)
    3. print(schema.dict())
  Expected: Valid schema instance
  ```

- [ ] 1.3 Implement GET /analysis-history endpoint

  **What to do**:
  - Add route handler in watchlist router
  - Call get_analysis_history()
  - Return formatted response
  
  **References**:
  - `webapi/routers/watchlist.py` - add after quick_analyze route
  
  **Acceptance Criteria**:
  - [ ] Endpoint returns 200 with analysis list
  - [ ] Correct JSON format
  
  **QA Scenario**:
  ```
  Tool: Bash (curl)
  Steps:
    1. curl -s http://localhost:8000/api/v1/watchlist/1/analysis-history | python -m json.tool
  Expected: JSON array with timestamp, signal, confidence, price, error_message
  ```

- [ ] 1.4 Add li
