"""
Analysis Router for TradingAgents API
"""
from typing import List, Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse
import asyncio
import json

from webapi.models.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    BatchAnalysisRequest,
    BatchAnalysisResponse,
    AnalysisStatus,
)
from webapi.services.analysis_service import analysis_service

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/", response_model=AnalysisResponse)
async def create_analysis(request: AnalysisRequest):
    """Create a new analysis task and start execution in background"""
    task = analysis_service.create_task(request)
    
    # Start analysis in background immediately
    asyncio.create_task(
        analysis_service.run_analysis(task.task_id, request)
    )
    
    return task


@router.get("/{task_id}", response_model=AnalysisResponse)
async def get_analysis(task_id: str):
    """Get analysis status by task ID"""
    result = analysis_service.get_task(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.delete("/{task_id}", status_code=204)
async def delete_analysis(task_id: str):
    """Delete an analysis task by ID"""
    deleted = analysis_service.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return None


@router.get("/", response_model=List[AnalysisResponse])
async def list_analyses(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of results"),
):
    """List all analyses with optional symbol filter"""
    return analysis_service.list_tasks(symbol=symbol, limit=limit)


@router.post("/batch", response_model=BatchAnalysisResponse)
async def batch_analysis(request: BatchAnalysisRequest):
    """Create batch analysis for multiple symbols"""
    return analysis_service.create_batch_task(request)


@router.get("/{task_id}/progress")
async def get_progress(task_id: str):
    """SSE stream for real-time progress updates"""
    async def event_generator() -> AsyncGenerator[dict, None]:
        task = analysis_service.get_task(task_id)
        if not task:
            yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
            return
        
        # Calculate progress based on status and elapsed time
        while task and task.status in (AnalysisStatus.PENDING, AnalysisStatus.RUNNING):
            progress_data = analysis_service.get_task_progress(task_id)
            yield {
                "event": "progress",
                "data": json.dumps(progress_data or {}),
            }
            await asyncio.sleep(2)
            task = analysis_service.get_task(task_id)
        
        # Final status
        final_data = analysis_service.get_task_progress(task_id)
        yield {
            "event": "complete",
            "data": json.dumps(final_data or {}),
        }
    
    return EventSourceResponse(event_generator())
