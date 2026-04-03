# pyright: reportUnusedCallResult=false, reportDeprecated=false

"""
TradingAgents API Server
"""
import os
import platform

# Windows-specific asyncio fix: must be set BEFORE any asyncio imports
# This prevents [Errno 22] Invalid argument errors with ThreadPoolExecutor/to_thread
if platform.system() == "Windows":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from webapi.routers import analysis, watchlist, cache, queue
from webapi.services.scheduler_service import scheduler_service

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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="TradingAgents API",
        description="Web API for TradingAgents - Stock analysis and monitoring",
        version="1.0.0",
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


@app.on_event("startup")
async def on_startup() -> None:
    """Restore scheduler monitoring state on API startup."""
    scheduler_service.restore_state()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Stop scheduler on API shutdown."""
    scheduler_service.stop()


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
    """Health check endpoint"""
    return {"status": "healthy"}


def main():
    """Main entry point for running the server"""
    import uvicorn
    uvicorn.run("webapi.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
