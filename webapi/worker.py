#!/usr/bin/env python3
"""
Analysis Worker - PostgreSQL Queue Consumer

Consumes analysis tasks from the PostgreSQL queue and executes them
in isolated subprocesses.

Usage:
    python -m webapi.worker --worker-id worker-1
    python -m webapi.worker --worker-id worker-2  # Start multiple workers
    python -m webapi.worker --poll-interval 2.0 --max-tasks 100
"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportDeprecated=false

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime
from typing import Optional

# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

# Windows asyncio fix
import platform
if platform.system() == "Windows":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text

from webapi.services.queue_service import AnalysisQueueService
from webapi.config.database import SessionLocal
from webapi.models.analysis import AnalysisStatus
from webapi.models.database import AnalysisTask

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AnalysisWorker:
    """Worker that consumes analysis tasks from PostgreSQL queue."""
    
    def __init__(
        self, 
        worker_id: str, 
        poll_interval: float = 1.0,
        max_tasks: Optional[int] = None,
        task_timeout: Optional[int] = None
    ):
        """
        Initialize worker.
        
        Args:
            worker_id: Unique identifier for this worker
            poll_interval: Seconds between queue polls when empty
            max_tasks: Maximum tasks to process before exiting (None = infinite)
            task_timeout: Maximum seconds to wait for a task to complete.
                         Priority: argument > env var > config default > 600
        """
        self.worker_id = worker_id
        self.poll_interval = poll_interval
        self.max_tasks = max_tasks
        
        # Determine task timeout: argument > env var > config default > 600
        if task_timeout is not None:
            # CLI argument takes highest priority
            self.task_timeout = task_timeout
        else:
            # Try environment variable
            env_timeout = os.getenv("WORKER_TASK_TIMEOUT")
            if env_timeout:
                try:
                    self.task_timeout = int(env_timeout)
                except ValueError:
                    logger.warning(f"Invalid WORKER_TASK_TIMEOUT value: {env_timeout}, using default")
                    self.task_timeout = self._get_default_timeout()
            else:
                # Fall back to config or default
                self.task_timeout = self._get_default_timeout()
        
        self.queue_service = AnalysisQueueService()
        self.running = False
        self.tasks_processed = 0
        self.current_task = None
        self.current_process = None
    
    def _get_default_timeout(self) -> int:
        """Get default timeout from config or hardcoded default."""
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            return DEFAULT_CONFIG.get("analysis_timeout_seconds", 600)
        except Exception:
            return 600
        
    def start(self):
        """Start the worker loop."""
        logger.info(f"Worker {self.worker_id} started (poll_interval={self.poll_interval}s, timeout={self.task_timeout}s)")
        self.running = True
        
        try:
            while self.running:
                # Check if we've reached max tasks
                if self.max_tasks and self.tasks_processed >= self.max_tasks:
                    logger.info(f"Worker {self.worker_id} reached max tasks ({self.max_tasks}), shutting down")
                    break
                
                # Try to get a task from queue
                task_id = self.queue_service.dequeue(self.worker_id)
                
                if task_id:
                    self.current_task = task_id
                    logger.info(f"Worker {self.worker_id} processing task {task_id} (task #{self.tasks_processed + 1})")
                    
                    self._process_task(task_id)
                    self.tasks_processed += 1
                    self.current_task = None
                    self.current_process = None
                else:
                    # No tasks available, wait before polling again
                    logger.debug(f"Worker {self.worker_id} - no tasks, sleeping {self.poll_interval}s")
                    time.sleep(self.poll_interval)
                    
        except KeyboardInterrupt:
            logger.info(f"Worker {self.worker_id} interrupted by user")
        except Exception as e:
            logger.error(f"Worker {self.worker_id} unexpected error: {e}")
        finally:
            self._cleanup()
            logger.info(f"Worker {self.worker_id} stopped. Processed {self.tasks_processed} tasks.")
    
    def _process_task(self, task_id: str):
        """
        Process a single task by spawning a subprocess.

        A ``finally`` safety-net guarantees that the task will never be left
        in RUNNING status when this method returns, regardless of how the
        subprocess exits (success, exception, SIGKILL, timeout).

        Args:
            task_id: The task ID to process
        """
        try:
            # Start subprocess (no pipes to avoid Windows buffer deadlock)
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m", "webapi.subprocess_runner",
                    task_id,
                    self.worker_id,
                ],
            )
            self.current_process = proc

            # Wait for completion with timeout
            proc.wait(timeout=self.task_timeout)

            if proc.returncode != 0:
                # Idempotent: only updates if task is still RUNNING.
                # Covers SIGKILL / crash where subprocess couldn't update DB.
                logger.error(f"Task {task_id} failed with exit code {proc.returncode}")
                self._mark_analysis_task_failed_if_running(
                    task_id, f"Process exited with code {proc.returncode}"
                )
                self.queue_service.mark_failed(
                    task_id, f"Process exited with code {proc.returncode}"
                )
            else:
                logger.info(f"Task {task_id} completed successfully")

        except subprocess.TimeoutExpired:
            logger.error(f"Task {task_id} timed out after {self.task_timeout}s")

            # Kill the subprocess
            if self.current_process:
                try:
                    self.current_process.kill()
                    self.current_process.wait(timeout=5)
                except Exception as e:
                    logger.warning(f"Failed to kill subprocess for task {task_id}: {e}")

            # Mark as failed
            self.queue_service.mark_failed(task_id, f"Timeout after {self.task_timeout}s")
            self._mark_analysis_task_failed_if_running(task_id, f"Timeout after {self.task_timeout}s")

        except Exception as e:
            logger.error(f"Error processing task {task_id}: {e}")
            self.queue_service.mark_failed(task_id, str(e))
            self._mark_analysis_task_failed_if_running(task_id, str(e))

        finally:
            # Safety-net: if the task is still RUNNING after all handlers,
            # something unexpected happened — mark it FAILED to prevent zombies.
            self._mark_analysis_task_failed_if_running(
                task_id, "Worker finished but task still RUNNING — forced fail"
            )
    
    def stop(self):
        """Signal the worker to stop gracefully."""
        logger.info(f"Worker {self.worker_id} received stop signal")
        self.running = False
    
    def _cleanup(self):
        """Cleanup resources."""
        if self.current_process and self.current_process.poll() is None:
            logger.warning(f"Terminating running subprocess for task {self.current_task}")
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=5)
            except Exception as e:
                logger.error(f"Failed to terminate subprocess: {e}")
                try:
                    self.current_process.kill()
                except:
                    pass

    def _mark_analysis_task_failed_if_running(self, task_id: str, error_message: str) -> None:
        """Idempotently mark a task as FAILED **only** if it is still RUNNING.

        Uses ``WHERE status = 'RUNNING'`` to avoid overwriting a status that
        the subprocess (or reconciliation) already finalised.
        """
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            result = db.execute(
                text(
                    """
                    UPDATE analysis_tasks
                    SET status    = 'FAILED',
                        updated_at = :now,
                        completed_at = COALESCE(completed_at, :now),
                        message   = 'Analysis failed in worker',
                        error     = :error
                    WHERE task_id = :task_id
                      AND status  = 'RUNNING'
                    """
                ),
                {"task_id": task_id, "now": now, "error": error_message},
            )
            db.commit()
            if result.rowcount > 0:
                logger.info("Marked task %s as FAILED (was RUNNING): %s", task_id, error_message)
        except Exception:
            db.rollback()
            logger.exception("Failed to mark analysis task %s as failed", task_id)
        finally:
            db.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="TradingAgents Analysis Worker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--worker-id", 
        default=str(uuid.uuid4())[:8],
        help="Unique worker identifier"
    )
    parser.add_argument(
        "--poll-interval", 
        type=float, 
        default=float(os.getenv("WORKER_POLL_INTERVAL", "1.0")),
        help="Queue poll interval in seconds when empty"
    )
    parser.add_argument(
        "--max-tasks", 
        type=int, 
        default=None,
        help="Maximum tasks to process before exiting (default: infinite)"
    )
    parser.add_argument(
        "--task-timeout", 
        type=int, 
        default=600,
        help="Maximum seconds to wait for a task to complete"
    )
    args = parser.parse_args()
    
    worker = AnalysisWorker(
        worker_id=args.worker_id,
        poll_interval=args.poll_interval,
        max_tasks=args.max_tasks,
        task_timeout=args.task_timeout
    )
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        worker.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start worker
    worker.start()


if __name__ == "__main__":
    main()
