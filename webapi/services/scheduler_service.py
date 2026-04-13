"""APScheduler-based watchlist monitoring and turning-point detection."""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportDeprecated=false, reportMissingTypeStubs=false, reportUnusedImport=false, reportUnannotatedClassAttribute=false, reportUnnecessaryIsInstance=false

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

logger = logging.getLogger(__name__)

TRADING_TIMEZONE = "Asia/Shanghai"
HIGH_FREQUENCY_DURATION_MINUTES = 10
DEFAULT_CONFIDENCE_JUMP = 0.15
DEFAULT_STABLE_THRESHOLD = 3
DEFAULT_CONFIDENCE_STABILITY_WINDOW = 0.10

BULLISH_SIGNALS = {"BUY", "OVERWEIGHT"}
BEARISH_SIGNALS = {"SELL", "UNDERWEIGHT"}
NEUTRAL_SIGNALS = {"HOLD"}


def _to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float conversion."""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_signal(raw_signal: Any) -> str:
    """Normalize signal payloads to a stable uppercase decision value.

    Handles:
    - Clean values: "BUY", "买入" → "BUY"
    - Nested dicts with decision/signal keys
    - Noisy LLM output containing <THINK> blocks or long reasoning —
      extracts the trailing BUY/SELL/HOLD if present.
    """
    import re

    if isinstance(raw_signal, dict):
        raw_signal = raw_signal.get("decision") or raw_signal.get("signal")

    if raw_signal is None:
        return "UNKNOWN"

    normalized = str(raw_signal).strip().upper()

    # Direct mapping for clean values
    mapping = {
        "买入": "BUY",
        "增持": "OVERWEIGHT",
        "持有": "HOLD",
        "减持": "UNDERWEIGHT",
        "卖出": "SELL",
        "BUY": "BUY",
        "SELL": "SELL",
        "HOLD": "HOLD",
        "OVERWEIGHT": "OVERWEIGHT",
        "UNDERWEIGHT": "UNDERWEIGHT",
    }

    direct = mapping.get(normalized)
    if direct:
        return direct

    # Fuzzy: check if a known decision word appears in the (possibly long) string
    # Prefer longer matches ("OVERWEIGHT" before "BUY") to avoid false positives
    for key in ("OVERWEIGHT", "UNDERWEIGHT", "BUY", "SELL", "HOLD"):
        if key in normalized:
            return key

    return "UNKNOWN"


def _extract_clean_signal(result: Any) -> str:
    """Extract BUY/SELL/HOLD from noisy analyst output.
    
    Prefers result.decision over nested signal fields.
    Handles Chinese-to-English mapping via _normalize_signal.
    """
    if not isinstance(result, dict):
        return "UNKNOWN"
    
    # Priority 1: Direct decision field
    decision = result.get("decision")
    if decision:
        return _normalize_signal(decision)
    
    # Priority 2: Nested signal.decision
    signal = result.get("signal")
    if isinstance(signal, dict):
        nested_decision = signal.get("decision")
        if nested_decision:
            return _normalize_signal(nested_decision)
        # Also try signal.signal for nested structure
        nested_signal = signal.get("signal")
        if nested_signal:
            return _normalize_signal(nested_signal)
    
    # Priority 3: Direct signal string
    if signal:
        return _normalize_signal(signal)
    
    return "UNKNOWN"


def _normalize_risk_level(raw_risk: Any) -> str:
    """Normalize risk level to low/medium/high."""
    if raw_risk is None:
        return "medium"

    normalized = str(raw_risk).strip().lower()
    mapping = {
        "low": "low",
        "medium": "medium",
        "med": "medium",
        "high": "high",
        "低": "low",
        "中": "medium",
        "高": "high",
    }
    return mapping.get(normalized, "medium")


def _extract_analysis_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten result payloads from AnalysisResponse storage."""
    nested_result = result.get("result")
    payload = nested_result if isinstance(nested_result, dict) else result

    signal = _extract_clean_signal(payload if isinstance(payload, dict) else result)
    confidence = _to_float(
        payload.get("confidence") if isinstance(payload, dict) else result.get("confidence"),
        default=0.0,
    )
    risk_level = _normalize_risk_level(
        (payload.get("risk_level") if isinstance(payload, dict) else None) or result.get("risk_level")
    )
    market_alert = str(
        (payload.get("market_alert") if isinstance(payload, dict) else None)
        or result.get("market_alert")
        or ""
    )
    price = payload.get("price") if isinstance(payload, dict) else result.get("price")

    return {
        "signal": signal,
        "confidence": confidence,
        "risk_level": risk_level,
        "market_alert": market_alert,
        "price": _to_float(price, default=0.0) if price is not None else None,
        "analysis_type": result.get("analysis_type") or (payload.get("analysis_type") if isinstance(payload, dict) else None),
        "status": result.get("status") or (payload.get("status") if isinstance(payload, dict) else None),
        "error": result.get("error") or (payload.get("error") if isinstance(payload, dict) else None),
    }


def _is_signal_reversal(previous_signal: str, current_signal: str, current_confidence: float) -> bool:
    """Check whether a signal transition counts as a turning-point reversal."""
    previous_signal = _normalize_signal(previous_signal)
    current_signal = _normalize_signal(current_signal)

    if previous_signal == current_signal:
        return False

    if previous_signal in BULLISH_SIGNALS and current_signal in BEARISH_SIGNALS:
        return True
    if previous_signal in BEARISH_SIGNALS and current_signal in BULLISH_SIGNALS:
        return True
    if previous_signal in NEUTRAL_SIGNALS and current_signal in BULLISH_SIGNALS.union(BEARISH_SIGNALS):
        return current_confidence > 0.75
    return False


def detect_turning_point(
    current_result: Dict[str, Any],
    previous_result: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, float]:
    """Detect whether the latest AI analysis indicates a turning point."""
    if not current_result or not previous_result:
        return False, "无显著变化", 0.0

    config = config or {}
    confidence_threshold = _to_float(config.get("confidence_jump"), DEFAULT_CONFIDENCE_JUMP)

    current_signal = _normalize_signal(current_result.get("signal"))
    previous_signal = _normalize_signal(previous_result.get("signal"))
    current_conf = _to_float(current_result.get("confidence"))
    previous_conf = _to_float(previous_result.get("confidence"))
    current_risk = _normalize_risk_level(current_result.get("risk_level"))
    previous_risk = _normalize_risk_level(previous_result.get("risk_level"))
    market_alert = str(current_result.get("market_alert") or "")

    turning_signals: List[str] = []
    importance = 0.0

    if _is_signal_reversal(previous_signal, current_signal, current_conf):
        turning_signals.append(f"信号转变: {previous_signal} → {current_signal}")
        importance += 0.9

    conf_jump = current_conf - previous_conf
    if conf_jump >= confidence_threshold and current_conf > 0.8:
        turning_signals.append(f"置信度突破: {previous_conf:.0%} → {current_conf:.0%}")
        importance += 0.6

    risk_levels = {"low": 1, "medium": 2, "high": 3}
    if risk_levels.get(current_risk, 2) != risk_levels.get(previous_risk, 2):
        direction = "风险上升" if risk_levels.get(current_risk, 2) > risk_levels.get(previous_risk, 2) else "风险下降"
        turning_signals.append(f"{direction}: {previous_risk} → {current_risk}")
        importance += 0.4 if direction == "风险上升" else 0.3

    if market_alert and any(keyword in market_alert for keyword in ("异常", "紧急", "熔断", "暴跌", "暴涨")):
        turning_signals.append(f"市场警报: {market_alert}")
        importance += 0.95

    is_turning = importance >= 0.5 or len(turning_signals) >= 2
    reason = " | ".join(turning_signals) if turning_signals else "无显著变化"
    return is_turning, reason, min(importance, 1.0)


def should_use_high_frequency(
    recent_results: List[Dict[str, Any]],
    stable_threshold: int = DEFAULT_STABLE_THRESHOLD,
) -> bool:
    """Return True when high-frequency monitoring should continue."""
    if len(recent_results) < stable_threshold:
        return True

    recent_slice = recent_results[-stable_threshold:]
    recent_signals = [_normalize_signal(item.get("signal")) for item in recent_slice]
    recent_risks = [_normalize_risk_level(item.get("risk_level")) for item in recent_slice]
    recent_confidences = [_to_float(item.get("confidence")) for item in recent_slice]

    signals_stable = len(set(recent_signals)) == 1
    risks_stable = len(set(recent_risks)) == 1
    confs_stable = (max(recent_confidences) - min(recent_confidences)) < DEFAULT_CONFIDENCE_STABILITY_WINDOW

    return not (signals_stable and risks_stable and confs_stable)


def _job_defaults() -> Dict[str, int]:
    """Resolve scheduler cadence, including accelerated test mode."""
    test_mode = str(os.getenv("SCHEDULER_TEST_MODE", "false")).lower() == "true"
    interval_minutes = max(1, int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "1" if test_mode else "5")))
    high_freq_minutes = max(1, int(os.getenv("SCHEDULER_HIGH_FREQUENCY_INTERVAL_MINUTES", "1" if test_mode else "2")))
    return {
        "test_mode": 1 if test_mode else 0,
        "interval_minutes": interval_minutes,
        "high_freq_minutes": high_freq_minutes,
    }


def _recent_analysis_results(db: Any, watchlist_id: int, limit: int = DEFAULT_STABLE_THRESHOLD) -> List[Dict[str, Any]]:
    """Load recent completed analysis results for a watchlist item."""
    from webapi.models.database import WatchlistAnalysis

    analyses = (
        db.query(WatchlistAnalysis)
        .filter(
            WatchlistAnalysis.watchlist_id == watchlist_id,
            WatchlistAnalysis.completed_at.isnot(None),
            WatchlistAnalysis.error_message.is_(None),
        )
        .order_by(WatchlistAnalysis.created_at.desc())
        .limit(limit)
        .all()
    )
    results = []
    for analysis in analyses:
        results.append(
            {
                "signal": analysis.signal,
                "confidence": _to_float(analysis.confidence),
                "risk_level": analysis.risk_level or "medium",
            }
        )
    results.reverse()
    return results


def _schedule_high_frequency_window(watchlist: Any, duration_minutes: int = HIGH_FREQUENCY_DURATION_MINUTES) -> None:
    """Extend the watchlist item's high-frequency window."""
    base_time = watchlist.high_freq_until if watchlist.high_freq_until and watchlist.high_freq_until > datetime.utcnow() else datetime.utcnow()
    watchlist.is_high_frequency = "Y"
    watchlist.high_freq_until = base_time + timedelta(minutes=duration_minutes)


def reconcile_unfinalized_watchlist_analyses(db) -> List[Dict[str, Any]]:
    """Find WA rows with completed_at IS NULL but linked AnalysisTask is COMPLETED.
    
    Uses FOR UPDATE SKIP LOCKED pattern for idempotency.
    Actually finalizes the analyses by calling _finalize_watchlist_analysis.
    
    Returns:
        List of dicts with reconciliation results
    """
    from webapi.models.database import WatchlistAnalysis, AnalysisTask
    from datetime import datetime, timedelta
    
    reconciled = []
    
    # Only process analyses that are at least 5 minutes old
    # (to avoid interfering with in-progress analyses)
    min_age = datetime.utcnow() - timedelta(minutes=5)
    
    # Find orphaned rows with SKIP LOCKED
    result = db.execute(
        text("""
            SELECT wa.id, wa.watchlist_id, at.result, at.task_id
            FROM watchlist_analyses wa
            JOIN analysis_tasks at ON at.task_id = wa.analysis_id
            WHERE wa.completed_at IS NULL
              AND at.status = 'COMPLETED'
              AND at.completed_at IS NOT NULL
              AND wa.created_at < :min_age
            FOR UPDATE OF wa SKIP LOCKED
        """),
        {"min_age": min_age}
    )
    
    rows = result.fetchall()
    
    for row in rows:
        wa_id, watchlist_id, task_result, task_id = row
        
        # Re-fetch with lock to ensure idempotency
        wa = db.query(WatchlistAnalysis).filter(
            WatchlistAnalysis.id == wa_id,
            WatchlistAnalysis.completed_at.is_(None)
        ).with_for_update().first()
        
        if wa:
            try:
                # Actually finalize the analysis with the result data
                _finalize_watchlist_analysis(db, wa, task_result or {})
                reconciled.append({
                    "wa_id": wa_id,
                    "watchlist_id": watchlist_id,
                    "task_id": task_id,
                    "status": "finalized"
                })
                logger.info("[RECONCILE] Finalized WA %d for watchlist %d", wa_id, watchlist_id)
            except Exception as e:
                logger.exception("[RECONCILE] Failed to finalize WA %d: %s", wa_id, str(e))
                reconciled.append({
                    "wa_id": wa_id,
                    "watchlist_id": watchlist_id,
                    "task_id": task_id,
                    "status": "error",
                    "error": str(e)
                })
    
    db.commit()
    return reconciled


def reconcile_expired_hf_flags(db) -> int:
    """Reset is_high_frequency='N' where high_freq_until has passed."""
    result = db.execute(
        text("""
            UPDATE watchlist
            SET is_high_frequency = 'N',
                high_freq_until = NULL
            WHERE is_high_frequency = 'Y'
              AND high_freq_until IS NOT NULL
              AND high_freq_until < CURRENT_TIMESTAMP
        """)
    )

    db.commit()
    count = result.rowcount or 0
    if count > 0:
        logger.info("[RECONCILE] Reset %d expired high-frequency flags", count)
    return count


def _finalize_watchlist_analysis(
    db: Any,
    watchlist_analysis: Any,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist analysis result, turning detection, and notification side effects."""
    from webapi.models.database import Watchlist, WatchlistAnalysis
    from webapi.services.notification_service import format_turning_alert, notification_service

    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_analysis.watchlist_id).first()
    if watchlist is None:
        raise ValueError(f"Watchlist {watchlist_analysis.watchlist_id} not found")

    payload = _extract_analysis_payload(result)
    now = datetime.utcnow()

    previous_analysis = (
        db.query(WatchlistAnalysis)
        .filter(
            WatchlistAnalysis.watchlist_id == watchlist.id,
            WatchlistAnalysis.id != watchlist_analysis.id,
            WatchlistAnalysis.completed_at.isnot(None),
            WatchlistAnalysis.error_message.is_(None),
        )
        .order_by(WatchlistAnalysis.created_at.desc())
        .first()
    )
    previous_result = (
        {
            "signal": previous_analysis.signal,
            "confidence": _to_float(previous_analysis.confidence),
            "risk_level": previous_analysis.risk_level or "medium",
        }
        if previous_analysis
        else None
    )

    current_result = {
        "signal": payload["signal"],
        "confidence": payload["confidence"],
        "risk_level": payload["risk_level"],
        "market_alert": payload["market_alert"],
    }

    detection_enabled = watchlist.turning_detection_enabled == "Y"
    config = {"confidence_jump": _to_float(watchlist.confidence_jump_threshold, DEFAULT_CONFIDENCE_JUMP)}
    is_turning, reason, importance = detect_turning_point(current_result, previous_result, config) if detection_enabled and previous_result else (False, "无显著变化", 0.0)

    watchlist_analysis.completed_at = now
    watchlist_analysis.signal = payload["signal"][:20] if payload["signal"] and len(payload["signal"]) <= 20 else payload["signal"][:17] + "..." if payload["signal"] else None
    watchlist_analysis.confidence = str(payload["confidence"]) if payload["confidence"] or payload["confidence"] == 0 else None
    watchlist_analysis.risk_level = payload["risk_level"]
    watchlist_analysis.price = payload["price"] if payload["price"] is not None else watchlist_analysis.price
    watchlist_analysis.error_message = payload["error"] if payload.get("status") == "error" else None
    watchlist_analysis.is_turning_point = "Y" if is_turning else "N"
    watchlist_analysis.turning_reason = reason if is_turning else None
    watchlist_analysis.importance_score = str(importance) if is_turning else None

    watchlist.last_analysis_at = now
    watchlist.last_signal = payload["signal"][:20] if payload["signal"] and len(payload["signal"]) <= 20 else payload["signal"][:17] + "..." if payload["signal"] else None
    watchlist.last_confidence = str(payload["confidence"]) if payload["confidence"] or payload["confidence"] == 0 else None
    watchlist.last_risk_level = payload["risk_level"]
    if payload["price"] is not None:
        current_price = _to_float(payload["price"], default=0.0)
        # Calculate change percentage from previous price (before overwrite)
        prev_price = _to_float(watchlist.last_price, default=0.0) if watchlist.last_price else 0.0
        watchlist.last_price = str(current_price)
        if prev_price > 0 and current_price > 0:
            change_pct = (current_price - prev_price) / prev_price * 100
            watchlist.last_change_pct = str(round(change_pct, 2))

    if is_turning:
        _schedule_high_frequency_window(watchlist)
        title, message = format_turning_alert(
            watchlist.symbol,
            watchlist.name or watchlist.symbol,
            current_result,
            reason,
            importance,
        )
        delivered = notification_service.send_turning_alert(title, message, importance=importance)
        watchlist_analysis.alert_sent = "Y" if delivered else "N"
        watchlist_analysis.alert_sent_at = now if delivered else None
    else:
        watchlist_analysis.alert_sent = watchlist_analysis.alert_sent or "N"
        watchlist_analysis.alert_sent_at = watchlist_analysis.alert_sent_at

    return {
        "symbol": watchlist.symbol,
        "analysis_id": watchlist_analysis.id,
        "is_turning": is_turning,
        "turning_reason": reason,
        "importance": importance,
        "alert_sent": watchlist_analysis.alert_sent == "Y",
    }


def process_watchlist_analysis_completion(watchlist_analysis_id: int, result: Dict[str, Any]) -> Dict[str, Any]:
    """Public wrapper to finalize a watchlist analysis and update parent watchlist.
    
    This function is called by the API path (async callback) to complete analysis.
    It creates its own database session and handles all cleanup.
    
    Args:
        watchlist_analysis_id: The ID of the WatchlistAnalysis row to finalize
        result: The analysis result dict from AnalysisTask
        
    Returns:
        Dict with status and summary of what was updated
    """
    from webapi.config.database import SessionLocal
    from webapi.models.database import WatchlistAnalysis
    
    db = SessionLocal()
    try:
        # Fetch the watchlist analysis
        watchlist_analysis = db.query(WatchlistAnalysis).filter(
            WatchlistAnalysis.id == watchlist_analysis_id
        ).first()
        
        if watchlist_analysis is None:
            logger.error("[PROCESS] WatchlistAnalysis %d not found", watchlist_analysis_id)
            return {"status": "error", "error": f"WatchlistAnalysis {watchlist_analysis_id} not found"}
        
        # Call the internal finalizer with the session
        summary = _finalize_watchlist_analysis(db, watchlist_analysis, result)
        
        db.commit()
        logger.info("[PROCESS] Finalized watchlist analysis %d: %s", watchlist_analysis_id, summary)
        return {"status": "success", "summary": summary}
        
    except Exception as e:
        db.rollback()
        logger.exception("[PROCESS] Failed to finalize watchlist analysis %d: %s", watchlist_analysis_id, str(e))
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def reconciliation_job() -> Dict[str, Any]:
    """Periodic sweep for stale states across all layers."""
    from webapi.config.database import SessionLocal
    from webapi.services.queue_service import AnalysisQueueService

    logger.info("[RECONCILE-JOB] Starting periodic reconciliation...")

    db = SessionLocal()
    try:
        # Queue layer
        queue_service = AnalysisQueueService()
        stale_queue = queue_service.reconcile_stale_queue_rows(db, 30)
        orphaned_tasks = queue_service.reconcile_orphaned_task_states(db, 30)
        pending_orphans = queue_service.reconcile_pending_orphans(db, 30)

        # Watchlist layer
        unfinalized = reconcile_unfinalized_watchlist_analyses(db)
        expired_hf = reconcile_expired_hf_flags(db)

        summary = {
            "stale_queue_rows": stale_queue,
            "orphaned_tasks": orphaned_tasks,
            "pending_orphans": pending_orphans,
            "unfinalized_analyses": len(unfinalized),
            "expired_hf_flags": expired_hf,
        }

        logger.info("[RECONCILE-JOB] Complete: %s", summary)
        return summary

    except Exception:
        logger.exception("[RECONCILE-JOB] Periodic reconciliation failed")
        return {"error": "reconciliation failed"}
    finally:
        db.close()


def high_frequency_batch_job() -> List[Dict[str, Any]]:
    """Batch-process all watchlist entries currently in high-frequency mode."""
    logger.info("[SCHEDULER] Starting high-frequency batch job")
    from webapi.config.database import SessionLocal
    from webapi.models.database import Watchlist

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        active_watchlists = (
            db.query(Watchlist)
            .filter(
                Watchlist.is_active == "Y",
                Watchlist.is_high_frequency == "Y",
                Watchlist.high_freq_until.isnot(None),
                Watchlist.high_freq_until > now,
            )
            .order_by(Watchlist.id.asc())
            .all()
        )

        expired_watchlists = (
            db.query(Watchlist)
            .filter(
                Watchlist.is_active == "Y",
                Watchlist.is_high_frequency == "Y",
                Watchlist.high_freq_until.isnot(None),
                Watchlist.high_freq_until <= now,
            )
            .all()
        )
        for watchlist in expired_watchlists:
            watchlist.is_high_frequency = "N"
            watchlist.high_freq_until = None
        if expired_watchlists:
            db.commit()
    finally:
        db.close()

    if not active_watchlists:
        logger.info("[SCHEDULER] No stocks currently in high-frequency mode")
        return []

    summaries = _run_watchlist_job_batch(
        analysis_type="turning",
        triggered_by="turning",
        is_quick=True,
        watchlists=active_watchlists,
        timeout=180,
    )

    db = SessionLocal()
    try:
        from webapi.models.database import Watchlist

        for item in active_watchlists:
            watchlist = db.query(Watchlist).filter(Watchlist.id == item.id).first()
            if watchlist is None or watchlist.is_high_frequency != "Y":
                continue
            recent_results = _recent_analysis_results(db, watchlist.id, DEFAULT_STABLE_THRESHOLD)
            if not should_use_high_frequency(recent_results, stable_threshold=DEFAULT_STABLE_THRESHOLD):
                watchlist.is_high_frequency = "N"
                watchlist.high_freq_until = None
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("[SCHEDULER] Failed to evaluate high-frequency deactivation")
    finally:
        db.close()

    return summaries


def full_analysis_job() -> None:
    """Run full analysis on all active watchlist stocks.
    
    This is a placeholder - the actual implementation should:
    1. Query all active watchlist entries
    2. Submit full analysis tasks for each
    3. Handle batching and rate limiting
    """
    logger.info("[SCHEDULER] Running full analysis job (placeholder)")
    # TODO: Implement actual full analysis logic
    pass


def quick_analysis_job() -> None:
    """Run quick market analysis on all active watchlist stocks.
    
    This is a placeholder - the actual implementation should:
    1. Query all active watchlist entries
    2. Submit quick market-only analysis tasks
    3. Handle batching and rate limiting
    """
    logger.info("[SCHEDULER] Running quick analysis job (placeholder)")
    # TODO: Implement actual quick analysis logic
    pass


def _run_watchlist_job_batch(
    analysis_type: str,
    triggered_by: str,
    is_quick: bool,
    watchlists: List[Any],
    timeout: int = 180
) -> List[Dict[str, Any]]:
    """Run a batch of watchlist analyses.
    
    This is a placeholder - the actual implementation should:
    1. Submit analysis tasks for each watchlist
    2. Wait for completion with timeout
    3. Collect and return results
    
    Args:
        analysis_type: Type of analysis ('full', 'quick', 'turning')
        triggered_by: Who triggered it ('scheduled', 'turning', 'manual')
        is_quick: Whether to use quick mode
        watchlists: List of Watchlist objects to analyze
        timeout: Maximum time to wait in seconds
        
    Returns:
        List of result summaries
    """
    logger.info("[SCHEDULER] Running batch job for %d watchlists (placeholder)", len(watchlists))
    # TODO: Implement actual batch processing logic
    return []


class SchedulerService:
    """APScheduler wrapper for watchlist monitoring jobs."""

    def __init__(self) -> None:
        self._scheduler: Optional[BackgroundScheduler] = None
        self._is_running: bool = False

    def _persist_monitoring_state(self, active: bool) -> None:
        """Persist current monitoring state into WatchlistConfig."""
        try:
            from webapi.config.database import SessionLocal
            from webapi.models.database import WatchlistConfig

            db = SessionLocal()
            try:
                WatchlistConfig.set_value(db, "monitoring_active", "true" if active else "false")
                WatchlistConfig.set_value(db, "monitoring_started_at", datetime.utcnow().isoformat() if active else "")
            finally:
                db.close()
        except Exception:
            logger.exception("[SCHEDULER] Failed to persist monitoring state")

    @property
    def is_running(self) -> bool:
        """Return whether the in-process scheduler is active."""
        return self._is_running

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Return scheduler jobs metadata."""
        if not self._scheduler:
            return []
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return jobs

    def trigger_job(self, job_id: str) -> Dict[str, Any]:
        """Run a configured job immediately, regardless of scheduler state."""
        job_handlers = {
            "watchlist_full_analysis": full_analysis_job,
            "watchlist_morning_quick": quick_analysis_job,
            "watchlist_afternoon_quick": quick_analysis_job,
            "watchlist_high_freq_batch": high_frequency_batch_job,
        }
        handler = job_handlers.get(job_id)
        if handler is None:
            return {"job_id": job_id, "found": False, "triggered": False, "results": []}

        results = handler()

        if self._scheduler and self._scheduler.get_job(job_id):
            try:
                job = self._scheduler.get_job(job_id)
                if job is not None:
                    job.modify(next_run_time=datetime.now(self._scheduler.timezone))
            except Exception:
                logger.exception("[SCHEDULER] Failed to refresh next_run_time for %s", job_id)

        return {
            "job_id": job_id,
            "found": True,
            "triggered": True,
            "results": results,
            "triggered_count": len(results),
        }

    def restore_state(self) -> None:
        """Restore persisted monitoring state on API startup."""
        should_start = False
        try:
            from webapi.config.database import SessionLocal
            from webapi.models.database import WatchlistConfig

            db = SessionLocal()
            try:
                monitoring_active = WatchlistConfig.get_value(db, "monitoring_active", "false")
                should_start = str(monitoring_active).lower() == "true"
            finally:
                db.close()
        except Exception:
            logger.exception("[SCHEDULER] Failed to restore persisted monitoring state")
            return

        if should_start and not self._is_running:
            self.start(persist=False)

    def start(self, persist: bool = True) -> None:
        """Start APScheduler and register configured jobs."""
        if self._is_running:
            return

        self._scheduler = BackgroundScheduler(timezone=TRADING_TIMEZONE)
        self._setup_jobs()
        self._scheduler.start()
        self._is_running = True
        if persist:
            self._persist_monitoring_state(True)
        logger.info("[SCHEDULER] Started with %s jobs", len(self.get_jobs()))

    def _setup_jobs(self) -> None:
        """Register watchlist jobs."""
        if self._scheduler is None:
            return

        defaults = _job_defaults()
        if defaults["test_mode"]:
            interval_minutes = defaults["interval_minutes"]
            high_freq_minutes = defaults["high_freq_minutes"]
            self._scheduler.add_job(
                full_analysis_job,
                IntervalTrigger(minutes=interval_minutes, timezone=TRADING_TIMEZONE),
                id="watchlist_full_analysis",
                name=f"Full Analysis (test every {interval_minutes} min)",
                replace_existing=True,
                max_instances=1,
            )
            self._scheduler.add_job(
                quick_analysis_job,
                IntervalTrigger(minutes=interval_minutes, timezone=TRADING_TIMEZONE),
                id="watchlist_morning_quick",
                name=f"Morning Quick Analysis (test every {interval_minutes} min)",
                replace_existing=True,
                max_instances=1,
            )
            self._scheduler.add_job(
                quick_analysis_job,
                IntervalTrigger(minutes=interval_minutes, timezone=TRADING_TIMEZONE),
                id="watchlist_afternoon_quick",
                name=f"Afternoon Quick Analysis (test every {interval_minutes} min)",
                replace_existing=True,
                max_instances=1,
            )
            self._scheduler.add_job(
                high_frequency_batch_job,
                IntervalTrigger(minutes=high_freq_minutes, timezone=TRADING_TIMEZONE),
                id="watchlist_high_freq_batch",
                name=f"High Frequency Batch (test every {high_freq_minutes} min)",
                replace_existing=True,
                max_instances=1,
            )
            return

        self._scheduler.add_job(
            full_analysis_job,
            CronTrigger(hour=2, minute=0, timezone=TRADING_TIMEZONE),
            id="watchlist_full_analysis",
            name="Full Analysis (Daily 02:00)",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            quick_analysis_job,
            CronTrigger(hour=9, minute="20-59/5", day_of_week="mon-fri", timezone=TRADING_TIMEZONE),
            id="watchlist_morning_quick",
            name="Morning Quick Analysis (09:20-09:55)",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            quick_analysis_job,
            CronTrigger(hour=10, minute="*/5", day_of_week="mon-fri", timezone=TRADING_TIMEZONE),
            id="watchlist_morning_quick_10",
            name="Morning Quick Analysis (10:00-10:55)",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            quick_analysis_job,
            CronTrigger(hour=11, minute="0-30/5", day_of_week="mon-fri", timezone=TRADING_TIMEZONE),
            id="watchlist_morning_quick_11",
            name="Morning Quick Analysis (11:00-11:30)",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            quick_analysis_job,
            CronTrigger(hour="13-14", minute="*/5", day_of_week="mon-fri", timezone=TRADING_TIMEZONE),
            id="watchlist_afternoon_quick",
            name="Afternoon Quick Analysis (13:00-14:55)",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            quick_analysis_job,
            CronTrigger(hour=15, minute=0, day_of_week="mon-fri", timezone=TRADING_TIMEZONE),
            id="watchlist_afternoon_quick_close",
            name="Afternoon Quick Analysis (15:00)",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            high_frequency_batch_job,
            IntervalTrigger(minutes=2, timezone=TRADING_TIMEZONE),
            id="watchlist_high_freq_batch",
            name="High Frequency Batch (Every 2 min)",
            replace_existing=True,
            max_instances=1,
        )
        # NEW: Periodic reconciliation job
        self._scheduler.add_job(
            reconciliation_job,
            IntervalTrigger(minutes=5, timezone=TRADING_TIMEZONE),
            id="watchlist_reconciliation",
            name="Watchlist Reconciliation (Every 5 min)",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=60,  # seconds, APScheduler requires int or None
        )

    def stop(self, persist: bool = True) -> None:
        """Stop APScheduler."""
        if self._scheduler is not None and self._is_running:
            self._scheduler.shutdown(wait=False)
        self._scheduler = None
        self._is_running = False
        if persist:
            self._persist_monitoring_state(False)
        logger.info("[SCHEDULER] Stopped")


class WatchlistScheduler(SchedulerService):
    """Backward-compatible alias."""


scheduler_service = SchedulerService()
