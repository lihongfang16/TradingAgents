# 自选股增量分析功能

## TL;DR

> **Quick Summary**: 为自选股列表增加三种分析按钮（全量分析 / 增量分析 / 查看差异），增量分析利用数据变化检测器选择性刷新已变化的分析师，目标 1-3 分钟出结果。同时支持自动（监控触发）和手动（用户点击）两种模式。
> 
> **Deliverables**:
> - 数据变化检测模块 `webapi/services/change_detection.py`
> - 增量分析 API 端点 `POST /api/v1/watchlist/{id}/incremental-analyze`
> - 差异报告 API 端点 `POST /api/v1/analysis/diff-report`
> - 自选股 UI 三按钮布局 + 差异展示弹窗
> - DB schema: `watchlist_analyses.analysis_type` 新增 `'incremental'` 值
> 
> **Estimated Effort**: Medium (3-4 waves)
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: W1-T1 → W2-T2 → W3-T1 → W4

---

## Context

### Original Request
用户希望自选股列表有多个分析按钮：全量分析完成后增量分析按钮可用，点击 1-3 分钟出结果。增量分析与监控功能结合。

### Interview Summary
**Key Decisions**:
- "增量"定义 = 只刷新数据发生变化的分析师（方案 B），不是 fast_mode 加速（方案 D）
- 需要"查看差异"按钮，纯 diff 不调 LLM，秒级响应
- 变化检测：自动 + 手动两种模式
- 必须遵守上游隔离原则

**Research Findings**:
- `CachedAnalysisRunner` 已有 per-analyst 缓存（market=15min, sentiment/news=2hr, fundamentals=24hr）
- 数据源全部实时获取（Mairui→Ashare→AkShare→BaoStock），无数据级变化检测
- 现有 `detect_turning_point()` 只比较分析结果（signal/confidence），不比较原始数据
- `AnalystReportCache` 表已有 `expires_at` 和 `is_valid` 字段
- `WatchlistAnalysis.analysis_type` 已有 `'full'`/`'quick'`/`'turning'` 三个值

### Metis Review (Pre-Execution)
**Identified Gaps** (all addressed):

**Critical:**
- `AnalysisService._run_sync_analysis()` 使用 `AnalysisRunner` 而非 `CachedAnalysisRunner` → T3 直接实例化 `CachedAnalysisRunner`，不走 `AnalysisService` 路径（符合上游隔离原则）

**Ambiguous (defaults applied):**
- News 数据源返回实时行情而非真实新闻 → T1 尝试 `akshare.stock_news_em()`，失败则视为"无变化"
- 分析过程中价格变化（如 15:00 收盘）→ 存储 `detection_timestamp`，分析基于检测时刻数据
- Diff 性能 → 使用 stdlib `difflib`（非 DeepDiff），预截断至 5KB
- 并发分析去重 → 复用 `AnalystReportCache` advisory lock 模式
- 调度器 turning detection 与增量冲突 → 排除 `analysis_type='incremental'`

**Minor (auto-resolved):**
- 新增边界值测试（价格恰好 2%）、非对称分析师覆盖、并发请求 409、分析中按钮全禁用、手动模式取消全选、precheck 无变化、停牌/空数据容错

**Scope locked down (explicitly out of scope):**
- 不改造 AnalysisService 使用 CachedAnalysisRunner
- 不做 per-stock 阈值配置、历史 diff、多股票批量 diff、WebSocket 实时推送、LLM 生成 diff 摘要

---

## Work Objectives

### Core Objective
在自选股列表中实现三种分析模式：全量分析、增量分析（选择性刷新）、差异查看（纯 diff），支持自动和手动触发。

### Analyst Naming Convention
**统一命名**：外部 API/UI 使用 `sentiment`，内部 graph/cache 使用 `social`。
- `CachedAnalysisRunner` 已有别名映射：`social` → `sentiment`（`cached_analysis_runner.py:51-57`）
- API 返回值使用 `sentiment`（用户友好）
- precheck 结果使用 `sentiment`
- `CachedAnalysisRunner.analysts` 参数使用 `social`（graph 要求）
- 变化检测返回格式：`{"market": True, "news": True, "sentiment": False, "fundamentals": False}`
- 调用 runner 前映射：`runner_analysts = [a if a != "sentiment" else "social" for a in all_analysts]`

### Concrete Deliverables
- `webapi/services/change_detection.py` — 数据变化检测器（自动+手动模式）
- `POST /api/v1/watchlist/{id}/incremental-analyze` — 增量分析端点
 - `POST /api/v1/analysis/diff-report` — 差异报告端点（request body 含 task_id_1, task_id_2）
- 自选股 UI 三按钮 + 差异弹窗

### Definition of Done
- [ ] 全量分析按钮：今日无全量结果时可点击，提交 4 分析师完整流程
- [ ] 增量分析按钮：今日已有全量结果时可点击，只刷新变化的分析师，1-3 分钟完成
- [ ] 查看差异按钮：今日有两次以上分析时可点击，秒级显示差异，不调用 LLM
- [ ] 按钮可用性正确：灰色禁用状态 + tooltip 提示原因
- [ ] API 端点返回 `analysis_type='incremental'` / `'diff'`
- [ ] 差异报告包含：每个分析师的变化类型、关键指标变化、LLM 输出 diff

### Must Have
- 增量分析必须复用 CachedAnalysisRunner 的缓存机制
- 查看差异必须不调用任何 LLM（纯文本比较）
- 所有新代码在 `webapi/` 或 `web/` 下，不修改 `tradingagents/` 核心
- 变化检测阈值使用全局默认值，v1 不提供 UI 配置入口

### Must NOT Have (Guardrails)
- 不修改 `tradingagents/graph/` 下的任何文件（上游隔离）
- 不修改 `tradingagents/agents/` 下的 agent 实现
- 不引入新的数据源或 API
- 不修改 `CachedAnalysisRunner` 的缓存 key 结构和 TTL 逻辑
- 差异报告不调用 LLM 生成摘要（纯 diff）
- 不使用 Redis/MongoDB — PostgreSQL only
- 不改造 `AnalysisService` 使用 `CachedAnalysisRunner`（T3 直接实例化 `CachedAnalysisRunner`）
- 不做 per-stock 阈值配置（v1 全局默认，v2 再做）
- 不做历史 diff（v1 仅今日，v2 再做）
- 不做多股票批量 diff（v1 单股票）
- 不做 WebSocket 实时推送（v1 polling 足够）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest + playwright)
- **Automated tests**: YES (tests-after for each task)
- **Framework**: pytest + requests (API) + playwright (UI)
- **Agent-Executed QA**: EVERY task includes QA scenarios

### QA Policy
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.
- **API endpoints**: curl + JSON assertion
- **UI components**: Playwright (screenshot + DOM assertion)
- **Change detection**: Unit test with mock data

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — independent modules):
├── T1: Data Change Detection Module [unspecified-high]
├── T2: Diff Report Generator [unspecified-high]
└── T3: Incremental Analysis Service [unspecified-high]

Wave 2 (API + DB — depends on Wave 1):
├── T4: Incremental Analyze API Endpoint [quick]
├── T5: Diff Report API Endpoint [quick]
├── T6: Alembic Migration (analysis_type='incremental') [quick]

Wave 3 (Frontend — depends on Wave 2):
├── T7: Watchlist UI Three-Button Layout [visual-engineering]
├── T8: Diff Report Modal Component [visual-engineering]
└── T9: Manual Analyst Selector (增量分析时可选手动刷新) [unspecified-high]

Wave FINAL (Integration + Verification):
├── F1: End-to-End API Test [unspecified-high]
├── F2: End-to-End UI Test [unspecified-high]
└── F3: Scope Fidelity Check [deep]

Critical Path: T1/T2/T3 → T4/T5 → T7 → F1/F2/F3
Parallel Speedup: ~60%
Max Concurrent: 3 (Wave 1), 3 (Wave 2), 3 (Wave 3), 3 (Wave FINAL)
```

### Agent Dispatch Summary
- **W1**: **3** — T1→`unspecified-high`, T2→`unspecified-high`, T3→`unspecified-high`
- **W2**: **3** — T4→`quick`, T5→`quick`, T6→`quick`
- **W3**: **3** — T7→`visual-engineering`, T8→`visual-engineering`, T9→`unspecified-high`
- **FINAL**: **3** — F1→`unspecified-high`, F2→`unspecified-high`, F3→`deep`

---

## TODOs

---

- [ ] 1. Data Change Detection Module

  **What to do**:
  - Create `webapi/services/change_detection.py`
  - Define `ChangeDetector` class with per-analyst-type change detection functions
  - **market analyst**: compare current price vs last cached price → threshold (default 2%)
  - **news analyst**: compare latest news timestamp vs last analysis time → any new news
  - **sentiment analyst**: derive from news change (same trigger as news)
  - **fundamentals analyst**: compare fundamentals data version → 日内默认不变化
  - Provide `auto_detect(symbol, last_analysis_time, thresholds)` → `Dict[str, bool]` (which analysts need refresh)
  - Provide `manual_detect(symbol, selected_analysts)` → `Dict[str, bool]` (user overrides)
  - Default thresholds: `{"market": 0.02, "news": True, "sentiment": True, "fundamentals": False}`
  - 获取最新价格: 调用 `ChinaDataManager.get_realtime_quote(symbol)` 或 `get_kline(symbol, "day", 1)` 获取最新一条
  - 获取最新新闻时间: 调用 AkShare `stock_news_em(symbol)` 获取最新一条的 `datetime` 字段

  **Must NOT do**:
  - 不修改 `tradingagents/` 下的任何文件
  - 不直接修改 `CachedAnalysisRunner` 的缓存逻辑
  - 不引入新的数据库表（使用现有 `analyst_report_cache` 表）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要理解数据源接口、缓存 TTL、阈值逻辑，中等复杂度
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `backtest-expert`: 这是交易策略回测，不是数据变化检测

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T2, T3)
  - **Parallel Group**: Wave 1
  - **Blocks**: T4 (incremental endpoint depends on this)
  - **Blocked By**: None

  **References**:

  **Data source interfaces (read-only, for understanding API surface)**:
  - `tradingagents/dataflows/china_data_manager.py:ChinaDataManager` — `get_realtime_quote()`, `get_kline()` 接口
  - `tradingagents/dataflows/interface.py:route_to_vendor()` — 数据路由逻辑
  - `tradingagents/agents/utils/news_data_tools.py` — `get_news` tool 定义

  **Cache TTL reference (for understanding when cache is valid)**:
  - `webapi/models/database.py:AnalystReportCache.TTL_CONFIG` — market=900, sentiment=7200, news=7200, fundamentals=86400

  **Existing change detection (reuse pattern)**:
  - `webapi/services/scheduler_service.py:detect_turning_point()` — 现有 turning detection 逻辑
  - `webapi/services/scheduler_service.py:should_use_high_frequency()` — 高频模式判断

  **AkShare news API reference**:
  - `tradingagents/dataflows/interface.py:152` — `_china_get_news()` → 当前返回 `get_realtime_quote()` 作为新闻替代
  - 需要直接调用 `akshare.stock_news_em(symbol)` 获取带时间戳的新闻列表

  **Acceptance Criteria**:

  **If TDD**:
  - [ ] Test file: `tests/test_change_detection.py`
  - [ ] `pytest tests/test_change_detection.py -v` → PASS

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Auto-detect — price unchanged, no new news
    Tool: Bash (python -c)
    Preconditions: Mock data with last_price=4.03, current_price=4.03, no new news
    Steps:
      1. from webapi.services.change_detection import ChangeDetector
      2. result = detector.auto_detect("002172", last_analysis_time, thresholds)
      3. assert result["market"] == False
      4. assert result["news"] == False
    Expected Result: Only fundamentals returns False (unchanged by default), rest False
    Evidence: .sisyphus/evidence/task-1-auto-detect-no-change.txt

  Scenario: Auto-detect — price changed >2%, new news available
    Tool: Bash (python -c)
    Preconditions: last_price=4.03, current_price=4.15, new_news_time > last_analysis_time
    Steps:
      1. result = detector.auto_detect("002172", last_analysis_time, thresholds)
      2. assert result["market"] == True
      3. assert result["news"] == True
    Expected Result: market and news need refresh, others not
    Evidence: .sisyphus/evidence/task-1-auto-detect-change.txt

  Scenario: Manual-detect — user selects only market and news
    Tool: Bash (python -c)
    Preconditions: thresholds={"market": 0.02, "news": True, "sentiment": True, "fundamentals": False}
    Steps:
      1. result = detector.manual_detect("002172", ["market", "news"])
      2. assert result["market"] == True
      3. assert result["news"] == True
      4. assert result["fundamentals"] == False
    Expected Result: Only selected analysts return True
    Evidence: .sisyphus/evidence/task-1-manual-detect.txt

  Scenario: Boundary value — price change exactly at 2% threshold
    Tool: Bash (python -c)
    Preconditions: last_price=10.00, current_price=10.20, threshold=0.02
    Steps:
      1. result = detector.auto_detect("002172", last_analysis_time, {"market": 0.02})
      2. assert result["market"] == True  # ≥ threshold triggers refresh
    Expected Result: Exact boundary value triggers refresh
    Evidence: .sisyphus/evidence/task-1-boundary-threshold.txt

  Scenario: Fallback — 停牌 (trading halt), no price data
    Tool: Bash (python -c)
    Preconditions: get_realtime_quote returns None/empty
    Steps:
      1. result = detector.auto_detect("600xxx", last_analysis_time, thresholds)
      2. assert result["market"] == False  # 停牌 = no change
      3. No exception raised
    Expected Result: Graceful handling, no crash, market marked as unchanged
    Evidence: .sisyphus/evidence/task-1-suspended-stock.txt
  ```

  **Commit**: YES (groups with T2, T3)
  - Message: `feat(watchlist): add data change detection module for incremental analysis`
  - Files: `webapi/services/change_detection.py`, `tests/test_change_detection.py`

---

- [ ] 2. Diff Report Generator

  **What to do**:
  - Create `webapi/services/diff_report.py`
  - Define `DiffReportGenerator` class
  - `generate(task_id_1, task_id_2) -> Dict[str, Any]`:
    - 从 DB 获取两个任务的 `llm_streams`（已有 per-agent 输出）
    - 从 DB 获取两个任务的 `final_state`（包含 reports 和 debate states）
    - 对每个分析师：生成 diff（文本对比）
    - 对关键指标：生成数值变化（价格、confidence、signal）
    - 返回结构：
      ```python
      {
        "analysts": {
          "market_analyst": {
            "changed": True,
            "change_type": "content_changed",
            "price_before": 4.03,
            "price_after": 4.15,
            "diff_summary": "价格从4.03上涨至4.15...",
            "old_preview": "...前200字...",
            "new_preview": "...前200字..."
          },
          ...
        },
        "decision": {
          "signal_before": "HOLD",
          "signal_after": "BUY",
          "signal_changed": True
        },
        "confidence": {
          "before": 75,
          "after": 88,
          "delta": 13
        },
        "timestamp_range": "14:30 → 15:45"
      }
      ```
  - 使用 Python 内置 `difflib` 进行文本 diff（不需要额外依赖）
  - Truncate long diffs（每段最多 500 字）

  **Must NOT do**:
  - 不调用任何 LLM 生成摘要
  - 不修改已有数据结构

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1, T3)
  - **Parallel Group**: Wave 1
  - **Blocks**: T5 (diff endpoint depends on this)

  **References**:
  - `webapi/models/database.py:AnalysisTask.llm_streams` — per-agent LLM 输出 JSONB
  - `webapi/models/database.py:AnalysisTask.result["final_state"]` — 包含所有 report 字段
  - `webapi/models/database.py:AnalysisTask.result["signal"]` — signal processing 结果

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Generate diff between two completed analysis tasks
    Tool: Bash (python -c)
    Preconditions: DB has two completed tasks for symbol 002172 with different results
    Steps:
      1. from webapi.services.diff_report import DiffReportGenerator
      2. gen = DiffReportGenerator(db_session)
      3. report = gen.generate(task_id_1, task_id_2)
      4. assert "analysts" in report
      5. assert report["decision"]["signal_changed"] in [True, False]
      6. assert len(report["analysts"]) > 0
    Expected Result: Structured diff report with all sections populated
    Evidence: .sisyphus/evidence/task-2-diff-generate.txt

  Scenario: Same task diff should return empty
    Tool: Bash (python -c)
    Steps:
      1. report = gen.generate(same_task_id, same_task_id)
      2. assert report["decision"]["signal_changed"] == False
    Expected Result: All analysts show changed=False
    Evidence: .sisyphus/evidence/task-2-diff-same.txt

  Scenario: Asymmetric analyst coverage — one task partial
    Tool: Bash (python -c)
    Preconditions: task_1 has 4 analysts, task_2 has 2 analysts (partial failure)
    Steps:
      1. report = gen.generate(task_id_full, task_id_partial)
      2. assert "market_analyst" in report["analysts"]
      3. Missing analysts marked as "missing" or handled gracefully
    Expected Result: No crash, partial comparison succeeds
    Evidence: .sisyphus/evidence/task-2-asymmetric-analysts.txt
  ```

  **Commit**: YES (groups with T1, T3)
  - Message: `feat(watchlist): add diff report generator for analysis comparison`
  - Files: `webapi/services/diff_report.py`, `tests/test_diff_report.py`

---

- [ ] 3. Incremental Analysis Service

  **What to do**:
  - Create `webapi/services/incremental_analysis_service.py`
  - Define `IncrementalAnalysisService` class
  - `run_incremental(symbol, analysis_date, options) -> Dict[str, Any]`:
    1. 检测今日是否有全量分析结果（查 `watchlist_analyses` 表：`analysis_type='full'` + `completed_at IS NOT NULL` + `error_message IS NULL` + `DATE(created_at) = TODAY`）
    2. 检查是否有正在运行的分析任务（`analysis_tasks.status='RUNNING'` for same symbol）→ 如有则返回 409
    3. 调用 `ChangeDetector.auto_detect()` 获取需要刷新的分析师
    4. **直接实例化 `CachedAnalysisRunner`**（不走 `AnalysisService` 路径）：
       - 创建 `AnalysisCacheService()` 实例
       - **先失效变化分析师的缓存**：`cache_service.invalidate_cache(symbol, analyst_type)` 对每个 `needs_refresh` 中的分析师调用
       - 传入**完整的分析师列表** `analysts=["market", "news", "social", "fundamentals"]`（sentiment→social 映射）
       - `runner = CachedAnalysisRunner(symbol=..., date=..., analysts=all_analysts, cache_service=cache_service, ...)`
       - `runner.run()` → `CachedAnalysisRunner` 会检查缓存：已失效的（needs_refresh）重新执行 LLM 调用，有效的（未变化）秒级注入
       - 不需要 `force_refresh` 参数 — 通过 `invalidate_cache()` 精确控制哪些分析师需要重算
    5. 将结果持久化：创建 `AnalysisTask` 记录 + 更新 `WatchlistAnalysis` 记录 `analysis_type='incremental'`
    6. 返回任务信息（task_id, refresh_analysts, skipped_analysts）
  - **如果全量分析不存在**：返回错误 `{"error": "需要先完成今日全量分析"}`
  - **如果所有分析师缓存都未过期**：返回 `{"error": "数据无变化，无需增量分析"}` + 可选"强制全量"选项
  - **注意**：此服务不走 `AnalysisService.create_task()` + `run_analysis()` 路径，因为那条路径使用 `AnalysisRunner`（无缓存）。增量分析必须直接使用 `CachedAnalysisRunner` 以实现选择性刷新。

  **Must NOT do**:
  - 不走 `AnalysisService.create_task()` + `run_analysis()` 路径（那条路径使用无缓存的 `AnalysisRunner`）
  - 不修改 `AnalysisRunner` 或 `CachedAnalysisRunner` 的核心逻辑
  - 不修改 `subprocess_runner.py`（增量分析在 API 进程内同步执行，不经过 subprocess）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1, T2)
  - **Parallel Group**: Wave 1
  - **Blocks**: T4 (API endpoint depends on this)

  **References**:
  - `webapi/services/analysis_service.py:AnalysisService.create_task()` — 创建分析任务
  - `webapi/services/analysis_service.py:AnalysisService.run_analysis()` — 运行分析
  - `webapi/models/database.py:WatchlistAnalysis` — 记录分析类型
  - `webapi/services/change_detection.py` (T1) — 变化检测器
  - `webapi/models/analysis.py:AnalysisRequest` — 请求模型，`force_refresh` 字段
  - `tradingagents/core/cached_analysis_runner.py:CachedAnalysisRunner.__init__(cache_service=...)` — 缓存 runner 接口，需要 `AnalysisCacheService` 实例
  - `tradingagents/core/cached_analysis_runner.py:CachedAnalysisRunner.run()` — 缓存 runner 运行入口，自动检查缓存有效性
  - `webapi/services/analysis_cache_service.py:AnalysisCacheService.invalidate_cache(symbol, analyst_type)` — **关键**：失效特定分析师缓存（使 CachedAnalysisRunner 重算该分析师）
  - `webapi/services/analysis_cache_service.py:AnalysisCacheService` — 缓存服务，T3 必须创建此依赖

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Unit test — IncrementalAnalysisService.run_incremental() with mock data
    Tool: Bash (pytest)
    Preconditions: Mock CachedAnalysisRunner and ChangeDetector
    Steps:
      1. from webapi.services.incremental_analysis_service import IncrementalAnalysisService
      2. service = IncrementalAnalysisService(db_session)
      3. result = service.run_incremental("002172", date.today(), {"analysts": ["market"]})
      4. assert result["analysis_type"] == "incremental"
      5. assert "market" in result["refresh_analysts"]
    Expected Result: Service correctly orchestrates change detection + CachedAnalysisRunner
    Evidence: .sisyphus/evidence/task-3-unit-test.txt

  Scenario: Unit test — no full analysis today → error
    Tool: Bash (pytest)
    Preconditions: DB has no full analysis for symbol today
    Steps:
      1. result = service.run_incremental("002172", date.today())
      2. assert "error" in result
      3. assert "全量分析" in result["error"]
    Expected Result: Clear error when no full analysis exists
    Evidence: .sisyphus/evidence/task-3-no-full-unit.txt

  Scenario: Integration test — incremental with price change (via endpoint, after T4)
    Tool: Bash (curl)
    Preconditions: Today has full analysis, price changed >2%
    Steps:
      1. POST /api/v1/watchlist/{id}/incremental-analyze
      2. response.status_code == 200 (synchronous, returns result directly)
      3. response["analysis_type"] == 'incremental'
      4. response["refresh_analysts"] contains "market"
      5. response["skipped_analysts"] contains "sentiment" or "fundamentals"
    Expected Result: Only market analyst refreshed, others from cache, completes in <3 min
    Evidence: .sisyphus/evidence/task-3-incremental-price-change.txt

  Scenario: Incremental analysis rejected — no full analysis today
    Tool: Bash (curl)
    Steps:
      1. POST /api/v1/watchlist/{id}/incremental-analyze
      2. response.status_code == 400 or 409
      3. response.error contains "全量分析"
    Expected Result: Request rejected with clear error message
    Evidence: .sisyphus/evidence/task-3-incremental-no-full.txt

  Scenario: Incremental analysis — no data change
    Tool: Bash (curl)
    Preconditions: All analyst caches valid, no price change
    Steps:
      1. POST /api/v1/watchlist/{id}/incremental-analyze
      2. response contains "no change" message
    Expected Result: Graceful rejection suggesting to wait or force refresh
    Evidence: .sisyphus/evidence/task-3-incremental-no-change.txt

  Scenario: Concurrent incremental requests — second rejected
    Tool: Bash (curl parallel)
    Preconditions: First incremental already running for same symbol
    Steps:
      1. Submit two POST /incremental-analyze for same stock simultaneously
      2. First returns 200 (success), second returns 409 (conflict)
      3. Second response contains "already in progress"
    Expected Result: Deduplication prevents duplicate analysis runs
    Evidence: .sisyphus/evidence/task-3-concurrent-rejection.txt
  ```

  **Commit**: YES (groups with T1, T2)
  - Message: `feat(watchlist): add incremental analysis service with change detection`
  - Files: `webapi/services/incremental_analysis_service.py`, `tests/test_incremental_service.py`

---

- [ ] 4. Incremental Analyze API Endpoint

  **What to do**:
  - Add `POST /api/v1/watchlist/{watchlist_id}/incremental-analyze` to `webapi/routers/watchlist.py`
  - 创建 `IncrementalAnalyzeRequest` Pydantic model（可选 `force_refresh_analysts` 列表）
  - 调用 `IncrementalAnalysisService.run_incremental()`（同步执行，直接返回结果）
  - 记录 `WatchlistAnalysis(analysis_type='incremental', triggered_by='manual')`
  - Response: 同步返回 200 + 分析结果（不是 202 异步），因为增量分析走 `CachedAnalysisRunner` 直接执行

  **Must NOT do**:
  - 不修改现有 `quick_analyze` 端点
  - 不修改 `AnalysisService` 核心逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T5, T6)
  - **Parallel Group**: Wave 2
  - **Blocks**: T7 (UI depends on API)

  **References**:
  - `webapi/routers/watchlist.py:714-754` — `quick_analyze` 端点（参考模式）
  - `webapi/routers/watchlist.py:171-190` — `WatchlistAnalysisResponse` 模型
  - `webapi/services/incremental_analysis_service.py` (T3) — 增量分析服务
  - `webapi/models/database.py:WatchlistAnalysis` — ORM 模型（无 `status` 列，用 `completed_at IS NOT NULL` + `error_message IS NULL` 判断完成）

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: POST incremental-analyze endpoint
    Tool: Bash (curl)
    Preconditions: Valid watchlist_id, today has full analysis
    Steps:
      1. curl -X POST http://localhost:8000/api/v1/watchlist/1/incremental-analyze
      2. assert response.status_code == 200
      3. assert response["analysis_type"] == "incremental"
    Expected Result: Synchronous result returned (not 202 async)
    Evidence: .sisyphus/evidence/task-4-incremental-endpoint.txt
  ```

  **Commit**: YES
  - Message: `feat(api): add incremental-analyze endpoint for watchlist`
  - Files: `webapi/routers/watchlist.py`

---

- [ ] 5. Diff Report API Endpoint

  **What to do**:
  - Add `POST /api/v1/analysis/diff-report` to `webapi/routers/analysis.py`
  - Request body: `{"task_id_1": "...", "task_id_2": "...", "symbol": "002172"}`
  - 调用 `DiffReportGenerator.generate()`
  - 返回结构化 diff 报告
  - 如果两个任务不存在或状态不是 COMPLETED → 返回 404

  **Must NOT do**:
  - 不调用 LLM

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T4, T6)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8 (diff modal depends on this)

  **References**:
  - `webapi/routers/analysis.py` — 现有 analysis 路由（添加端点参考）
  - `webapi/services/diff_report.py` (T2) — DiffReportGenerator

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: POST diff-report endpoint with valid task IDs
    Tool: Bash (curl)
    Steps:
      1. curl -X POST http://localhost:8000/api/v1/analysis/diff-report -d '{"task_id_1":"...", "task_id_2":"..."}'
      2. assert response.status_code == 200
      3. assert "analysts" in response
      4. assert "decision" in response
    Expected Result: Structured diff report returned
    Evidence: .sisyphus/evidence/task-5-diff-endpoint.txt

  Scenario: Non-existent task ID returns 404
    Tool: Bash (curl)
    Steps:
      1. curl -X POST http://localhost:8000/api/v1/analysis/diff-report -d '{"task_id_1":"nonexistent-uuid", "task_id_2":"..."}'
      2. assert response.status_code == 404
    Expected Result: Clear error message, not 500
    Evidence: .sisyphus/evidence/task-5-diff-404.txt
  ```

  **Commit**: YES
  - Message: `feat(api): add diff-report endpoint for analysis comparison`
  - Files: `webapi/routers/analysis.py`

---

- [ ] 6. Alembic Migration (analysis_type='incremental')

  **What to do**:
  - 创建 migration `alembic/versions/xxx_add_incremental_analysis_type.py`
  - `analysis_type` 列的 CHECK 约束添加 `'incremental'` 值（如果使用 CHECK 约束）
  - 如果没有 CHECK 约束则无需 migration，只需确保代码中使用正确的值
  - **必须同时修改** `webapi/models/analysis.py:32`：`analysts` 默认值从 `["market", "news", "fundamentals"]` 改为 `["market", "news", "social", "fundamentals"]`
    - 原因：全量分析必须是 4 个分析师 baseline，增量 diff 对比才有意义
    - social=sentiment，graph 层缓存使用 social 命名

  **Must NOT do**:
  - 不修改现有数据

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T4, T5)
  - **Parallel Group**: Wave 2
  - **Blocks**: None

  **References**:
  - `webapi/models/database.py:WatchlistAnalysis` — line 349: `analysis_type = Column(String(20), nullable=False)`
  - `alembic/` — 现有 migrations 结构
  - `webapi/models/database.py:WatchlistAnalysis.__table_args__` — 现有 indexes

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Migration applied successfully
    Tool: Bash (alembic upgrade head)
    Steps:
      1. alembic upgrade head
      2. assert success
    Expected Result: No schema changes needed (String column already supports 'incremental' value)
    Evidence: .sisyphus/evidence/task-6-migration.txt
  ```

  **Commit**: YES
  - Message: `chore(db): verify analysis_type column supports incremental value (no migration needed)`
  - Files: `alembic/versions/xxx_add_incremental_analysis_type.py` (if needed)

---

- [ ] 7. Watchlist UI Three-Button Layout

  **What to do**:
  - 修改 `web/components/watchlist_manager.py` 中的 `render_watchlist_table()` 函数
  - 将原来的单列 "🔄 分析"（`row_cols[7]`，宽度=1）替换为三按钮区域：
    ```
    ┌──────────────────────────────────┐
    │ [全量] [增量] [📊差异]            │
    └──────────────────────────────────┘
    ```
  - 使用 `st.columns([0.7, 0.7, 0.7])` 替代原来的单列
  - **全量分析按钮**: 🔄 或 "全量"，`key=f"full_stock_{stock_id}"`
    - 调用现有 `POST /api/v1/watchlist/analyze?symbol={symbol}` 端点（`watchlist.py:661-711`）
    - 此端点创建 `WatchlistAnalysis(analysis_type='full', triggered_by='manual')` + 异步执行 + completion callback 设置 `completed_at`
    - 响应 200 返回 `{"triggered": 1, "results": [...]}`，前端轮询 `analysis_tasks` 表或等待 SSE 进度
    - **增量分析按钮**: ⚡ 或 "增量"，`key=f"incr_stock_{stock_id}"`
    - **差异查看按钮**: 📊 或 "差异"，`key=f"diff_stock_{stock_id}"`
  - 按钮可用性逻辑：
    ```python
    has_full_today = _has_full_analysis_today(symbol)  # 查 watchlist_analyses: analysis_type='full' + completed_at IS NOT NULL + DATE(created_at)=today
    has_multiple = _has_multiple_analyses_today(symbol)  # 查 DB
    is_analyzing = _is_analysis_running(symbol)  # 查 DB 是否有 RUNNING 状态
    
    full_disabled = is_analyzing  # 全量按钮：仅分析进行中时禁用
    incr_disabled = not has_full_today or is_analyzing  # 增量按钮：需先有全量结果
    diff_disabled = not has_multiple or is_analyzing  # 差异按钮：需有至少两次分析
    ```
  - 禁用时按钮显示为 `st.button("全量", disabled=True)` + tooltip

  **Must NOT do**:
  - 不改变现有列布局结构（只替换 row_cols[7]）
  - 不删除现有其他按钮（查看/管理）

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `frontend-design`: 不需要复杂设计，只改按钮布局

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T8, T9)
  - **Parallel Group**: Wave 3
  - **Blocks**: F2 (UI E2E test)

  **References**:
  - `web/components/watchlist_manager.py:784` — header_cols 定义
  - `web/components/watchlist_manager.py:886-893` — 现有 "🔄 分析" 按钮代码
  - `web/components/watchlist_manager.py:847-930` — 现有表格行渲染循环
  - `webapi/routers/watchlist.py:661-711` — `POST /watchlist/analyze` 全量分析端点（analysis_type='full'）
  - `webapi/routers/watchlist.py:33-72` — `create_analysis_complete_callback()` 完成回调（设置 completed_at）
  - `webapi/routers/watchlist.py:714-754` — `quick_analyze` 端点（仅 market analyst，参考但不用于全量按钮）

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Three buttons visible in watchlist
    Tool: Playwright
    Preconditions: Watchlist has at least 2 stocks
    Steps:
      1. Navigate to http://localhost:8501
      2. Wait for watchlist table to load
      3. Find all buttons with accessible name "全量" (role=button)
      4. Assert at least 2 "全量" buttons found (one per stock)
      5. Find all buttons with accessible name "增量" and "差异"
      6. Assert at least 2 of each found
    Expected Result: All three button types visible per stock
    Evidence: .sisyphus/evidence/task-7-three-buttons.png

  Scenario: Button disabled states
    Tool: Playwright
    Preconditions: Stock "002172" has no full analysis today, no analysis running
    Steps:
      1. Find button with accessible name "全量" for stock "002172" — assert not disabled
      2. Find button with accessible name "增量" for stock "002172" — assert disabled
      3. Find button with accessible name "差异" for stock "002172" — assert disabled
    Expected Result: Full enabled, incremental and diff disabled
    Evidence: .sisyphus/evidence/task-7-button-states.png

  Scenario: All buttons disabled during analysis execution
    Tool: Playwright
    Preconditions: Full analysis just triggered, still running
    Steps:
      1. Click "全量" button, wait for spinner to appear
      2. Assert all three buttons ("全量", "增量", "差异") are disabled while spinner visible
      3. After completion, assert full=enabled, incr=enabled, diff=disabled
    Expected Result: Buttons disabled during any analysis to prevent concurrent clicks
    Evidence: .sisyphus/evidence/task-7-state-transitions.png
  ```

  **Commit**: YES (groups with T8, T9)
  - Message: `feat(ui): replace single analyze button with triple buttons (full/incremental/diff)`
  - Files: `web/components/watchlist_manager.py`

---

- [ ] 8. Diff Report Modal Component

  **What to do**:
  - 在 `web/components/watchlist_manager.py` 中添加 `render_diff_modal()` 函数
  - 调用 `POST /api/v1/analysis/diff-report` 获取 diff 数据
  - 使用 `st.expander("market_analyst 变化")` 等展示每个分析师的变化
  - 显示关键指标对比（价格、signal、confidence）
  - 使用 `st.columns([1, 1])` 显示 "之前" vs "之后" 对比
  - 用颜色标注变化方向（🟢 上升 🔴 下降 ⚪ 不变）

  **Must NOT do**:
  - 不在 diff 展示中调用 LLM

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T7, T9)
  - **Parallel Group**: Wave 3
  - **Blocks**: F2 (UI E2E test)

  **References**:
  - `web/components/watchlist_manager.py:1227-1271` — `render_stock_detail_modal()` 现有模态框（参考模式）
  - `webapi/services/diff_report.py` (T2) — DiffReportGenerator 返回格式

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Diff modal shows analysis comparison
    Tool: Playwright
    Preconditions: Stock has 2+ completed analyses today
    Steps:
      1. Click "📊 差异" button
      2. Modal opens with diff content
      3. Assert each analyst section shows "before"/"after" comparison
    Expected Result: Clear visual diff without LLM involvement
    Evidence: .sisyphus/evidence/task-8-diff-modal.png
  ```

  **Commit**: YES (groups with T7, T9)
  - Message: `feat(ui): add diff report modal for analysis comparison display`
  - Files: `web/components/watchlist_manager.py`

---

- [ ] 9. Manual Analyst Selector (增量分析时可选手动刷新)

  **What to do**:
  - 在增量分析流程中添加"手动选择分析师"功能
  - 当用户点击增量分析时：
    1. 先运行自动检测，展示检测结果（哪些分析师需要刷新）
    2. 提供 st.multiselect 让用户选择要强制刷新的分析师
    3. 用户确认后开始增量分析
  - 实现 `trigger_incremental_analysis(stock_id)` 函数：
    1. 先调用 `POST /api/v1/watchlist/{id}/incremental-analyze/precheck` 获取检测结果
    2. 用 `st.expander` 展示检测结果 + 分析师选择
    3. 用户选择后调用 `POST /api/v1/watchlist/{id}/incremental-analyze`（**不设置 timeout**，因为是同步 1-3 分钟）
  - 添加 precheck 端点：`POST /api/v1/watchlist/{id}/incremental-analyze/precheck`
    - 返回 `{"needs_refresh": ["market", "news"], "cached": ["sentiment", "fundamentals"], "all_cached": False}`
  - **重要**：现有 UI 请求模式（`watchlist_manager.py:507-515`）使用 `timeout=5`，增量端点同步执行 1-3 分钟，必须移除或增大 timeout。

  **Must NOT do**:
  - 不修改上游核心代码

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T7, T8)
  - **Parallel Group**: Wave 3
  - **Blocks**: F2 (UI E2E test)

  **References**:
  - `web/components/watchlist_manager.py:886-893` — 现有按钮回调模式
  - `webapi/services/change_detection.py` (T1) — 变化检测结果格式
  - `webapi/routers/watchlist.py` — API 端点添加位置

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Precheck shows change detection results
    Tool: Bash (curl)
    Steps:
      1. POST /api/v1/watchlist/1/incremental-analyze/precheck
      2. response["needs_refresh"] is a list of analyst names
      3. response["cached"] is a list of analyst names
      4. response["all_cached"] is False
    Expected Result: User can see which analysts need refresh before confirming
    Evidence: .sisyphus/evidence/task-9-precheck.txt

  Scenario: Precheck with no changes detected (all cached)
    Tool: Bash (curl)
    Preconditions: All analyst caches valid, no price change, no new news
    Steps:
      1. POST /api/v1/watchlist/1/incremental-analyze/precheck
      2. assert response["needs_refresh"] == []
      3. assert response["all_cached"] == True
    Expected Result: UI shows "no changes detected" with option to force refresh
    Evidence: .sisyphus/evidence/task-9-precheck-no-changes.txt

  Scenario: Manual mode — user deselects all analysts
    Tool: Playwright
    Preconditions: Precheck shows 2 analysts need refresh
    Steps:
      1. Open incremental dialog with precheck results
      2. Uncheck all analysts in multiselect
      3. Submit button should be disabled or show validation error
    Expected Result: Cannot start analysis with zero analysts selected
    Evidence: .sisyphus/evidence/task-9-empty-selection.png
  ```

  **Commit**: YES (groups with T7, T8)
  - Message: `feat(watchlist): add precheck endpoint and manual analyst selector for incremental analysis`
  - Files: `webapi/routers/watchlist.py`, `web/components/watchlist_manager.py`

---

## Final Verification Wave

> 3 review agents run in PARALLEL. ALL must APPROVE.

- [ ] F1. **End-to-End API Test** — `unspecified-high`
  Tool: Bash (curl) + Python (unit test assertions)
  Submit full analysis, then incremental analysis, then diff report. Verify:
  - Full analysis completes and creates `analysis_type='full'` record
  - Incremental analysis only refreshes changed analysts, completes in <3 min
  - Diff report shows correct before/after comparison
  - Precheck endpoint returns correct refresh/cached lists
  - Concurrent incremental request returns 409
  Output: `Tests [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **End-to-End UI Test** — `unspecified-high` + `playwright` skill
  Tool: Playwright (screenshot + DOM assertion)
  Start from clean state. Verify:
  - Watchlist shows three buttons per stock
  - Button disabled states correct before/after full analysis
  - Incremental analysis flow with precheck modal
  - Diff modal shows comparison with visual indicators
  Output: `Scenarios [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F3. **Scope Fidelity Check** — `deep`
  Tool: Bash (git diff, grep)
  For each task: verify 1:1 compliance with spec. Check:
  - No modifications to `tradingagents/` core code
  - All new files in `webapi/` or `web/` directories
  - Upstream isolation maintained
  - Output: `Tasks [N/N compliant] | VERDICT`

---

## Commit Strategy

- **1**: `feat(watchlist): add data change detection module for incremental analysis` — T1, T2, T3
- **2**: `feat(api): add incremental-analyze and diff-report endpoints` — T4, T5, T6
- **3**: `feat(ui): replace single analyze button with triple buttons + diff modal + manual selector` — T7, T8, T9
- **4**: `test: add unit tests for change detection, diff report, incremental service` — test files

---

## Success Criteria

### Verification Commands
```bash
pytest tests/test_change_detection.py -v        # Change detection unit tests
pytest tests/test_diff_report.py -v              # Diff report unit tests
pytest tests/test_incremental_service.py -v         # Incremental service unit tests
pytest tests/e2e -m api                            # API endpoint tests
```

### Final Checklist
- [ ] All Must Have items implemented
- [ ] All Must NOT Have items absent
- [ ] No modifications to `tradingagents/` core
- [ ] All tests pass
- [ ] Incremental analysis completes in <3 minutes on average
- [ ] Diff report generates in <1 second (no LLM)
