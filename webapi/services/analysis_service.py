# TradingAgents WebAPI Services - Analysis Service
"""
Async wrapper service for the core AnalysisRunner, providing task management
and progress tracking for the FastAPI layer.
"""

import asyncio
import os
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# Load environment variables from .env file
from dotenv import load_dotenv
# Find project root (where .env file is located)
_current_dir = os.path.dirname(os.path.abspath(__file__))
# Go up 3 levels: services -> webapi -> project_root
_project_root = os.path.abspath(os.path.join(_current_dir, '..', '..'))
env_path = os.path.join(_project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # Fallback: try loading from current working directory
    load_dotenv()

from tradingagents.core.analysis_runner import AnalysisRunner
from webapi.models.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatus,
    BatchAnalysisRequest,
    BatchAnalysisResponse,
)


class AnalysisService:
    """
    Async wrapper service for running TradingAgents analysis tasks.
    
    Provides task management, progress tracking, and async execution
    for the FastAPI web layer.
    """

    def __init__(self, max_workers: int = 4):
        """
        Initialize the AnalysisService.
        
        Args:
            max_workers: Maximum number of concurrent analysis tasks (default: 4)
        """
        self._tasks: Dict[str, AnalysisResponse] = {}
        self._batch_tasks: Dict[str, BatchAnalysisResponse] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._progress_callbacks: Dict[str, Callable] = {}

    def create_task(self, request: AnalysisRequest) -> AnalysisResponse:
        """
        Create a new analysis task and store it in memory.
        
        Args:
            request: AnalysisRequest containing analysis parameters
            
        Returns:
            AnalysisResponse with task_id and initial status
        """
        task_id = str(uuid.uuid4())
        
        task_response = AnalysisResponse(
            task_id=task_id,
            status=AnalysisStatus.PENDING,
            symbol=request.symbol,
            message=f"Task created for {request.symbol}",
            created_at=datetime.now().isoformat(),
            logs=[f"Task {task_id} created at {datetime.now().isoformat()}"],
        )
        
        self._tasks[task_id] = task_response
        return task_response

    def get_task(self, task_id: str) -> Optional[AnalysisResponse]:
        """
        Retrieve a task by its ID.
        
        Args:
            task_id: UUID of the task to retrieve
            
        Returns:
            AnalysisResponse if found, None otherwise
        """
        return self._tasks.get(task_id)

    def list_tasks(
        self, 
        status: Optional[AnalysisStatus] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None
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
        tasks = list(self._tasks.values())
        
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        
        if symbol is not None:
            tasks = [task for task in tasks if task.symbol == symbol]
        
        if limit is not None:
            tasks = tasks[:limit]
        
        return tasks

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
        import time
        task = self._tasks.get(task_id)
        if not task:
            return {}
        
        # Calculate elapsed time
        created_at = task.created_at
        if created_at:
            try:
                from datetime import datetime
                start_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                # Handle both timezone-aware and naive datetime
                now = datetime.now()
                if start_dt.tzinfo is not None:
                    now = datetime.now(start_dt.tzinfo)
                elapsed = (now - start_dt.replace(tzinfo=None)).total_seconds()
            except:
                elapsed = 0
        else:
            elapsed = 0
        
        # Estimate total time based on analysts count (rough estimate)
        analysts = getattr(task, 'analysts', None) or []
        analyst_count = len(analysts) if analysts else 1
        # Base estimate: 60 seconds per analyst + 60 seconds base
        estimated_total = 60 * analyst_count + 60
        
        # Calculate progress based on status
        status = task.status
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
            # Estimate progress based on elapsed time vs expected
            if elapsed < 30:
                progress = min(10, (elapsed / 30) * 10)
            elif elapsed < 60:
                progress = 10 + min(20, ((elapsed - 30) / 30) * 20)
            elif elapsed < 120:
                progress = 30 + min(25, ((elapsed - 60) / 60) * 25)
            else:
                progress = min(55, 55 + ((elapsed - 120) / 120) * 20)  # Up to 75% at 4 min
            remaining = max(0, estimated_total - elapsed)
        
        return {
            "task_id": task_id,
            "status": status.value if hasattr(status, 'value') else str(status),
            "progress": round(progress, 1),
            "elapsed": round(elapsed, 1),
            "remaining": round(remaining, 1),
            "message": task.message or "",
        }

    async def run_analysis(
        self, task_id: str, request: AnalysisRequest
    ) -> AnalysisResponse:
        """
        Run analysis for a task asynchronously using thread pool executor.
        
        Args:
            task_id: UUID of the task to run
            request: AnalysisRequest containing analysis parameters
            
        Returns:
            AnalysisResponse with completed analysis result
        """
        # Get or create task
        task = self._tasks.get(task_id)
        if task is None:
            task = self.create_task(request)
            task_id = task.task_id

        # Update status to running
        task.status = AnalysisStatus.RUNNING
        task.updated_at = datetime.now().isoformat()
        task.message = f"Running analysis for {request.symbol}"
        task.logs.append(f"Started analysis at {datetime.now().isoformat()}")
        self._tasks[task_id] = task

        try:
            # Get event loop and run sync analysis in executor
            loop = asyncio.get_event_loop()
            
            # Run the sync analysis in thread pool
            result = await loop.run_in_executor(
                None, self._run_sync_analysis, task_id, request
            )
            
            # Update task with result
            task.result = result
            task.status = AnalysisStatus.COMPLETED
            task.completed_at = datetime.now().isoformat()
            task.message = f"Analysis completed for {request.symbol}"
            task.logs.append(f"Completed at {datetime.now().isoformat()}")
            
        except Exception as e:
            task.status = AnalysisStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now().isoformat()
            task.message = f"Analysis failed: {str(e)}"
            task.logs.append(f"Failed at {datetime.now().isoformat()}: {traceback.format_exc()}")
        
        task.updated_at = datetime.now().isoformat()
        self._tasks[task_id] = task
        
        return task

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
            llm_provider = request.llm_provider or "openai"
            llm_model = request.deep_model or request.quick_model or "gpt-4"
            
            # Map minimax to openai with custom base_url
            base_url = None
            if llm_provider.lower() == "minimax":
                base_url = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.chat/v1")
                llm_provider = "openai"
                # MiniMax API key needs to be in OPENAI_API_KEY for OpenAIClient
                # Try MINIMAX_API_KEY first, fallback to OPENAI_API_KEY
                minimax_key = os.getenv("MINIMAX_API_KEY")
                openai_key = os.getenv("OPENAI_API_KEY")
                if minimax_key:
                    os.environ["OPENAI_API_KEY"] = minimax_key
                elif openai_key:
                    # Already set in OPENAI_API_KEY, ensure it's in environ
                    os.environ["OPENAI_API_KEY"] = openai_key
            
            analysts = request.analysts or ["market", "news", "fundamentals"]
            
            # Create runner instance
            runner = AnalysisRunner(
                symbol=symbol,
                date=date,
                analysts=analysts,
                llm_model=llm_model,
                llm_provider=llm_provider,
                base_url=base_url,
            )
            
            # Run analysis
            result = runner.run()
            
            # Invoke progress callback if registered
            if task_id in self._progress_callbacks:
                callback = self._progress_callbacks[task_id]
                callback(
                    task_id,
                    result.get("progress_pct", 0),
                    result.get("current_agent", "")
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
        
        # Create individual tasks for each symbol
        tasks = []
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
        
        # Create batch response
        batch_response = BatchAnalysisResponse(
            batch_id=batch_id,
            total=len(request.symbols),
            tasks=tasks,
            status=AnalysisStatus.RUNNING,
            created_at=datetime.now().isoformat(),
        )
        self._batch_tasks[batch_id] = batch_response
        
        # Run all tasks concurrently
        async def run_single(task_id: str, req: AnalysisRequest):
            return await self.run_analysis(task_id, req)
        
        # Execute all tasks
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
        
        # Update batch status
        batch_response.tasks = results
        failed_count = sum(1 for r in results if isinstance(r, Exception) or r.status == AnalysisStatus.FAILED)
        batch_response.status = AnalysisStatus.FAILED if failed_count == len(results) else AnalysisStatus.COMPLETED
        
        self._batch_tasks[batch_id] = batch_response
        return batch_response

    def get_batch(self, batch_id: str) -> Optional[BatchAnalysisResponse]:
        """
        Retrieve a batch by its ID.
        
        Args:
            batch_id: UUID of the batch to retrieve
            
        Returns:
            BatchAnalysisResponse if found, None otherwise
        """
        return self._batch_tasks.get(batch_id)

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task (marks as cancelled, does not kill running thread).
        
        Args:
            task_id: UUID of the task to cancel
            
        Returns:
            True if task was found and marked as cancelled, False otherwise
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        
        if task.status == AnalysisStatus.RUNNING:
            # Cannot truly cancel a running task, just mark it
            task.status = AnalysisStatus.CANCELLED
            task.message = "Task cancellation requested"
            task.updated_at = datetime.now()
            self._tasks[task_id] = task
            return True
        elif task.status in (AnalysisStatus.PENDING,):
            task.status = AnalysisStatus.CANCELLED
            task.message = "Task cancelled before execution"
            task.updated_at = datetime.now()
            self._tasks[task_id] = task
            return True
        
        return False

    def create_batch_task(self, request: BatchAnalysisRequest) -> BatchAnalysisResponse:
        """Create a batch task (synchronous wrapper for run_batch)."""
        import asyncio
        # Create batch ID and initial tasks synchronously
        batch_id = str(uuid.uuid4())
        
        # Create individual tasks for each symbol
        tasks = []
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
        
        # Create batch response
        batch_response = BatchAnalysisResponse(
            batch_id=batch_id,
            total=len(request.symbols),
            tasks=tasks,
            status=AnalysisStatus.RUNNING,
            created_at=datetime.now().isoformat(),
        )
        self._batch_tasks[batch_id] = batch_response
        return batch_response

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=True)


# Global singleton instance
analysis_service = AnalysisService()
