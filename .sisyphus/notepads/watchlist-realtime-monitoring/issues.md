# Watchlist Realtime Monitoring - Issues

## 2026-03-30

- `POST /api/v1/watchlist/monitoring/start` can hang in local verification because scheduler jobs execute immediately and `scheduler_service.py` imports `SessionLocal` from `webapi.models.database` (not exported there). This is outside this router-only task scope (scheduler service task).
- `lsp_diagnostics` shows many pre-existing basedpyright errors in `webapi/routers/watchlist.py` caused by SQLAlchemy typing mismatch patterns and not introduced by this endpoint change.
- `@app.on_event(...)` emits FastAPI deprecation warnings in runtime/lint output (lifespan API preferred), but retained intentionally for compatibility with current task requirement.
- Startup verification may not always show a restore log line when persisted monitoring state is inactive because `restore_state()` currently logs only when active state is restored.
