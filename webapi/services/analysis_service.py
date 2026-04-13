# TradingAgents WebAPI Services - Analysis Service
"""
Async wrapper service for the core AnalysisRunner, providing task management
and progress tracking for the FastAPI layer.

Storage is backed by PostgreSQL via SQLAlchemy ORM (AnalysisTask model).
"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportDeprecated=false, reportUnannotatedClassAttribute=false

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional

# Initialize logger early for module-level logging
logger = logging.getLogger(__name__)

# Load environment variables from .env file
from dotenv import load_dotenv
# Try multiple locations for .env file
env_loaded = False
for env_path in ['.env', '../.env', '../../.env', 'D:/1.MyProjects/Other/tradingagents-a-share/.env']:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        env_loaded = True
        break
if not env_loaded:
    load_dotenv()  # Fallback to default behavior

# Pre-import these modules to avoid import issues in threads on Windows
from webapi.models.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    BatchAnalysisRequest,
    BatchAnalysisResponse,
)
from webapi.models.database import AnalysisTask, AnalysisBatch
from webapi.config.database import SessionLocal
from webapi.services.queue_service import AnalysisQueueService
from tradingagents.default_config import DEFAULT_CONFIG


def _orm_to_response(task: AnalysisTask) -> AnalysisResponse:
    """Convert an AnalysisTask ORM row to an AnalysisResponse Pydantic model."""
    # Extract decision from result.signal if available
    result_data = task.result if task.result else None

    # For running/pending tasks, include real-time progress data
    if task.status in (AnalysisStatus.PENDING.value, AnalysisStatus.RUNNING.value):
        if not isinstance(result_data, dict):
            result_data = {}
        result_data.update({
            "agents_progress": task.agents_progress or {},
            "current_agent": task.current_agent or "",
            "progress_pct": task.progress_pct or 0,
        })

    # Add elapsed_time and remaining_time for running tasks
    if task.created_at:
        elapsed_seconds = int(
            (
                datetime.now(timezone.utc)
                - task.created_at.replace(tzinfo=timezone.utc)
            ).total_seconds()
        )

        stored_remaining_time = None
        if isinstance(result_data, dict):
            stored_remaining_time = result_data.get("remaining_time")

        if task.status in (AnalysisStatus.COMPLETED.value, AnalysisStatus.FAILED.value, AnalysisStatus.CANCELLED.value):
            remaining_time = 0
        elif stored_remaining_time is None:
            remaining_time = None
        else:
            try:
                remaining_time = max(0, int(stored_remaining_time))
            except (TypeError, ValueError):
                remaining_time = None
    else:
        elapsed_seconds = 0
        remaining_time = None

    # Keep elapsed/remaining time available in result_data for UI paths
    # that read result_data.get("elapsed_time") / result_data.get("remaining_time").
    if not isinstance(result_data, dict):
        result_data = {}
    result_data["elapsed_time"] = elapsed_seconds
    result_data["remaining_time"] = remaining_time
    result_data["is_progress_indeterminate"] = bool(
        task.status in (AnalysisStatus.PENDING.value, AnalysisStatus.RUNNING.value)
        and remaining_time is None
        and (task.progress_pct or 0) < 100
    )

    # Return AnalysisResponse with time fields populated
    return AnalysisResponse(
        task_id=task.task_id,
        status=AnalysisStatus(task.status),
        symbol=task.symbol,
        message=task.message or "",
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        result=result_data,
        error=task.error,
        logs=task.logs if task.logs else [],  # logs from DB
        agents_progress=task.agents_progress,
        current_agent=task.current_agent,
        progress_pct=task.progress_pct,
        elapsed_time=elapsed_seconds,
        remaining_time=remaining_time,
        llm_streams=task.llm_streams,
        decision=task.decision,
        confidence=task.confidence,
    )


def _batch_orm_to_response(batch: AnalysisBatch, tasks: List[AnalysisResponse]) -> BatchAnalysisResponse:
    """Convert an AnalysisBatch ORM row to a BatchAnalysisResponse Pydantic model."""
    return BatchAnalysisResponse(
        batch_id=batch.batch_id,
        total=batch.total,
        completed_count=batch.completed_count,
        failed_count=batch.failed_count,
        status=AnalysisStatus(batch.status),
        created_at=batch.created_at.isoformat() if batch.created_at else None,
        updated_at=batch.updated_at.isoformat() if batch.updated_at else None,
        completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
        tasks=tasks,
    )


class AnalysisService:
    """
    Async wrapper service for running TradingAgents analysis tasks.

    Provides task management, progress tracking, and async execution
    for the FastAPI web layer. Task state is persisted to PostgreSQL.
    """

    _instance = None

    def __new__(cls):
        """Keep a single shared service instance for concurrency limits."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """
        Initialize the AnalysisService.
        """
        if self._initialized:
            return

        self._initialized = True
        self._batch_tasks: Dict[str, BatchAnalysisResponse] = {}
        self._progress_callbacks: Dict[str, Callable] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self.queue_service = AnalysisQueueService()

        logger.info("AnalysisService initialized with PostgreSQL queue backend")

    # ------------------------------------------------------------------
    # CRUD operations backed by PostgreSQL
    # ------------------------------------------------------------------

    def create_task(
        self,
        request: AnalysisRequest,
        task_id: Optional[str] = None,
    ) -> AnalysisResponse:
        """
        Create a new analysis task and persist it to the database.

        Args:
            request: AnalysisRequest containing analysis parameters

        Returns:
            AnalysisResponse with task_id and initial status
        """
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            task = AnalysisTask(
                task_id=task_id or str(uuid.uuid4()),
                symbol=request.symbol,
                status=AnalysisStatus.PENDING.value,
                created_at=now,
                message=f"Task created for {request.symbol}",
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            return _orm_to_response(task)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_task(self, task_id: str) -> Optional[AnalysisResponse]:
        """
        Retrieve a task by its ID from the database.

        Args:
            task_id: UUID of the task to retrieve

        Returns:
            AnalysisResponse if found, None otherwise
        """
        db = SessionLocal()
        try:
            task = db.query(AnalysisTask).filter(
                AnalysisTask.task_id == task_id
            ).first()
            return _orm_to_response(task) if task else None
        finally:
            db.close()

    def list_tasks(
        self,
        status: Optional[AnalysisStatus] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[AnalysisResponse]:
        """
        List all tasks, optionally filtered by status and symbol.

        Args:
            status: Optional status filter
            symbol: Optional symbol filter
            limit: Maximum number of results to return

        Returns:
            List of AnalysisResponse objects
        """
        db = SessionLocal()
        try:
            query = db.query(AnalysisTask)
            if status is not None:
                query = query.filter(AnalysisTask.status == status.value)
            if symbol is not None:
                query = query.filter(AnalysisTask.symbol == symbol)
            query = query.order_by(AnalysisTask.created_at.desc())
            if limit is not None:
                query = query.limit(limit)
            return [_orm_to_response(t) for t in query.all()]
        finally:
            db.close()

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task from the database by its ID.

        Args:
            task_id: UUID of the task to delete

        Returns:
            True if the task was found and deleted, False otherwise
        """
        db = SessionLocal()
        try:
            task = db.query(AnalysisTask).filter(
                AnalysisTask.task_id == task_id
            ).first()
            if task is None:
                return False
            db.delete(task)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------

    def register_progress_callback(self, task_id: str, callback: Callable) -> None:
        """
        Register a progress callback for a task.

        Args:
            task_id: UUID of the task
            callback: Callable that accepts (task_id, progress_pct, current_agent)
        """
        self._progress_callbacks[task_id] = callback

    def get_task_progress(self, task_id: str) -> Dict[str, Any]:
        """
        Get progress information for a task including elapsed and remaining time.

        Args:
            task_id: UUID of the task

        Returns:
            Dict with progress info
        """
        task_resp = self.get_task(task_id)
        if not task_resp:
            return {}

        # Calculate elapsed time
        created_at = task_resp.created_at
        if created_at:
            try:
                start_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                now = datetime.now()
                if start_dt.tzinfo is not None:
                    now = datetime.now(start_dt.tzinfo)
                elapsed = (now - start_dt.replace(tzinfo=None)).total_seconds()
            except Exception:
                elapsed = 0
        else:
            elapsed = 0

        progress_pct = task_resp.progress_pct or 0
        remaining_raw = task_resp.remaining_time

        try:
            remaining = round(float(remaining_raw), 1) if remaining_raw is not None else None
        except (TypeError, ValueError):
            remaining = None

        # Calculate progress based on tracked status
        status = task_resp.status
        if status == AnalysisStatus.COMPLETED:
            progress = 100
            remaining = 0
        elif status == AnalysisStatus.FAILED:
            progress = 100
            remaining = 0
        elif status == AnalysisStatus.PENDING:
            progress = progress_pct
        else:  # RUNNING
            progress = progress_pct

        return {
            "task_id": task_id,
            "status": status.value if hasattr(status, 'value') else str(status),
            "progress": round(progress, 1),
            "elapsed": round(elapsed, 1),
            "remaining": remaining,
            "message": task_resp.message or "",
            "current_agent": task_resp.current_agent or "",
            "is_progress_indeterminate": bool(
                status in {AnalysisStatus.PENDING, AnalysisStatus.RUNNING} and remaining is None and progress < 100
            ),
        }

    # ------------------------------------------------------------------
    # Analysis execution
    # ------------------------------------------------------------------

    def _ensure_task_record(self, task_id: str, request: AnalysisRequest) -> AnalysisResponse:
        """Get or create a persisted task row using the provided task ID."""
        task_resp = self.get_task(task_id)
        if task_resp is not None:
            return task_resp
        return self.create_task(request, task_id=task_id)

    def _update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update task status with optional message and error fields."""
        db = SessionLocal()
        try:
            task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
            if task is None:
                return

            now = datetime.utcnow()
            task.status = status
            task.updated_at = now

            if status in {
                AnalysisStatus.COMPLETED.value,
                AnalysisStatus.FAILED.value,
                AnalysisStatus.CANCELLED.value,
            }:
                task.completed_at = task.completed_at or now

            if message is not None:
                task.message = message
            if error is not None:
                task.error = error

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _track_background_task(self, task: asyncio.Task) -> None:
        """Keep background tasks referenced until completion."""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _invoke_on_complete(
        self,
        task_id: str,
        on_complete: Optional[Callable[[str, Dict[str, Any]], None]],
    ) -> None:
        """Invoke completion callback with the latest task result."""
        if not on_complete:
            return

        final_task = self.get_task(task_id)
        result = final_task.result if final_task and final_task.result else {}
        on_complete(task_id, result)

    def _prepare_task_for_queue(
        self,
        task_id: str,
        request: AnalysisRequest,
        *,
        priority: int,
    ) -> AnalysisResponse:
        """Ensure the task exists and is ready for worker pickup.

        If enqueue fails the task is rolled back to FAILED so it never
        becomes an orphan PENDING entry (no matching analysis_queue row).
        """
        task_resp = self._ensure_task_record(task_id, request)
        self._update_task_status(
            task_id,
            AnalysisStatus.PENDING.value,
            message=f"Analysis queued for {request.symbol}",
            error=None,
        )

        try:
            enqueued = self.queue_service.enqueue(
                task_id,
                request.model_dump(mode="json"),
                priority=priority,
            )
            if not enqueued:
                logger.warning(
                    "Task %s enqueue returned False (already queued); treating as success",
                    task_id,
                )
        except Exception:
            logger.exception("Failed to enqueue task %s — marking as FAILED", task_id)
            self._update_task_status(
                task_id,
                AnalysisStatus.FAILED.value,
                error="Failed to enqueue task — queue persistence unavailable",
            )
            raise

        refreshed_task = self.get_task(task_id)
        return refreshed_task or task_resp

    def _apply_request_mode(self, request: AnalysisRequest, *, is_quick: Optional[bool] = None) -> AnalysisRequest:
        """Clone request with execution-mode overrides."""
        if is_quick is None:
            return request
        return request.model_copy(update={"is_quick": is_quick})

    def _wait_for_task_completion(self, task_id: str, timeout: int) -> AnalysisResponse:
        """Block until a queued task reaches a terminal state."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self.get_task(task_id)
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            if task.status in {
                AnalysisStatus.COMPLETED,
                AnalysisStatus.FAILED,
                AnalysisStatus.CANCELLED,
            }:
                return task
            time.sleep(0.5)

        raise TimeoutError(f"Analysis {task_id} did not complete within {timeout}s")

    async def _await_completion_callback(
        self,
        task_id: str,
        on_complete: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """Wait asynchronously for task completion before firing callbacks."""
        timeout = DEFAULT_CONFIG.get("analysis_timeout_seconds", 900)
        try:
            await asyncio.to_thread(self._wait_for_task_completion, task_id, timeout)
        except Exception:
            logger.exception("Completion callback wait failed for %s", task_id)
        finally:
            self._invoke_on_complete(task_id, on_complete)

    async def run_analysis(
        self,
        task_id: str,
        request: AnalysisRequest,
        on_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        priority: int = 0,
        blocking: bool = False,
        is_quick: Optional[bool] = None,
    ) -> AnalysisResponse:
        """
        Queue analysis for worker-based subprocess execution.

        Args:
            task_id: UUID of the task to run
            request: AnalysisRequest containing analysis parameters
            on_complete: Optional callback called when analysis finishes
            priority: Queue priority (higher values run earlier)
            blocking: True waits until a worker finishes the task

        Returns:
            AnalysisResponse with task state
        """
        request = self._apply_request_mode(request, is_quick=is_quick)
        task_resp = self._prepare_task_for_queue(task_id, request, priority=priority)

        if blocking:
            timeout = DEFAULT_CONFIG.get("analysis_timeout_seconds", 900)
            final_task = await asyncio.to_thread(self._wait_for_task_completion, task_id, timeout)
            self._invoke_on_complete(task_id, on_complete)
            return final_task

        if on_complete is not None:
            background_task = asyncio.create_task(
                self._await_completion_callback(task_id, on_complete)
            )
            self._track_background_task(background_task)

        task_resp.message = "Analysis queued for processing"
        return task_resp

    def run_analysis_sync(
        self,
        task_id: str,
        request: AnalysisRequest,
        priority: int = 10,
        timeout: int = 600,
        is_quick: Optional[bool] = None,
    ) -> AnalysisResponse:
        """
        Run analysis synchronously, waiting for completion.
        
        This method is used by the scheduler which needs to wait
        for analysis completion before proceeding.

        Args:
            task_id: UUID of the task to run
            request: AnalysisRequest containing analysis parameters
            priority: Task priority (default 10 for high priority)
            timeout: Maximum seconds to wait for completion

        Returns:
            AnalysisResponse with completed analysis result
        """
        request = self._apply_request_mode(request, is_quick=is_quick)
        self._prepare_task_for_queue(task_id, request, priority=priority)
        return self._wait_for_task_completion(task_id, timeout)

    def _run_sync_analysis(
        self,
        task_id: str,
        request: AnalysisRequest,
        is_quick: bool = False,
    ) -> Dict[str, Any]:
        """Compatibility sync runner used by older tests/debug scripts."""
        _ = task_id
        from webapi.subprocess_runner import _resolve_runner_config
        from tradingagents.core.analysis_runner import AnalysisRunner

        request = self._apply_request_mode(request, is_quick=is_quick)
        runner_config = _resolve_runner_config(request)
        runner = AnalysisRunner(
            symbol=request.symbol,
            date=request.date or datetime.utcnow().strftime("%Y-%m-%d"),
            analysts=request.analysts or ["market_index", "market", "news", "social", "fundamentals"],
            llm_model=runner_config["llm_model"],
            llm_provider=runner_config["llm_provider"],
            base_url=runner_config["base_url"],
            api_key=runner_config["api_key"],
            max_iterations=300,
            fast_mode=request.is_quick,
        )
        result = runner.run()
        result["analysis_type"] = "quick" if request.is_quick else result.get("analysis_type", "full")
        return result

    def _update_task_progress(self, task_id: str, progress_data: Dict[str, Any]):
        """Update task progress in database using targeted column update.
        
        Uses column-only UPDATE to avoid race conditions with the main thread
        that may be writing the final result.
        
        Args:
            task_id: UUID of the task
            progress_data: Dict containing agents_progress, current_agent, progress_pct, message, timestamp
        """
        db = SessionLocal()
        try:
            # First check if task is still running (don't overwrite completed results)
            task_status = db.query(AnalysisTask.status).filter(
                AnalysisTask.task_id == task_id
            ).scalar()
            
            # Only update progress if task is still running
            if task_status in ("PENDING", "RUNNING"):
                # Append to logs - need to fetch current logs first
                current_logs = db.query(AnalysisTask.logs).filter(
                    AnalysisTask.task_id == task_id
                ).scalar() or []
                
                new_log = {
                    "timestamp": progress_data.get("timestamp"),
                    "agent": progress_data.get("current_agent"),
                    "progress": progress_data.get("progress_pct"),
                    "message": progress_data.get("message", ""),
                }
                updated_logs = (current_logs + [new_log])[-100:]
                
                # Use targeted column update to avoid race condition
                db.query(AnalysisTask).filter(
                    AnalysisTask.task_id == task_id
                ).update({
                    "agents_progress": progress_data.get("agents_progress", {}),
                    "current_agent": progress_data.get("current_agent", ""),
                    "progress_pct": progress_data.get("progress_pct", 0),
                    "updated_at": datetime.utcnow(),
                    "message": progress_data.get("message", "") or progress_data.get("current_agent", ""),
                    "logs": updated_logs,
                }, synchronize_session=False)
                
                db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Error updating task progress: {e}")
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    async def run_batch(
        self, request: BatchAnalysisRequest
    ) -> BatchAnalysisResponse:
        """
        Run batch analysis for multiple symbols.

        Args:
            request: BatchAnalysisRequest containing symbols and parameters

        Returns:
            BatchAnalysisResponse with all task results
        """
        batch_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Create individual tasks for each symbol (persists to DB)
        tasks = []
        task_ids = []
        for symbol in request.symbols:
            single_request = AnalysisRequest(
                symbol=symbol,
                date=request.date,
                exchange=request.exchange,
                source=request.source,
                analysts=request.analysts,
                force_refresh=request.force_refresh,
            )
            task_response = self.create_task(single_request)
            tasks.append(task_response)
            task_ids.append(task_response.task_id)

        # Persist batch metadata to database
        db = SessionLocal()
        try:
            batch = AnalysisBatch(
                batch_id=batch_id,
                total=len(request.symbols),
                completed_count=0,
                failed_count=0,
                status=AnalysisStatus.RUNNING.value,
                created_at=now,
                task_ids=task_ids,
                symbols=request.symbols,
                message=f"Batch analysis started for {len(request.symbols)} symbols",
            )
            db.add(batch)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        # Create batch response
        batch_response = BatchAnalysisResponse(
            batch_id=batch_id,
            total=len(request.symbols),
            tasks=tasks,
            status=AnalysisStatus.RUNNING,
            created_at=now.isoformat(),
        )
        self._batch_tasks[batch_id] = batch_response  # Keep for backward compatibility

        # Start all tasks asynchronously and return immediately.
        coroutines = [
            self.run_analysis(task.task_id, AnalysisRequest(
                symbol=task.symbol,
                date=request.date,
                exchange=request.exchange,
                source=request.source,
                analysts=request.analysts,
                force_refresh=request.force_refresh,
            ), blocking=False)
            for task in tasks
        ]

        results = await asyncio.gather(*coroutines)
        batch_response.tasks = results

        self._batch_tasks[batch_id] = batch_response
        return batch_response

    def get_batch(self, batch_id: str) -> Optional[BatchAnalysisResponse]:
        """
        Retrieve a batch by its ID from the database.

        Args:
            batch_id: UUID of the batch to retrieve

        Returns:
            BatchAnalysisResponse if found, None otherwise
        """
        # Try to get from database first
        db = SessionLocal()
        try:
            db_batch = db.query(AnalysisBatch).filter(
                AnalysisBatch.batch_id == batch_id
            ).first()
            if db_batch:
                # Get all associated tasks
                tasks = []
                if db_batch.task_ids:
                    for task_id in db_batch.task_ids:
                        task_resp = self.get_task(task_id)
                        if task_resp:
                            tasks.append(task_resp)
                return _batch_orm_to_response(db_batch, tasks)
        finally:
            db.close()

        # Fallback to in-memory for backward compatibility
        return self._batch_tasks.get(batch_id)

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task (marks as cancelled, does not kill running thread).

        Args:
            task_id: UUID of the task to cancel

        Returns:
            True if task was found and marked as cancelled, False otherwise
        """
        db = SessionLocal()
        try:
            db_task = db.query(AnalysisTask).filter(
                AnalysisTask.task_id == task_id
            ).first()
            if db_task is None:
                return False

            current_status = db_task.status
            if current_status in (
                AnalysisStatus.RUNNING.value,
                AnalysisStatus.PENDING.value,
            ):
                db_task.status = AnalysisStatus.CANCELLED.value
                db_task.message = (
                    "Task cancellation requested"
                    if current_status == AnalysisStatus.RUNNING.value
                    else "Task cancelled before execution"
                )
                db_task.updated_at = datetime.utcnow()
                db.commit()

                try:
                    self.queue_service.cancel(task_id, "Task cancelled")
                except Exception:
                    logger.exception("Failed to update queue state during cancellation for %s", task_id)
                return True

            return False
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create_batch_task(self, request: BatchAnalysisRequest) -> BatchAnalysisResponse:
        """Create a batch task (synchronous wrapper for run_batch)."""
        batch_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Create individual tasks for each symbol (persists to DB)
        tasks = []
        task_ids = []
        for symbol in request.symbols:
            single_request = AnalysisRequest(
                symbol=symbol,
                date=request.date,
                exchange=request.exchange,
                source=request.source,
                analysts=request.analysts,
                force_refresh=request.force_refresh,
            )
            task_response = self.create_task(single_request)
            tasks.append(task_response)
            task_ids.append(task_response.task_id)

        # Persist batch metadata to database
        db = SessionLocal()
        try:
            batch = AnalysisBatch(
                batch_id=batch_id,
                total=len(request.symbols),
                completed_count=0,
                failed_count=0,
                status=AnalysisStatus.RUNNING.value,
                created_at=now,
                task_ids=task_ids,
                symbols=request.symbols,
                message=f"Batch analysis created for {len(request.symbols)} symbols",
            )
            db.add(batch)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        # Create batch response
        batch_response = BatchAnalysisResponse(
            batch_id=batch_id,
            total=len(request.symbols),
            completed_count=0,
            failed_count=0,
            tasks=tasks,
            status=AnalysisStatus.RUNNING,
            created_at=now.isoformat(),
        )
        self._batch_tasks[batch_id] = batch_response
        return batch_response

    # ------------------------------------------------------------------
    # Error query methods for debugging and monitoring
    # ------------------------------------------------------------------

    def get_error_stats(self, days: int = 7) -> Dict[str, int]:
        """Get error statistics by type for the last N days.
        
        Parses the structured error JSON stored in task.error field.
        
        Args:
            days: Number of days to look back (default 7)
            
        Returns:
            Dict mapping error types to counts
        """
        from sqlalchemy import text
        
        db = SessionLocal()
        try:
            # Query error counts by type using PostgreSQL JSON operator
            # error::jsonb->>'type' extracts the 'type' field from JSON
            # Use :days * interval '1 day' for proper parameter binding
            query = text("""
                SELECT 
                    COALESCE(error::jsonb->>'type', 'unknown') as error_type,
                    COUNT(*) as count
                FROM analysis_tasks
                WHERE status = 'FAILED'
                    AND error IS NOT NULL
                    AND created_at >= NOW() - (:days * INTERVAL '1 day')
                GROUP BY error::jsonb->>'type'
                ORDER BY count DESC
            """)
            
            result = db.execute(query, {"days": days})
            stats: Dict[str, int] = {}
            for row in result:
                stats[row.error_type] = row.count
            return stats
        except Exception as e:
            logger.warning(f"Error querying error stats: {e}")
            return {}
        finally:
            db.close()

    def get_llm_timeout_tasks(self, days: int = 7, limit: int = 100) -> List[AnalysisResponse]:
        """Get tasks that failed due to LLM timeout for retry debugging.
        
        Args:
            days: Number of days to look back (default 7)
            limit: Maximum number of tasks to return
            
        Returns:
            List of AnalysisResponse for timeout errors
        """
        db = SessionLocal()
        try:
            # Query for tasks with llm_timeout error type
            # Use PostgreSQL JSON containment operator @>
            tasks = db.query(AnalysisTask).filter(
                AnalysisTask.status == AnalysisStatus.FAILED.value,
                AnalysisTask.error.isnot(None),
                AnalysisTask.created_at >= datetime.utcnow() - timedelta(days=days)
            ).order_by(AnalysisTask.created_at.desc()).limit(limit).all()
            
            # Filter for llm_timeout errors by parsing JSON
            timeout_tasks = []
            for task in tasks:
                try:
                    error_data = json.loads(task.error) if task.error else {}
                    if error_data.get("type") == "llm_timeout":
                        timeout_tasks.append(_orm_to_response(task))
                except (json.JSONDecodeError, TypeError):
                    continue
                    
            return timeout_tasks
        except Exception as e:
            logger.warning(f"Error querying LLM timeout tasks: {e}")
            return []
        finally:
            db.close()

    def get_tasks_by_error_type(self, error_type: str, days: int = 7, limit: int = 100) -> List[AnalysisResponse]:
        """Get tasks filtered by specific error type.
        
        Args:
            error_type: Error type to filter by (e.g., 'llm_timeout', 'api_error')
            days: Number of days to look back (default 7)
            limit: Maximum number of tasks to return
            
        Returns:
            List of AnalysisResponse matching the error type
        """
        db = SessionLocal()
        try:
            # Get recent failed tasks and filter by error type
            tasks = db.query(AnalysisTask).filter(
                AnalysisTask.status == AnalysisStatus.FAILED.value,
                AnalysisTask.error.isnot(None),
                AnalysisTask.created_at >= datetime.utcnow() - timedelta(days=days)
            ).order_by(AnalysisTask.created_at.desc()).limit(limit).all()
            
            # Filter by error type
            matching_tasks = []
            for task in tasks:
                try:
                    error_data = json.loads(task.error) if task.error else {}
                    if error_data.get("type") == error_type:
                        matching_tasks.append(_orm_to_response(task))
                except (json.JSONDecodeError, TypeError):
                    continue
                    
            return matching_tasks
        except Exception as e:
            logger.warning(f"Error querying tasks by error type: {e}")
            return []
        finally:
            db.close()

    def shutdown(self) -> None:
        """Shutdown cleanup (no-op for queue-based architecture)."""
        # ThreadPoolExecutor removed - queue-based architecture uses subprocess
        pass


# Global singleton instance
analysis_service = AnalysisService()
