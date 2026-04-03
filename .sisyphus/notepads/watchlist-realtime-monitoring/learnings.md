# Watchlist Realtime Monitoring - Learnings

## 2026-03-27: Scheduler Service Implementation

### APScheduler Integration
- Created `webapi/services/scheduler_service.py` with `SchedulerService` class
- Uses `BackgroundScheduler` with `Asia/Shanghai` timezone for trading hours
- Four scheduled jobs configured:
  - `watchlist_full_analysis`: Daily at 02:00 (CronTrigger)
  - `watchlist_morning_quick`: 9:20-11:55 weekdays every 5 min (CronTrigger)
  - `watchlist_afternoon_quick`: 13:00-14:55 weekdays every 5 min (CronTrigger)
  - `watchlist_high_freq_batch`: Every 2 minutes (IntervalTrigger, max_instances=1)

### Turning Detection Algorithm
- `detect_turning_point()`: compares current vs previous analysis results
- Signal change: importance += 0.9
- Confidence jump >= 0.15 with confidence > 0.8: importance += 0.6
- Risk level change: importance += 0.3-0.4
- Market alert ("异常"): importance += 0.95
- `is_turning = importance >= 0.5 or len(turning_signals) >= 2`

### High Frequency Mode Logic
- `should_use_high_frequency()`: checks if recent N results are stable
- Stable = same signal AND confidence variation < 10%
- Returns `False` (deactivate) when stable, `True` (continue) otherwise

### Desktop Notification Service
- Created `webapi/services/notification_service.py`
- Platform detection: Windows → win10toast, Mac → osascript, Linux → notify-send
- Falls back to ConsoleNotifier for unknown platforms
- `format_turning_alert()`: creates emoji-rich notifications with signal, confidence, reason

### Import Pattern for Circular Dependencies
- Avoid top-level imports of services that might have circular dependencies
- Use local/conditional imports inside functions where needed
- `from webapi.services.notification_service import ...` in try/except to gracefully handle missing dependencies

### Key Files Created
1. `webapi/services/scheduler_service.py` - APScheduler integration
2. `webapi/services/notification_service.py` - Cross-platform notifications
3. Updated `webapi/services/__init__.py` - Exports for new services

### Dependencies Required
- `APScheduler` - for scheduler service
- `win10toast` - for Windows notifications (optional on Windows)

### Lessons Learned
- Type checkers (basedpyright) flag SQLAlchemy ORM attributes as `Column[X]` vs `X` - expected, harmless
- APScheduler types not stubbed - many "unknown type" warnings, not errors
- `datetime.utcnow()` is deprecated - use timezone-aware objects
- Tuple return type annotations should use `Tuple[str, str]` not bare `tuple`

## 2026-03-30: Monitoring State Persistence

### Scheduler persistence hooks
- Added `restore_state()` to `SchedulerService` to read `monitoring_active` from `WatchlistConfig` and auto-start when persisted state is `"true"`.
- Added `persist: bool = True` parameter to `start()` and `stop()`.
- Added `_persist_monitoring_state(active: bool)` helper to write:
  - `monitoring_active`: `"true"` or `"false"`
  - `monitoring_started_at`: ISO UTC timestamp when active, empty string when inactive

### Import and circular-dependency pattern
- Kept imports local inside persistence methods.
- Use `SessionLocal` from `webapi.config.database` and `WatchlistConfig` from `webapi.models.database` to avoid import errors and keep model access centralized.

### Compatibility note
- Added `WatchlistScheduler` as a backward-compatible alias of `SchedulerService` so direct imports like `from ... import WatchlistScheduler` remain valid.

## 2026-03-30: Watchlist monitoring API endpoints (router)

### Router persistence pattern for monitoring state
- Added `MonitoringStateResponse` and `MonitoringStateUpdate` Pydantic models in `webapi/routers/watchlist.py`.
- Added `_get_monitoring_state()` helper that always calls `WatchlistConfig.init_defaults(db)` before reading keys.
- Stored and read keys through existing model methods only:
  - `monitoring_active` (`"true"` / `"false"`)
  - `monitoring_started_at` (ISO string or empty string)
  - `monitoring_interval` (minutes as string)

### New endpoints added
- `GET /api/v1/watchlist/monitoring/state`
- `POST /api/v1/watchlist/monitoring/state`
- `POST /api/v1/watchlist/monitoring/start`
- `POST /api/v1/watchlist/monitoring/stop`

### Scheduler status endpoint improvement
- Replaced in-memory fake scheduler state usage in `GET /scheduler/status` with live `scheduler_service` state and `get_jobs()`.

## 2026-03-30: FastAPI lifecycle wiring for scheduler restore/stop

### Server startup/shutdown integration
- Updated `webapi/server.py` to import `WatchlistScheduler` at module level and instantiate a global `scheduler = WatchlistScheduler()`.
- Added FastAPI event hooks:
  - `@app.on_event("startup")` → `scheduler.restore_state()`
  - `@app.on_event("shutdown")` → `scheduler.stop()`
- Kept existing app factory flow unchanged (`create_app()` then module-level `app = create_app()`) to avoid router registration regressions.
