"""
Analysis Router for TradingAgents API
"""
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
import asyncio
import json

from webapi.models.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    BatchAnalysisRequest,
    BatchAnalysisResponse,
    AnalysisStatus,
    DiffReportRequest,
    DiffReportResponse,
)
# Lazy import to avoid slow startup
def get_analysis_service():
    from webapi.services.analysis_service import analysis_service
    return analysis_service


def _get_db():
    """Return the get_db generator for FastAPI Depends."""
    from webapi.config.database import get_db as _get_db_gen
    return _get_db_gen

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/", response_model=AnalysisResponse)
async def create_analysis(request: AnalysisRequest):
    """Create a new analysis task and enqueue it for worker processing."""
    return await get_analysis_service().run_analysis(str(uuid.uuid4()), request)


@router.get("/{task_id}", response_model=AnalysisResponse)
async def get_analysis(task_id: str):
    """Get analysis status by task ID"""
    result = get_analysis_service().get_task(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.delete("/{task_id}", status_code=204)
async def delete_analysis(task_id: str):
    """Delete an analysis task by ID"""
    deleted = await asyncio.to_thread(get_analysis_service().delete_task, task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return None


@router.get("/", response_model=List[AnalysisResponse])
async def list_analyses(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of results"),
):
    """List all analyses with optional symbol filter"""
    return get_analysis_service().list_tasks(symbol=symbol, limit=limit)


@router.post("/batch", response_model=BatchAnalysisResponse)
async def batch_analysis(request: BatchAnalysisRequest):
    """Create and run batch analysis for multiple symbols"""
    # Use run_batch which creates tasks AND starts execution
    return await get_analysis_service().run_batch(request)


@router.post("/diff-report", response_model=DiffReportResponse)
async def diff_report(request: DiffReportRequest, db: Session = Depends(_get_db)):
    """Generate a diff report comparing two analysis tasks.
    
    Validates that both tasks exist and are COMPLETED before generating the diff.
    """
    # Import here to avoid circular imports
    from webapi.services.diff_report import DiffReportGenerator
    from webapi.models.database import AnalysisTask
    
    # Validate task 1 exists
    task1 = db.query(AnalysisTask).filter(AnalysisTask.task_id == request.task_id_1).first()
    if task1 is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {request.task_id_1}")
    
    # Validate task 2 exists
    task2 = db.query(AnalysisTask).filter(AnalysisTask.task_id == request.task_id_2).first()
    if task2 is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {request.task_id_2}")
    
    # Validate both tasks are COMPLETED
    if str(task1.status) != AnalysisStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Task {request.task_id_1} is not completed (status: {task1.status})"
        )
    
    if str(task2.status) != AnalysisStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Task {request.task_id_2} is not completed (status: {task2.status})"
        )
    
    # Generate diff report
    try:
        generator = DiffReportGenerator()
        report = generator.generate(request.task_id_1, request.task_id_2, db)
        return report
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error generating diff report: {str(e)}")


@router.get("/{task_id}/progress")
async def get_progress(task_id: str):
    """SSE stream for real-time progress updates with agent-level tracking"""
    async def event_generator() -> AsyncGenerator[Dict[str, Any], None]:
        task = get_analysis_service().get_task(task_id)
        if not task:
            yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
            return

        # Stream real-time progress using tracked fields
        while task and task.status in {AnalysisStatus.PENDING, AnalysisStatus.RUNNING}:
            progress_data = {
                "task_id": task_id,
                "status": task.status.value,
                "symbol": task.symbol,
                "agents_progress": task.agents_progress or {},
                "current_agent": task.current_agent or "",
                "progress_pct": task.progress_pct or 0,
                "message": task.message or "",
                "logs": task.logs or [],
                "done": False,
            }
            yield {
                "event": "progress",
                "data": json.dumps(progress_data),
            }
            await asyncio.sleep(2)
            task = get_analysis_service().get_task(task_id)

        # Final status - include full result
        final_task = get_analysis_service().get_task(task_id)
        if final_task is None:
            # Task was deleted mid-stream
            yield {
                "event": "error",
                "data": json.dumps({"error": "Task not found", "done": True}),
            }
            return
        
        final_data = {
            "task_id": task_id,
            "status": final_task.status.value,
            "symbol": final_task.symbol,
            "agents_progress": final_task.agents_progress or {},
            "current_agent": final_task.current_agent or "",
            "progress_pct": 100,
            "message": final_task.message or "",
            "logs": final_task.logs or [],
            "result": final_task.result,
            "done": True,
        }
        yield {
            "event": "complete",
            "data": json.dumps(final_data),
        }

    return EventSourceResponse(event_generator())
