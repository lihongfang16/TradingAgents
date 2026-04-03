# webapi/ — FastAPI REST API

## OVERVIEW

FastAPI backend serving analysis task management, real-time SSE progress streaming, watchlist CRUD, scheduled analysis, and PostgreSQL persistence via SQLAlchemy 2.0 + Alembic migrations.

## STRUCTURE

```
webapi/
├── server.py               # FastAPI app factory, CORS, uvicorn entry (port 8000)
├── routers/
│   ├── analysis.py         # POST/GET/DELETE /api/v1/analysis/, SSE /{id}/progress
│   └── watchlist.py        # CRUD /api/v1/watchlist/, quick-analyze, turning detection
├── services/
│   ├── analysis_service.py # Task CRUD, ThreadPoolExecutor async execution, progress tracking
│   ├── scheduler_service.py# APScheduler: full@02:00, quick@market-hours, batch@2min
│   ├── notification_service.py  # Cross-platform desktop notifications (Win/Mac/Linux)
│   └── history_persistence.py   # Local JSON fallback (web/data/history.json)
├── models/
│   ├── analysis.py         # Pydantic: AnalysisRequest/Response, BatchRequest, AnalysisStatus
│   └── database.py         # SQLAlchemy ORM: AnalysisTask, AnalysisBatch, Watchlist, WatchlistAnalysis
└── config/
    └── database.py         # Engine/session setup, get_db() dependency
```

## API ROUTES

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/analysis/` | Submit analysis task (returns task_id, runs async) |
| GET | `/api/v1/analysis/{id}` | Get task status/result |
| GET | `/api/v1/analysis/{id}/progress` | **SSE** real-time agent-level progress |
| DELETE | `/api/v1/analysis/{id}` | Delete task (204 No Content) |
| POST | `/api/v1/analysis/batch` | Batch analysis for multiple symbols |
| GET/POST | `/api/v1/watchlist/` | CRUD watchlist stocks |
| POST | `/api/v1/watchlist/{id}/quick-analyze` | Market-only quick analysis |
| POST | `/api/v1/watchlist/detect-turning` | Compare two results for turning points |
| GET | `/health` | Health check |

## KEY PATTERNS

- **Lazy imports**: `analysis_service` loaded on first request to reduce cold-start time
- **Async execution**: `ThreadPoolExecutor` wraps sync `AnalysisRunner` — analysis runs in background thread
- **Progress tracking**: Agent progress written to DB JSONB columns (`agents_progress`, `current_agent`, `progress_pct`, `logs`)
- **SSE streaming**: Routers yield `Server-Sent Events` from DB progress columns
- **Dual persistence**: PostgreSQL (source of truth) + local JSON (cache/fallback)
- **MiniMax mapping**: Mapped to OpenAI-compatible API with custom `base_url`

## DB SCHEMA

Tables: `analysis_tasks`, `analysis_batches`, `watchlist`, `watchlist_analyses`
- JSONB columns for flexible result storage
- Index naming: `ix_<table>_<column>`
- Timestamps: `created_at`, `updated_at`, `completed_at`

## NOTES

- `scheduler_service.py` runs cron jobs via APScheduler — not Celery despite redis in requirements
- `history_persistence.py` writes to `web/data/history.json` — fallback only, PostgreSQL is truth
- Analysis progress bug: runner only reports 60% once, then silent — see `.sisyphus/plans/`
- DELETE endpoint returns 204 No Content per convention
