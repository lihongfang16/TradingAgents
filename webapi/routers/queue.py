"""
Queue monitoring API endpoints.

Provides endpoints for monitoring the analysis task queue,
including statistics, retry functionality, and health checks.
"""
from typing import Dict, Any

from fastapi import APIRouter
from pydantic import BaseModel

from webapi.services.queue_service import AnalysisQueueService

router = APIRouter(prefix="/api/v1/queue", tags=["queue"])


class QueueStatsResponse(BaseModel):
    """Queue statistics response model."""
    queued: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    oldest_queued_seconds: int = 0


class RetryFailedResponse(BaseModel):
    """Retry failed tasks response model."""
    requeued: int


class QueueHealthResponse(BaseModel):
    """Queue health check response."""
    status: str
    queued: int
    processing: int


@router.get("/stats", response_model=QueueStatsResponse)
async def get_queue_stats() -> Dict[str, Any]:
    """
    Get current queue statistics.
    
    Returns counts of tasks by status:
    - queued: Tasks waiting to be processed
    - processing: Tasks currently being analyzed
    - completed: Successfully completed tasks
    - failed: Tasks that failed (may be retryable)
    """
    service = AnalysisQueueService()
    stats = service.get_queue_stats()
    
    return {
        "queued": stats.get("QUEUED", 0),
        "processing": stats.get("PROCESSING", 0),
        "completed": stats.get("COMPLETED", 0),
        "failed": stats.get("FAILED", 0),
        "oldest_queued_seconds": stats.get("oldest_queued_seconds", 0),
    }


@router.post("/retry-failed", response_model=RetryFailedResponse)
async def retry_failed_tasks() -> Dict[str, int]:
    """
    Retry all failed tasks that haven't exceeded max retries.
    
    Also resets stale PROCESSING tasks (tasks stuck for >30 minutes).
    
    Returns the number of tasks requeued.
    """
    service = AnalysisQueueService()
    count = service.requeue_failed(max_retries=3, stale_timeout_minutes=30)
    
    return {"requeued": count}


@router.get("/health", response_model=QueueHealthResponse)
async def get_queue_health() -> Dict[str, Any]:
    """
    Get queue health status.
    
    Returns:
    - status: "healthy" if queue is processing normally
    - queued: Number of tasks in queue
    - processing: Number of tasks being processed
    """
    service = AnalysisQueueService()
    stats = service.get_queue_stats()
    
    queued = stats.get("QUEUED", 0)
    processing = stats.get("PROCESSING", 0)
    failed = stats.get("FAILED", 0)
    
    # Determine health status
    # - If many failed tasks, warn
    # - If queue is backed up (>100 tasks), warn
    status = "healthy"
    if failed > 10:
        status = "degraded"
    if queued > 100:
        status = "backed_up"
    
    return {
        "status": status,
        "queued": queued,
        "processing": processing,
    }


@router.post("/purge", response_model=Dict[str, int])
async def purge_old_tasks(older_than_days: int = 7) -> Dict[str, int]:
    """
    Purge old completed/failed tasks from the queue.
    
    Args:
        older_than_days: Delete tasks older than this many days (default: 7)
        
    Returns:
        deleted: Number of tasks deleted
    """
    service = AnalysisQueueService()
    count = service.purge_completed(older_than_days=older_than_days)
    
    return {"deleted": count}
