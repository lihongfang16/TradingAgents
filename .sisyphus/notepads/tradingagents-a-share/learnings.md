# TradingAgents A-Share Learnings

## 2026-03-23: market_analyst.py A-Share Adaptation

### Architecture Insight
- `market_analyst.py` is a **prompt-based LLM agent node**, not a direct data processor
- A-share data routing already handled at tool level via `route_to_vendor()` → `china_manager.get_kline()`
- The right place to add A-share specifics is in the **system prompt context**, not in data processing

### Implementation Approach
- Added `_get_price_limit(symbol)` helper for ±10%/±20% detection
- Added `_get_a_share_context(symbol)` to build A-share specific prompt context
- Context includes: 涨跌停限制, T+1 rules, trading hours, real-time quote alerts
- Real-time quote fetched via `china_manager.get_realtime_quote()` for 涨跌停 detection
- No changes needed to tool infrastructure — routing already works

### Key Findings
- `china_manager` singleton is in `interface.py` — import directly
- `is_a_share()` also in `interface.py` — handles SZ/SH/BJ prefixes
- 创业板 (301xxx, 303xxx) and 科创板 (688xxx) have ±20% limits
- Quote dict keys vary by provider: `change_percent`, `pct_chg`, `涨跌幅`

## 2026-03-24: WebAPI Analysis Service Implementation

### AnalysisRunner vs run_analysis
- The core module `tradingagents/core/analysis_runner.py` has `AnalysisRunner` **class**, not a `run_analysis` function
- Task requirement to use `run_analysis` was slightly misleading — correct approach is to instantiate `AnalysisRunner` and call `.run()`
- `AnalysisRunner.run()` returns dict with: status, progress_pct, agents_progress, current_agent, final_state, signal, error, timestamp

### AnalysisService Architecture
- Created `webapi/services/analysis_service.py` with `AnalysisService` class
- In-memory task storage: `_tasks: Dict[str, AnalysisResponse]`
- Async execution via `asyncio.run_in_executor(None, self._run_sync_analysis, ...)` using ThreadPoolExecutor
- Progress callback support via `_progress_callbacks: Dict[str, Callable]`
- Methods: create_task, get_task, list_tasks, run_analysis, run_batch, cancel_task, get_batch, shutdown

### Key Design Decisions
- Used ThreadPoolExecutor with configurable max_workers (default 4)
- `run_analysis` is async but calls sync `AnalysisRunner.run()` in executor
- Batch processing uses `asyncio.gather()` for concurrent execution
- Task status lifecycle: PENDING → RUNNING → COMPLETED/FAILED/CANCELLED

### QA Verification Results
- All imports successful
- Service instantiation works
- create_task creates valid AnalysisResponse with UUID task_id
- get_task retrieves by ID correctly
- list_tasks filters by status correctly

## 2026-03-27: Watchlist Router Implementation

### Watchlist ORM Models
- `Watchlist` and `WatchlistAnalysis` models in `webapi/models/database.py` use **string columns for boolean flags** ('Y'/'N')
- `Watchlist.to_dict()` / `from_dict()` handle the Y/N ↔ bool conversion
- Same pattern for float fields stored as strings (e.g., `confidence_jump_threshold`, `last_confidence`)

### Helper Conversion Functions
- `_watchlist_to_response(w: Watchlist)`: converts ORM → Pydantic `WatchlistResponse`
- `_analysis_to_response(a: WatchlistAnalysis)`: converts ORM → Pydantic `WatchlistAnalysisResponse`
- Both handle the string ↔ typed conversions for flags and floats

### SQLAlchemy Column Type Warnings
- Type checkers (basedpyright) flag `Column[T]` vs `T` mismatches — these are **expected and harmless**
- SQLAlchemy ORM attributes are typed as `Column[X]` but behave as `X` at runtime
- Same pattern used throughout `analysis_service.py` — no special handling needed

### Turning Point Detection Algorithm
- `detect_turning_point()` function: signal change, confidence jump, risk level change, emergency alerts
- Returns `TurningDetectionResponse` with `is_turning`, `reason`, `importance_score`
- Importance thresholds: signal flip = 0.9, confidence jump = 0.6, risk change = 0.3-0.4, market alert = 0.95

### Endpoints Implemented (13 total)
- CRUD: POST/GET/PUT/DELETE on `/api/v1/watchlist/`
- Analysis: POST `/analyze`, POST `/{id}/quick-analyze`
- History/Alerts: GET `/analysis`, GET `/alerts`
- Detection: POST `/detect-turning`
- Scheduler: GET `/scheduler/status`, POST `/scheduler/trigger/{job_id}`

### FastAPI Patterns Used
- `Depends(get_db)` for SQLAlchemy session injection
- `status_code=201` for POST create, `204` for DELETE
- `HTTPException(status_code=404/409)` for not found/conflict
- `Query()` for optional filter parameters

