# TradingAgents WebAPI Services - Analysis Service
"""
Async wrapper service for the core AnalysisRunner, providing task management
and progress tracking for the FastAPI layer.

Storage is backed by PostgreSQL via SQLAlchemy ORM (AnalysisTask model).
"""

import asyncio
import logging
import os
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# Load environment variables from .env file
from dotenv import load_dotenv
# Try multiple locations for .env file
env_loaded = False
for env_path in ['.env', '../.env', '../../.env', 'D:/1.MyProjects/Other/tradingagents-a-share/.env']:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        env_loaded = True
        print(f"[ENV] Loaded .env from: {env_path}", flush=True)
        break
if not env_loaded:
    load_dotenv()  # Fallback to default behavior
    print("[ENV] Using default load_dotenv()", flush=True)

# Debug: check if key is loaded
print(f"[ENV] OPENAI_API_KEY present: {bool(os.getenv('OPENAI_API_KEY'))}", flush=True)

from tradingagents.core.analysis_runner import AnalysisRunner
from webapi.models.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    BatchAnalysisRequest,
    BatchAnalysisResponse,
)
from webapi.models.database import AnalysisTask, AnalysisBatch
from webapi.config.database import SessionLocal

# Import local history persistence (no API dependencies)
from webapi.services.history_persistence import add_to_local_history

logger = logging.getLogger(__name__)


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

        # Estimate remaining time based on progress
        progress_pct = result_data.get("progress_pct", 0) if isinstance(result_data, dict) else 0
        if progress_pct > 0 and progress_pct < 100:
            estimated_total = int(elapsed_seconds * 100 / progress_pct)
            remaining_seconds = max(0, estimated_total - elapsed_seconds)
            remaining_time = remaining_seconds
        else:
            remaining_time = 0
    else:
        elapsed_seconds = 0
        remaining_time = 0

    # Keep elapsed/remaining time available in result_data for UI paths
    # that read result_data.get("elapsed_time") / result_data.get("remaining_time").
    if not isinstance(result_data, dict):
        result_data = {}
    result_data["elapsed_time"] = elapsed_seconds
    result_data["remaining_time"] = remaining_time

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

    def __init__(self, max_workers: int = 4):
        """
        Initialize the AnalysisService.

        Args:
            max_workers: Maximum number of concurrent analysis tasks (default: 4)
        """
        self._batch_tasks: Dict[str, BatchAnalysisResponse] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._progress_callbacks: Dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # CRUD operations backed by PostgreSQL
    # ------------------------------------------------------------------

    def create_task(self, request: AnalysisRequest) -> AnalysisResponse:
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
                task_id=str(uuid.uuid4()),
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

        # Estimate total time based on analysts count (rough estimate)
        analysts = task_resp.result.get("analysts", []) if task_resp.result else []
        analyst_count = len(analysts) if analysts else 1
        estimated_total = 60 * analyst_count + 60

        # Calculate progress based on status
        status = task_resp.status
        if status == AnalysisStatus.COMPLETED:
            progress = 100
            remaining = 0
        elif status == AnalysisStatus.FAILED:
            progress = 100
            remaining = 0
        elif status == AnalysisStatus.PENDING:
            progress = 0
            remaining = estimated_total
        else:  # RUNNING
            if elapsed < 30:
                progress = min(10, (elapsed / 30) * 10)
            elif elapsed < 60:
                progress = 10 + min(20, ((elapsed - 30) / 30) * 20)
            elif elapsed < 120:
                progress = 30 + min(25, ((elapsed - 60) / 60) * 25)
            else:
                progress = min(55, 55 + ((elapsed - 120) / 120) * 20)
            remaining = max(0, estimated_total - elapsed)

        return {
            "task_id": task_id,
            "status": status.value if hasattr(status, 'value') else str(status),
            "progress": round(progress, 1),
            "elapsed": round(elapsed, 1),
            "remaining": round(remaining, 1),
            "message": task_resp.message or "",
        }

    # ------------------------------------------------------------------
    # Analysis execution
    # ------------------------------------------------------------------

    async def run_analysis(
        self,
        task_id: str,
        request: AnalysisRequest,
        on_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> AnalysisResponse:
        """
        Run analysis for a task asynchronously using thread pool executor.

        Args:
            task_id: UUID of the task to run
            request: AnalysisRequest containing analysis parameters
            on_complete: Optional callback called when analysis finishes (receives task_id, result dict)

        Returns:
            AnalysisResponse with completed analysis result
        """
        # Get or create task from DB
        task_resp = self.get_task(task_id)
        if task_resp is None:
            task_resp = self.create_task(request)
            task_id = task_resp.task_id

        # Update status to RUNNING in DB
        now = datetime.utcnow()
        db = SessionLocal()
        try:
            db_task = db.query(AnalysisTask).filter(
                AnalysisTask.task_id == task_id
            ).first()
            if db_task:
                db_task.status = AnalysisStatus.RUNNING.value
                db_task.updated_at = now
                db_task.message = f"Running analysis for {request.symbol}"
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        # Re-read to get fresh state
        task_resp = self.get_task(task_id)

        timeout_raw = os.getenv("ANALYSIS_TIMEOUT", "600")
        try:
            timeout_seconds = max(1, int(timeout_raw))
        except (TypeError, ValueError):
            timeout_seconds = 600
            logger.warning(
                "Invalid ANALYSIS_TIMEOUT value '%s', falling back to %s seconds",
                timeout_raw,
                timeout_seconds,
            )

        result = None
        try:
            # Run the sync analysis in thread pool
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._run_sync_analysis, task_id, request),
                timeout=timeout_seconds,
            )

            # Update task with result in DB
            now = datetime.utcnow()
            db = SessionLocal()
            try:
                db_task = db.query(AnalysisTask).filter(
                    AnalysisTask.task_id == task_id
                ).first()
                if db_task:
                    db_task.result = result
                    db_task.completed_at = now
                    db_task.updated_at = now

                    if isinstance(result, dict) and result.get("status") == "error":
                        db_task.status = AnalysisStatus.FAILED.value
                        db_task.error = result.get("error", "Analysis failed")
                        db_task.message = f"Analysis failed: {db_task.error}"
                    else:
                        db_task.status = AnalysisStatus.COMPLETED.value
                        db_task.message = f"Analysis completed for {request.symbol}"
                        # Extract decision from result.signal
                        if result and result.get("signal"):
                            signal = result["signal"]
                            if isinstance(signal, dict):
                                db_task.decision = signal.get("decision")
                            elif isinstance(signal, str):
                                # process_signal() returns raw LLM content; extract last word
                                # The LLM is prompted to output "BUY/OVERWEIGHT/HOLD/UNDERWEIGHT/SELL"
                                valid = {"BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "SELL"}
                                words = signal.strip().split()
                                for w in reversed(words):
                                    if w.upper() in valid:
                                        db_task.decision = w.upper()
                                        break

                    db.commit()

                    # Call completion callback if provided
                    if on_complete:
                        try:
                            on_complete(task_id, result)
                        except Exception as cb_err:
                            logger.warning("Completion callback error: %s", cb_err)
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        except asyncio.TimeoutError:
            timeout_error = f"Analysis timed out after {timeout_seconds}s"
            now = datetime.utcnow()
            db = SessionLocal()
            try:
                db_task = db.query(AnalysisTask).filter(
                    AnalysisTask.task_id == task_id
                ).first()
                if db_task:
                    db_task.status = AnalysisStatus.FAILED.value
                    db_task.error = timeout_error
                    db_task.completed_at = now
                    db_task.updated_at = now
                    db_task.message = f"Analysis failed: {timeout_error}"
                    db.commit()

                    # Call completion callback on timeout error
                    if on_complete:
                        try:
                            on_complete(task_id, {"status": "error", "error": timeout_error})
                        except Exception as cb_err:
                            logger.warning("Completion callback error: %s", cb_err)
            except Exception:
                db.rollback()
            finally:
                db.close()
        except Exception as e:
            now = datetime.utcnow()
            db = SessionLocal()
            try:
                db_task = db.query(AnalysisTask).filter(
                    AnalysisTask.task_id == task_id
                ).first()
                if db_task:
                    db_task.status = AnalysisStatus.FAILED.value
                    db_task.error = str(e)
                    db_task.completed_at = now
                    db_task.updated_at = now
                    db_task.message = f"Analysis failed: {str(e)}"
                    db.commit()

                    # Call completion callback on error
                    if on_complete:
                        try:
                            on_complete(task_id, {"status": "error", "error": str(e)})
                        except Exception as cb_err:
                            logger.warning("Completion callback error: %s", cb_err)
            except Exception:
                db.rollback()
            finally:
                db.close()

        # Re-read final state from DB
        task_resp = self.get_task(task_id)
        if task_resp is None:
            # Should not happen — task was just updated — but guard for type safety
            return AnalysisResponse(
                task_id=task_id,
                status=AnalysisStatus.FAILED,
                symbol=request.symbol,
                message="Task completed but could not be re-read from database",
            )

        # Persist to history when task completes (COMPLETED or FAILED)
        if task_resp and task_resp.status in (AnalysisStatus.COMPLETED, AnalysisStatus.FAILED):
            try:
                history_result = dict(task_resp.result or {})
                history_result["status"] = task_resp.status.value
                history_result["symbol"] = task_resp.symbol
                if task_resp.result and isinstance(task_resp.result.get("signal"), dict):
                    history_result["decision"] = task_resp.result["signal"].get("decision", "UNKNOWN")
                if task_resp.error:
                    history_result["error"] = task_resp.error
                add_to_local_history(
                    task_id,
                    task_resp.symbol,
                    history_result,
                    created_at=task_resp.created_at or "",
                    updated_at=task_resp.completed_at or "",
                )
            except Exception as hist_err:
                logger.warning("History persistence warning: %s", hist_err)

        return task_resp

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
                    "logs": updated_logs,
                }, synchronize_session=False)
                
                db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Error updating task progress: {e}")
        finally:
            db.close()

    def _run_sync_analysis(
        self, task_id: str, request: AnalysisRequest
    ) -> Dict[str, Any]:
        """
        Synchronous analysis runner to be executed in thread pool.

        Args:
            task_id: UUID of the task
            request: AnalysisRequest containing analysis parameters

        Returns:
            Dict containing analysis results
        """
        try:
            # Build parameters for AnalysisRunner
            symbol = request.symbol
            date = request.date or datetime.now().strftime("%Y-%m-%d")

            # Determine LLM model and provider
            # Priority: request params > env vars > model-name heuristic
            llm_provider = request.llm_provider or os.getenv("LLM_PROVIDER", "openai")

            # Determine model
            deep_model = request.deep_model or os.getenv("DEEP_THINK_LLM", "gpt-4")
            quick_model = request.quick_model or os.getenv("QUICK_THINK_LLM", "gpt-4")

            # Auto-detect provider from model name if provider is generic "openai"
            # but model is clearly a non-OpenAI model (e.g. MiniMax, Gemini)
            if llm_provider.lower() == "openai" and not request.llm_provider:
                model_lower = (deep_model + " " + quick_model).lower()
                if "minimax" in model_lower:
                    llm_provider = "minimax"

            # Map minimax to openai-compatible with custom base_url
            base_url = None
            api_key = None
            if llm_provider.lower() == "minimax":
                base_url = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.chat/v1")
                llm_provider = "openai"  # MiniMax uses OpenAI-compatible API
                api_key = os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY")
                deep_model = request.deep_model or os.getenv("DEEP_THINK_LLM", "MiniMax-M2.7")
                quick_model = request.quick_model or os.getenv("QUICK_THINK_LLM", "MiniMax-M2.7")
                print(f"[API_KEY_TRACE] analysis_service: minimax mode, api_key length = {len(api_key) if api_key else 0}", flush=True)

            llm_model = deep_model

            analysts = request.analysts or ["market", "news", "fundamentals"]

            # Create runner instance with progress callback
            runner = AnalysisRunner(
                symbol=symbol,
                date=date,
                analysts=analysts,
                llm_model=llm_model,
                llm_provider=llm_provider,
                max_iterations=300,
                base_url=base_url,
                api_key=api_key,
                progress_callback=lambda data: self._update_task_progress(task_id, data),
            )

            # Run analysis
            result = runner.run()

            # Invoke progress callback if registered
            if task_id in self._progress_callbacks:
                callback = self._progress_callbacks[task_id]
                callback(
                    task_id,
                    result.get("progress_pct", 0),
                    result.get("current_agent", ""),
                )

            return result

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "progress_pct": 0,
                "current_agent": "error",
            }

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

        # Run all tasks concurrently
        async def run_single(tid: str, req: AnalysisRequest):
            return await self.run_analysis(tid, req)

        coroutines = [
            run_single(task.task_id, AnalysisRequest(
                symbol=task.symbol,
                date=request.date,
                exchange=request.exchange,
                source=request.source,
                analysts=request.analysts,
            ))
            for task in tasks
        ]

        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # Calculate final counts
        failed_count = sum(1 for r in results if isinstance(r, Exception) or (
            hasattr(r, 'status') and r.status == AnalysisStatus.FAILED
        ))
        completed_count = len(results) - failed_count
        final_status = AnalysisStatus.FAILED if failed_count == len(results) else AnalysisStatus.COMPLETED
        completed_at = datetime.utcnow()

        # Update batch in database
        db = SessionLocal()
        try:
            db_batch = db.query(AnalysisBatch).filter(
                AnalysisBatch.batch_id == batch_id
            ).first()
            if db_batch:
                db_batch.completed_count = completed_count
                db_batch.failed_count = failed_count
                db_batch.status = final_status.value
                db_batch.updated_at = completed_at
                db_batch.completed_at = completed_at
                db_batch.message = f"Batch completed: {completed_count} succeeded, {failed_count} failed"
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        # Update batch response
        batch_response.tasks = results
        batch_response.completed_count = completed_count
        batch_response.failed_count = failed_count
        batch_response.status = final_status
        batch_response.updated_at = completed_at.isoformat()
        batch_response.completed_at = completed_at.isoformat()

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

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=True)


# Global singleton instance
analysis_service = AnalysisService()
