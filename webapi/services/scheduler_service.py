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
    """Normalize signal payloads to a stable uppercase decision value."""
    if isinstance(raw_signal, dict):
        raw_signal = raw_signal.get("decision") or raw_signal.get("signal")

    if raw_signal is None:
        return "UNKNOWN"

    normalized = str(raw_signal).strip().upper()
    mapping = {
        "买入": "BUY",
        "增持": "OVERWEIGHT",
        "持有": "HOLD",
        "减持": "UNDERWEIGHT",
        "卖出": "SELL",
    }
    return mapping.get(normalized, normalized or "UNKNOWN")


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

    signal = _normalize_signal(payload.get("signal") if isinstance(payload, dict) else result.get("signal"))
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
    watchlist_analysis.signal = payload["signal"]
    watchlist_analysis.confidence = str(payload["confidence"]) if payload["confidence"] or payload["confidence"] == 0 else None
    watchlist_analysis.risk_level = payload["risk_level"]
    watchlist_analysis.price = payload["price"] if payload["price"] is not None else watchlist_analysis.price
    watchlist_analysis.error_message = payload["error"] if payload.get("status") == "error" else None
    watchlist_analysis.is_turning_point = "Y" if is_turning else "N"
    watchlist_analysis.turning_reason = reason if is_turning else None
    watchlist_analysis.importance_score = str(importance) if is_turning else None

    watchlist.last_analysis_at = now
    watchlist.last_signal = payload["signal"]
    watchlist.last_confidence = str(payload["confidence"]) if payload["confidence"] or payload["confidence"] == 0 else None
    watchlist.last_risk_level = payload["risk_level"]
    if payload["price"] is not None:
        watchlist.last_price = str(payload["price"])

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
        "watchlist_id": watchlist.id,
        "symbol": watchlist.symbol,
        "is_turning": is_turning,
        "reason": reason,
        "importance": importance,
        "is_high_frequency": watchlist.is_high_frequency == "Y",
        "high_freq_until": watchlist.high_freq_until.isoformat() if watchlist.high_freq_until else None,
    }


def process_watchlist_analysis_completion(
    watchlist_analysis_id: int,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Finalize an existing watchlist analysis row after task completion."""
    from webapi.config.database import SessionLocal
    from webapi.models.database import WatchlistAnalysis

    db = SessionLocal()
    try:
        watchlist_analysis = db.query(WatchlistAnalysis).filter(WatchlistAnalysis.id == watchlist_analysis_id).first()
        if watchlist_analysis is None:
            raise ValueError(f"WatchlistAnalysis {watchlist_analysis_id} not found")

        summary = _finalize_watchlist_analysis(db, watchlist_analysis, result)
        db.commit()
        return summary
    except Exception:
        db.rollback()
        logger.exception("[SCHEDULER] Failed to finalize watchlist analysis %s", watchlist_analysis_id)
        raise
    finally:
        db.close()


def _build_analysis_request(symbol: str, *, is_quick: bool) -> Any:
    """Create a standard analysis request for scheduled jobs."""
    from webapi.models.analysis import AnalysisRequest, StockExchange

    return AnalysisRequest(
        symbol=symbol,
        exchange=StockExchange.CN,
        analysts=["market"] if is_quick else None,
        is_quick=is_quick,
    )


def _create_watchlist_analysis_row(db: Any, watchlist: Any, *, analysis_id: str, analysis_type: str, triggered_by: str) -> Any:
    """Create a persisted WatchlistAnalysis placeholder row."""
    from webapi.models.database import WatchlistAnalysis

    watchlist_analysis = WatchlistAnalysis(
        watchlist_id=watchlist.id,
        analysis_id=analysis_id,
        analysis_type=analysis_type,
        triggered_by=triggered_by,
        created_at=datetime.utcnow(),
    )
    db.add(watchlist_analysis)
    db.commit()
    db.refresh(watchlist_analysis)
    return watchlist_analysis


def _run_watchlist_job_batch(
    *,
    analysis_type: str,
    triggered_by: str,
    is_quick: bool,
    watchlists: Sequence[Any],
    timeout: int,
) -> List[Dict[str, Any]]:
    """Run scheduled analysis for a batch of watchlist items."""
    from webapi.config.database import SessionLocal
    from webapi.services.analysis_service import analysis_service

    db = SessionLocal()
    summaries: List[Dict[str, Any]] = []
    try:
        for watchlist in watchlists:
            try:
                request = _build_analysis_request(watchlist.symbol, is_quick=is_quick)
                task = analysis_service.create_task(request)
                watchlist_analysis = _create_watchlist_analysis_row(
                    db,
                    watchlist,
                    analysis_id=task.task_id,
                    analysis_type=analysis_type,
                    triggered_by=triggered_by,
                )
                analysis_response = analysis_service.run_analysis_sync(
                    task.task_id,
                    request,
                    timeout=timeout,
                    is_quick=is_quick,
                )
                result_payload = analysis_response.result if analysis_response and analysis_response.result else {}
                result_payload.setdefault("analysis_type", analysis_type)
                summaries.append(process_watchlist_analysis_completion(watchlist_analysis.id, result_payload))
            except Exception:
                logger.exception("[SCHEDULER] Failed processing scheduled analysis for %s", watchlist.symbol)
        return summaries
    finally:
        db.close()


def full_analysis_job() -> List[Dict[str, Any]]:
    """Run full overnight analysis across all active watchlist entries."""
    logger.info("[SCHEDULER] Starting full analysis job")
    from webapi.config.database import SessionLocal
    from webapi.models.database import Watchlist

    db = SessionLocal()
    try:
        watchlists = db.query(Watchlist).filter(Watchlist.is_active == "Y").order_by(Watchlist.id.asc()).all()
    finally:
        db.close()

    if not watchlists:
        logger.info("[SCHEDULER] No active watchlist stocks for full analysis")
        return []
    return _run_watchlist_job_batch(
        analysis_type="full",
        triggered_by="scheduled",
        is_quick=False,
        watchlists=watchlists,
        timeout=600,
    )


def quick_analysis_job() -> List[Dict[str, Any]]:
    """Run regular market-hours quick analysis for non-high-frequency items."""
    logger.info("[SCHEDULER] Starting quick analysis job")
    from webapi.config.database import SessionLocal
    from webapi.models.database import Watchlist

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        watchlists = (
            db.query(Watchlist)
            .filter(
                Watchlist.is_active == "Y",
                (Watchlist.is_high_frequency == "N") | (Watchlist.high_freq_until.is_(None)) | (Watchlist.high_freq_until <= now),
            )
            .order_by(Watchlist.id.asc())
            .all()
        )

        expired_high_freq = (
            db.query(Watchlist)
            .filter(
                Watchlist.is_active == "Y",
                Watchlist.is_high_frequency == "Y",
                Watchlist.high_freq_until.isnot(None),
                Watchlist.high_freq_until <= now,
            )
            .all()
        )
        for watchlist in expired_high_freq:
            watchlist.is_high_frequency = "N"
            watchlist.high_freq_until = None
        if expired_high_freq:
            db.commit()
    finally:
        db.close()

    if not watchlists:
        logger.info("[SCHEDULER] No eligible watchlist stocks for regular quick analysis")
        return []
    return _run_watchlist_job_batch(
        analysis_type="quick",
        triggered_by="scheduled",
        is_quick=True,
        watchlists=watchlists,
        timeout=300,
    )


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
