# pyright: reportUnusedCallResult=false, reportDeprecated=false

"""
TradingAgents API Server
"""
import os
import platform
import threading
import logging
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# Windows-specific asyncio fix: must be set BEFORE any asyncio imports
# This prevents [Errno 22] Invalid argument errors with ThreadPoolExecutor/to_thread
if platform.system() == "Windows":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from webapi.routers import analysis, watchlist, cache, queue
from webapi.services.scheduler_service import (
    scheduler_service,
    reconcile_unfinalized_watchlist_analyses,
    reconcile_expired_hf_flags,
)
from webapi.services.queue_service import AnalysisQueueService

# Load environment variables from .env file
# Find project root (where .env file is located)
_current_dir = os.path.dirname(os.path.abspath(__file__))
# Go up 2 levels: webapi -> project_root
_project_root = os.path.abspath(os.path.join(_current_dir, '..'))
env_path = os.path.join(_project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # Fallback: try loading from current working directory
    load_dotenv()


async def startup_reconciliation():
    """Run all reconciliation tasks on startup.

    Called after scheduler restore but before worker starts.
    Non-blocking - logs results but doesn't wait.
    """
    import asyncio
    from webapi.config.database import SessionLocal

    logger.info("[STARTUP] Running reconciliation...")

    # Run in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()

    def _reconcile():
        db = SessionLocal()
        try:
            # Queue layer reconciliation
            queue_service = AnalysisQueueService()
            stale_queue = queue_service.reconcile_stale_queue_rows(db, 30)
            orphaned_tasks = queue_service.reconcile_orphaned_task_states(db, 30)
            pending_orphans = queue_service.reconcile_pending_orphans(db, 30)

            # Watchlist layer reconciliation
            unfinalized = reconcile_unfinalized_watchlist_analyses(db)
            expired_hf = reconcile_expired_hf_flags(db)

            return {
                "stale_queue_rows": stale_queue,
                "orphaned_tasks": orphaned_tasks,
                "pending_orphans": pending_orphans,
                "unfinalized_analyses": len(unfinalized),
                "expired_hf_flags": expired_hf
            }
        except Exception as e:
            logger.exception("[STARTUP] Reconciliation failed: %s", str(e))
            return {"error": str(e)}
        finally:
            db.close()

    try:
        # Run with timeout to prevent blocking startup
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _reconcile),
            timeout=60.0
        )
        logger.info("[STARTUP] Reconciliation complete: %s", result)
    except asyncio.TimeoutError:
        logger.warning("[STARTUP] Reconciliation timed out after 60s")
    except Exception as e:
        logger.exception("[STARTUP] Reconciliation error: %s", str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown for scheduler and embedded worker."""
    embedded_worker = os.getenv("EMBEDDED_WORKER", "true").lower() == "true"
    worker_thread: Optional[threading.Thread] = None

    # --- Startup ---
    scheduler_service.restore_state()
    await startup_reconciliation()  # Run reconciliation before worker starts

    if embedded_worker:
        from webapi.worker import AnalysisWorker
        poll_interval = float(os.getenv("WORKER_POLL_INTERVAL", "1.0"))
        worker = AnalysisWorker(
            worker_id="embedded-worker",
            poll_interval=poll_interval,
        )
        app.state.worker = worker

        worker_thread = threading.Thread(
            target=worker.start,
            name="analysis-worker",
            daemon=True,
        )
        worker_thread.start()
        logger.info("Embedded analysis worker started in background thread")

    yield  # --- App running ---

    # --- Shutdown ---
    if worker_thread and worker_thread.is_alive():
        app.state.worker.stop()
        worker_thread.join(timeout=5.0)
        if worker_thread.is_alive():
            logger.warning("Worker thread did not stop gracefully within 5s")

    scheduler_service.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="TradingAgents API",
        description="Web API for TradingAgents - Stock analysis and monitoring",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(analysis.router)
    app.include_router(watchlist.router)
    app.include_router(cache.router, prefix="/api/v1")
    app.include_router(queue.router)
    
    return app


# Create app instance
app = create_app()


@app.get("/")
async def root():
    """Root endpoint - returns API info"""
    return {
        "name": "TradingAgents API",
        "version": "1.0.0",
        "description": "Web API for stock analysis and monitoring",
    }


@app.get("/health")
async def health():
    """Health check endpoint with worker status"""
    status = {"status": "healthy"}
    worker = getattr(app.state, "worker", None)
    if worker:
        status["worker"] = {
            "alive": worker.running,
            "tasks_processed": worker.tasks_processed,
            "current_task": worker.current_task,
        }
    return status


def main():
    """Main entry point for running the server"""
    import uvicorn
    uvicorn.run("webapi.server:app", host="0.0.0.0", port=8002, reload=True)


if __name__ == "__main__":
    main()
