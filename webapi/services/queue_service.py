"""PostgreSQL-backed queue operations for analysis workers."""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportDeprecated=false, reportReturnType=false

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import func, text

from webapi.config.database import SessionLocal
from webapi.models.database import AnalysisQueue

logger = logging.getLogger(__name__)


class AnalysisQueueService:
    """CRUD and worker-safe operations for the analysis queue."""

    def enqueue(
        self,
        task_id: str,
        request_payload: Dict[str, Any],
        *,
        priority: int = 0,
        max_retries: int = 3,
    ) -> bool:
        """Persist a task in the queue if it is not already active."""
        db = SessionLocal()
        try:
            existing = db.query(AnalysisQueue).filter(AnalysisQueue.task_id == task_id).first()
            if existing is not None:
                if existing.status in {"QUEUED", "PROCESSING"}:
                    logger.info("Task %s already queued with status %s", task_id, existing.status)
                    return False

                db.delete(existing)
                db.flush()

            queue_item = AnalysisQueue(
                task_id=task_id,
                status="QUEUED",
                priority=priority,
                retry_count=0,
                max_retries=max_retries,
                request_payload=request_payload,
                created_at=datetime.utcnow(),
                started_at=None,
                completed_at=None,
                worker_id=None,
                error_message=None,
            )
            db.add(queue_item)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def dequeue(self, worker_id: str) -> Optional[str]:
        """Atomically claim the next queued task using SKIP LOCKED."""
        db = SessionLocal()
        try:
            result = db.execute(
                text(
                    """
                    UPDATE analysis_queue
                    SET status = 'PROCESSING',
                        worker_id = :worker_id,
                        started_at = CURRENT_TIMESTAMP,
                        completed_at = NULL,
                        error_message = NULL
                    WHERE id = (
                        SELECT id
                        FROM analysis_queue
                        WHERE status = 'QUEUED'
                        ORDER BY priority DESC, created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING task_id;
                    """
                ),
                {"worker_id": worker_id},
            )
            row = result.fetchone()
            db.commit()
            return row[0] if row else None
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_request_payload(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the persisted request payload for a queued task."""
        db = SessionLocal()
        try:
            queue_item = db.query(AnalysisQueue).filter(AnalysisQueue.task_id == task_id).first()
            return queue_item.request_payload if queue_item else None
        finally:
            db.close()

    def mark_processing(self, task_id: str, worker_id: str) -> bool:
        """Refresh processing metadata for a claimed task."""
        return self._update_status(
            task_id,
            "PROCESSING",
            worker_id=worker_id,
            started_at=datetime.utcnow(),
            completed_at=None,
            error_message=None,
        )

    def mark_completed(self, task_id: str) -> bool:
        """Mark a task as completed in the queue."""
        return self._update_status(
            task_id,
            "COMPLETED",
            completed_at=datetime.utcnow(),
            error_message=None,
        )

    def mark_failed(self, task_id: str, error_message: str) -> bool:
        """Mark a task as failed in the queue."""
        return self._update_status(
            task_id,
            "FAILED",
            completed_at=datetime.utcnow(),
            error_message=error_message,
        )

    def cancel(self, task_id: str, message: str = "Task cancelled") -> bool:
        """Cancel a queued or processing task in the queue."""
        return self._update_status(
            task_id,
            "FAILED",
            completed_at=datetime.utcnow(),
            error_message=message,
        )

    def requeue_failed(self, *, max_retries: Optional[int] = None, stale_timeout_minutes: int = 30) -> int:
        """Requeue failed tasks and stale processing tasks that are still retryable."""
        db = SessionLocal()
        try:
            retry_limit_expr = "COALESCE(:max_retries, max_retries)"
            stale_cutoff = datetime.utcnow() - timedelta(minutes=stale_timeout_minutes)

            failed_result = db.execute(
                text(
                    f"""
                    UPDATE analysis_queue
                    SET status = 'QUEUED',
                        retry_count = retry_count + 1,
                        worker_id = NULL,
                        started_at = NULL,
                        completed_at = NULL,
                        error_message = NULL
                    WHERE status = 'FAILED'
                      AND retry_count < {retry_limit_expr};
                    """
                ),
                {"max_retries": max_retries},
            )

            stale_result = db.execute(
                text(
                    f"""
                    UPDATE analysis_queue
                    SET status = 'QUEUED',
                        retry_count = retry_count + 1,
                        worker_id = NULL,
                        started_at = NULL,
                        completed_at = NULL,
                        error_message = 'Worker timeout - task reset'
                    WHERE status = 'PROCESSING'
                      AND started_at IS NOT NULL
                      AND started_at < :stale_cutoff
                      AND retry_count < {retry_limit_expr};
                    """
                ),
                {"max_retries": max_retries, "stale_cutoff": stale_cutoff},
            )

            db.commit()
            return (failed_result.rowcount or 0) + (stale_result.rowcount or 0)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_queue_stats(self) -> Dict[str, Any]:
        """Return counts and simple latency visibility for queue monitoring."""
        db = SessionLocal()
        try:
            grouped = db.query(
                AnalysisQueue.status,
                func.count(AnalysisQueue.id),
            ).group_by(AnalysisQueue.status).all()

            stats: Dict[str, Any] = {status: count for status, count in grouped}
            for status in ["QUEUED", "PROCESSING", "COMPLETED", "FAILED"]:
                stats.setdefault(status, 0)

            oldest_queued = db.query(func.min(AnalysisQueue.created_at)).filter(
                AnalysisQueue.status == "QUEUED"
            ).scalar()
            stats["oldest_queued_seconds"] = (
                int((datetime.utcnow() - oldest_queued).total_seconds()) if oldest_queued else 0
            )
            return stats
        finally:
            db.close()

    def purge_completed(self, older_than_days: int = 7) -> int:
        """Delete old completed or failed queue entries."""
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(days=older_than_days)
            deleted = db.query(AnalysisQueue).filter(
                AnalysisQueue.status.in_(["COMPLETED", "FAILED"]),
                AnalysisQueue.completed_at.is_not(None),
                AnalysisQueue.completed_at < cutoff,
            ).delete(synchronize_session=False)
            db.commit()
            return deleted
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _update_status(
        self,
        task_id: str,
        status: str,
        *,
        worker_id: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update a queue row in place."""
        db = SessionLocal()
        try:
            queue_item = db.query(AnalysisQueue).filter(AnalysisQueue.task_id == task_id).first()
            if queue_item is None:
                return False

            queue_item.status = status
            if worker_id is not None:
                queue_item.worker_id = worker_id
            if started_at is not None or status == "PROCESSING":
                queue_item.started_at = started_at
            if completed_at is not None or status in {"COMPLETED", "FAILED"}:
                queue_item.completed_at = completed_at or datetime.utcnow()
            if error_message is not None:
                queue_item.error_message = error_message
            elif status in {"QUEUED", "PROCESSING", "COMPLETED"}:
                queue_item.error_message = None

            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
