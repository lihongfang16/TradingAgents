# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-28
**Commit:** 16720d4
**Branch:** feature/a-share-support

## OVERVIEW

Multi-agent LLM trading framework forked from TauricResearch/TradingAgents, adapted for Chinese A-share markets. Deploys 11 specialized agents (4 analysts, 2 researchers, 1 trader, 3 risk debaters, 2 managers) orchestrated via LangGraph, with a 4-source failover data layer for A-share market data.

**Stack:** Python 3.10+ | LangGraph | FastAPI + SQLAlchemy 2.0 | PostgreSQL | Streamlit | Alembic

## STRUCTURE

```
.
├── tradingagents/       # Core library: agents, graph, data sources, LLM clients
├── cli/                 # Typer+Rich CLI (tradingagents command)
├── web/                 # Streamlit UI (no __init__.py, standalone app)
├── webapi/              # FastAPI REST API + PostgreSQL persistence
├── alembic/             # DB migrations (analysis_tasks, watchlist, etc.)
├── scripts/             # DB init, JSON→Postgres migration, WSL/Linux setup
├── tests/e2e/           # E2E tests (pytest markers: api, ui)
├── nginx/               # Reverse proxy config (/ → web, /api/ → api)
└── main.py              # Direct Python usage example
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add a new agent type | `tradingagents/agents/<role>/` | Register in `agents/__init__.py`, add node in `graph/setup.py` |
| Change graph flow | `tradingagents/graph/setup.py` | LangGraph StateGraph edges and nodes |
| Add A-share data provider | `tradingagents/dataflows/` | Register in `china_data_manager.py` failover chain |
| Add LLM provider | `tradingagents/llm_clients/` | Extend `factory.py`, add client class |
| API endpoint | `webapi/routers/` | Analysis `/api/v1/analysis/`, Watchlist `/api/v1/watchlist/` |
| DB schema change | `webapi/models/database.py` + `alembic/` | Run `alembic revision --autogenerate` |
| Streamlit component | `web/components/` | No `__init__.py` in web/ — standalone Streamlit app |
| CLI interaction | `cli/main.py` | Typer app, 1537 lines, MessageBuffer state management |
| Config defaults | `tradingagents/default_config.py` | LLM provider, debate rounds, data vendors |
| Tool definitions | `tradingagents/agents/utils/` | @tool decorators: core_stock, fundamentals, news, indicators |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `TradingAgentsGraph` | Class | `tradingagents/graph/trading_graph.py` | Main orchestrator — init LLMs, build graph, propagate, reflect |
| `GraphSetup` | Class | `tradingagents/graph/setup.py` | Builds LangGraph StateGraph with all nodes/edges |
| `AgentState` | Class | `tradingagents/agents/utils/agent_states.py` | LangGraph state — holds all reports, debate states, decisions |
| `ChinaDataManager` | Class | `tradingagents/dataflows/china_data_manager.py` | A-share multi-source failover (Mairui→Ashare→AkShare→BaoStock) |
| `AnalysisService` | Class | `webapi/services/analysis_service.py` | Task CRUD, async execution, progress tracking |
| `AnalysisRunner` | Class | `tradingagents/core/analysis_runner.py` | Wraps TradingAgentsGraph for API/CLI consumption |
| `create_llm_client()` | Fn | `tradingagents/llm_clients/factory.py` | Factory for OpenAI/Anthropic/Google/xAI/Ollama/OpenRouter |
| `route_to_vendor()` | Fn | `tradingagents/dataflows/interface.py` | Auto-routes A-share symbols to ChinaDataManager |
| `FinancialSituationMemory` | Class | `tradingagents/agents/utils/memory.py` | BM25-based offline memory for trade reflection |

## CONVENTIONS

- **Naming**: Classes PascalCase, functions snake_case, constants UPPER_SNAKE, tables plural_lowercase
- **Imports**: stdlib → third-party → local (see `.openspec/conventions.md`)
- **Type annotations**: Required on all public function params and returns
- **Docstrings**: Required on public modules, classes, methods (Args/Returns/Raises format)
- **DB index naming**: `ix_<table>_<column>`
- **DB timestamps**: `created_at`, `updated_at`, `completed_at`
- **Git commits**: `<type>(<scope>): <subject>` — feat/fix/docs/style/refactor/test/chore
- **API responses**: DELETE returns 204 No Content

## UPSTREAM ISOLATION PRINCIPLE

- **NEVER** modify analysis engine core code when adding persistence layers
- **NEVER** delete JSON backup files — keep alongside PostgreSQL
- **NEVER** introduce Redis/MongoDB — PostgreSQL only for persistence
- **NEVER** create a new LangGraph Graph for fast mode — use `AnalysisRunner(fast_mode=True)`
- Fast Mode uses `AnalysisRunner` parameter, NOT a separate 3-agent Graph
- Architecture changes require ADR in `.openspec/decisions/`
- Major features require RFC in `.openspec/rfcs/`
- LLM client `validate_model()` is never called — known issue (see `llm_clients/TODO.md`)
- `base_url` accepted but ignored in `AnthropicClient` and `GoogleClient` — known issue
- Progress display bugs: `analysis_runner.py` only reports 60% once, then silent until done

## UNIQUE STYLES

- **Bilingual agents**: Chinese system prompts for A-share symbols, English for US/global
- **A-share price limits**: Market analyst auto-detects 创业板/科创板 ±20% vs 主板 ±10%
- **Symbol normalization**: Handles 000001, SZ000001, 600000.SH, etc. interchangeably
- **Data failover chain**: Mairui (licensed) → Ashare (Sina+Tencent) → AkShare → BaoStock
- **Dual-LLM strategy**: `deep_think_llm` for Research/Portfolio Manager, `quick_think_llm` for all others
- **5-tier rating**: BUY / OVERWEIGHT / HOLD / UNDERWEIGHT / SELL
- **SSE progress streaming**: `/api/v1/analysis/{task_id}/progress` for real-time agent-level updates
- **Lazy imports**: `analysis_service` loaded on first API request to reduce startup time

## COMMANDS

```bash
# Development
pip install -e ".[web]"          # Install with web dependencies
python -m cli.main               # CLI directly
python main.py                   # Direct Python usage

# Services
start_all.py                     # API + Web concurrently
start_api.py                     # FastAPI on :8000
start_web.py                     # Streamlit on :8501

# Database
alembic revision --autogenerate -m "desc"
alembic upgrade head
python scripts/init_database.py

# Testing
pytest tests/e2e -m api          # API tests
pytest tests/e2e -m ui           # UI tests (Playwright)

# Docker
docker-compose up                # api:8000 + web:8501 + nginx:80
```

## NOTES

- **Windows dev**: PostgreSQL runs in WSL2, configured via `DATABASE_URL` env var
- **No `__init__.py`** in `web/` — it's a standalone Streamlit app, not a Python package
- **`web/data/history.json`**: Local cache/fallback, NOT source of truth (PostgreSQL is)
- **`eval_results/`**: Strategy backtest logs, not part of application
- **`tradingagents/__init__.py`** sets `PYTHONUTF8=1` on import
- **APScheduler** runs cron jobs: full analysis 02:00, quick during market hours, batch every 2min
- **`.openspec/`** contains full ADR/RFC governance — check before architectural changes
- **Docker pip mirror**: Uses Tsinghua `pypi.tuna.tsinghua.edu.cn/simple`
