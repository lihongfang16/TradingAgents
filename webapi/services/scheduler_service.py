# TradingAgents WebAPI Services - Scheduler Service
"""
APScheduler-based scheduler service for watchlist monitoring.

Schedules and executes:
- Full analysis job (daily at 02:00)
- Morning quick analysis (9:20-11:30, every 5 minutes on weekdays)
- Afternoon quick analysis (13:00-14:55, every 5 minutes on weekdays)
- High-frequency batch job (every 2 minutes for stocks in high-frequency mode)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Turning Detection Algorithm
# ------------------------------------------------------------------

def detect_turning_point(
    current_result: Dict[str, Any],
    previous_result: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None
) -> tuple:
    """
    Detect turning points based on AI analysis results comparison.

    Args:
        current_result: Current analysis result dict with signal, confidence, risk_level
        previous_result: Previous analysis result dict
        config: Optional config with confidence_jump threshold (default 0.15)

    Returns:
        (is_turning: bool, reason: str, importance_score: float)
    """
    if not current_result or not previous_result:
        return False, "", 0.0

    config = config or {}
    confidence_threshold = config.get('confidence_jump', 0.15)

    current_signal = current_result.get('signal', 'UNKNOWN')
    previous_signal = previous_result.get('signal', 'UNKNOWN')
    current_conf = current_result.get('confidence', 0)
    previous_conf = previous_result.get('confidence', 0)
    current_risk = current_result.get('risk_level', 'medium')
    previous_risk = previous_result.get('risk_level', 'medium')

    turning_signals: List[str] = []
    importance = 0.0

    # 1. Signal change detection (most important)
    if current_signal != previous_signal and current_signal in ['BUY', 'SELL']:
        if previous_signal in ['SELL', 'BUY'] or (previous_signal == 'HOLD' and current_conf > 0.75):
            turning_signals.append(f"信号转变: {previous_signal} → {current_signal}")
            importance += 0.9

    # 2. Confidence jump detection
    conf_jump = current_conf - previous_conf
    if conf_jump >= confidence_threshold and current_conf > 0.8:
        turning_signals.append(f"置信度突破: {previous_conf:.0%} → {current_conf:.0%}")
        importance += 0.6

    # 3. Risk level change detection
    risk_levels = {'low': 1, 'medium': 2, 'high': 3}
    if risk_levels.get(current_risk, 2) != risk_levels.get(previous_risk, 2):
        if risk_levels.get(current_risk, 2) > risk_levels.get(previous_risk, 2):
            turning_signals.append(f"风险上升: {previous_risk} → {current_risk}")
            importance += 0.4
        else:
            turning_signals.append(f"风险下降: {previous_risk} → {current_risk}")
            importance += 0.3

    # 4. Emergency signal detection (market anomaly)
    market_alert = current_result.get('market_alert', '')
    if market_alert and '异常' in market_alert:
        turning_signals.append(f"市场警报: {market_alert}")
        importance += 0.95

    #综合判定
    is_turning = importance >= 0.5 or len(turning_signals) >= 2

    reason = " | ".join(turning_signals) if turning_signals else "无显著变化"

    return is_turning, reason, min(importance, 1.0)


def should_use_high_frequency(
    recent_results: List[Dict[str, Any]],
    stable_threshold: int = 3
) -> bool:
    """
    Determine whether to continue high-frequency analysis mode.

    Logic:
    - If recent N results are consistent (stable), return to low frequency
    - Otherwise continue high frequency
    """
    if len(recent_results) < stable_threshold:
        return True  # Insufficient data, continue high frequency

    recent_signals = [r.get('signal') for r in recent_results[-stable_threshold:]]
    recent_confs = [r.get('confidence', 0) for r in recent_results[-stable_threshold:]]

    # Signals consistent and confidence stable (change < 10%)
    signals_stable = len(set(recent_signals)) == 1
    confs_stable = max(recent_confs) - min(recent_confs) < 0.1

    return not (signals_stable and confs_stable)


# ------------------------------------------------------------------
# Scheduled Job Functions
# ------------------------------------------------------------------

def full_analysis_job():
    """
    Full analysis job - runs at 02:00 daily.
    Performs deep analysis of all active watchlist stocks.
    """
    logger.info("[SCHEDULER] Starting full analysis job")
    try:
        from webapi.services.analysis_service import analysis_service
        from webapi.models.database import SessionLocal, Watchlist

        db = SessionLocal()
        try:
            # Get all active watchlist stocks
            watchlists = db.query(Watchlist).filter(
                Watchlist.is_active == True
            ).all()

            if not watchlists:
                logger.info("[SCHEDULER] No active watchlist stocks for full analysis")
                return

            symbols = [w.symbol for w in watchlists]
            logger.info(f"[SCHEDULER] Full analysis for {len(symbols)} stocks: {symbols}")

            # Run batch analysis (async in background)
            from webapi.models.analysis import BatchAnalysisRequest
            request = BatchAnalysisRequest(symbols=symbols)

            # Create event loop for async call
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                batch_response = loop.run_until_complete(
                    analysis_service.run_batch(request)
                )
                logger.info(f"[SCHEDULER] Full analysis batch started: {batch_response.batch_id}")
            finally:
                loop.close()

        finally:
            db.close()
    except Exception as e:
        logger.error(f"[SCHEDULER] Full analysis job failed: {e}", exc_info=True)


def quick_analysis_job():
    """
    Quick analysis job - runs during trading hours (9:20-11:30, 13:00-15:00).
    Performs fast-mode analysis of all active watchlist stocks.
    """
    logger.info("[SCHEDULER] Starting quick analysis job")
    try:
        from webapi.services.analysis_service import analysis_service
        from webapi.models.database import SessionLocal, Watchlist

        db = SessionLocal()
        try:
            # Get all active watchlist stocks (not in high-frequency mode for regular quick analysis)
            watchlists = db.query(Watchlist).filter(
                Watchlist.is_active == True,
                Watchlist.is_high_frequency == False
            ).all()

            if not watchlists:
                logger.info("[SCHEDULER] No stocks for quick analysis (all may be in high-frequency mode)")
                return

            symbols = [w.symbol for w in watchlists]
            logger.info(f"[SCHEDULER] Quick analysis for {len(symbols)} stocks: {symbols}")

            # Run batch analysis
            from webapi.models.analysis import BatchAnalysisRequest
            request = BatchAnalysisRequest(symbols=symbols)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                batch_response = loop.run_until_complete(
                    analysis_service.run_batch(request)
                )
                logger.info(f"[SCHEDULER] Quick analysis batch started: {batch_response.batch_id}")
            finally:
                loop.close()

        finally:
            db.close()
    except Exception as e:
        logger.error(f"[SCHEDULER] Quick analysis job failed: {e}", exc_info=True)


def high_frequency_batch_job():
    """
    High-frequency batch job - runs every 2 minutes.
    Processes all stocks currently in high-frequency mode.
    After processing, checks if they should return to normal frequency.
    """
    logger.info("[SCHEDULER] Starting high-frequency batch job")
    try:
        from webapi.services.analysis_service import analysis_service
        from webapi.models.database import SessionLocal, Watchlist

        db = SessionLocal()
        try:
            # Get all stocks in high-frequency mode that haven't expired
            now = datetime.utcnow()
            watchlists = db.query(Watchlist).filter(
                Watchlist.is_active == True,
                Watchlist.is_high_frequency == True,
                Watchlist.high_freq_until > now
            ).all()

            if not watchlists:
                logger.info("[SCHEDULER] No stocks in high-frequency mode")
                return

            symbols = [w.symbol for w in watchlists]
            logger.info(f"[SCHEDULER] High-frequency analysis for {len(symbols)} stocks: {symbols}")

            # Run batch analysis
            from webapi.models.analysis import BatchAnalysisRequest
            request = BatchAnalysisRequest(symbols=symbols)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                batch_response = loop.run_until_complete(
                    analysis_service.run_batch(request)
                )
                logger.info(f"[SCHEDULER] High-frequency batch started: {batch_response.batch_id}")

                # After analysis, check if we should deactivate high-frequency mode
                _check_and_deactivate_high_frequency(db, watchlists)

            finally:
                loop.close()

        finally:
            db.close()
    except Exception as e:
        logger.error(f"[SCHEDULER] High-frequency batch job failed: {e}", exc_info=True)


def _check_and_deactivate_high_frequency(db, watchlists):
    """
    Check recent analysis results and deactivate high-frequency mode if signals are stable.
    """
    try:
        from webapi.models.database import WatchlistAnalysis

        for watchlist in watchlists:
            # Get recent analysis results for this watchlist
            recent_analyses = db.query(WatchlistAnalysis).filter(
                WatchlistAnalysis.watchlist_id == watchlist.id
            ).order_by(WatchlistAnalysis.created_at.desc()).limit(3).all()

            if len(recent_analyses) < 3:
                continue

            recent_results = []
            for analysis in recent_analyses:
                if analysis.signal and analysis.confidence:
                    recent_results.append({
                        'signal': analysis.signal,
                        'confidence': analysis.confidence,
                        'risk_level': analysis.risk_level or 'medium'
                    })

            if len(recent_results) >= 3:
                # Check if should return to normal frequency
                if not should_use_high_frequency(recent_results, stable_threshold=3):
                    watchlist.is_high_frequency = False
                    watchlist.high_freq_until = None
                    logger.info(f"[SCHEDULER] Deactivated high-frequency mode for {watchlist.symbol} - signals stable")
                    break  # Process one at a time

        db.commit()
    except Exception as e:
        logger.error(f"[SCHEDULER] Error checking high-frequency deactivation: {e}")
        db.rollback()


def on_analysis_complete(watchlist_id: int, result: Dict[str, Any]):
    """
    Callback executed after each analysis completes.
    Performs turning detection and triggers notifications/high-frequency mode.

    Args:
        watchlist_id: ID of the watchlist stock
        result: Analysis result dict with signal, confidence, risk_level
    """
    try:
        from webapi.models.database import SessionLocal, Watchlist, WatchlistAnalysis

        db = SessionLocal()
        try:
            watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
            if not watchlist:
                return

            # Get previous analysis result
            previous_analysis = db.query(WatchlistAnalysis).filter(
                WatchlistAnalysis.watchlist_id == watchlist_id
            ).order_by(WatchlistAnalysis.created_at.desc()).first()

            previous_result = None
            if previous_analysis:
                previous_result = {
                    'signal': previous_analysis.signal or 'UNKNOWN',
                    'confidence': previous_analysis.confidence or 0,
                    'risk_level': previous_analysis.risk_level or 'medium',
                    'market_alert': ''
                }

            # Perform turning detection
            current_result = {
                'signal': result.get('signal', 'UNKNOWN'),
                'confidence': result.get('confidence', 0),
                'risk_level': result.get('risk_level', 'medium'),
                'market_alert': result.get('market_alert', '')
            }

            config = {
                'confidence_jump': watchlist.confidence_jump_threshold or 0.15
            }

            is_turning, reason, importance = detect_turning_point(
                current_result, previous_result, config
            )

            # Create analysis record
            now = datetime.utcnow()
            analysis_record = WatchlistAnalysis(
                watchlist_id=watchlist_id,
                analysis_id=result.get('task_id', ''),
                analysis_type=result.get('analysis_type', 'quick'),
                triggered_by='scheduled',
                created_at=now,
                completed_at=now,
                signal=current_result['signal'],
                confidence=current_result['confidence'],
                risk_level=current_result['risk_level'],
                is_turning_point=is_turning,
                turning_reason=reason if is_turning else None,
                importance_score=importance if is_turning else 0,
            )
            db.add(analysis_record)

            # Update watchlist with latest analysis info
            watchlist.last_analysis_at = now
            watchlist.last_signal = current_result['signal']
            watchlist.last_confidence = current_result['confidence']
            watchlist.last_risk_level = current_result['risk_level']

            if is_turning:
                # Activate high-frequency mode
                watchlist.is_high_frequency = True
                watchlist.high_freq_until = datetime.utcnow()  # Will be set properly

                # Mark alert as not sent yet
                analysis_record.alert_sent = False

                # Send desktop notification (try import to avoid circular dependency)
                try:
                    from webapi.services.notification_service import notification_service, format_turning_alert
                    title, message = format_turning_alert(
                        watchlist.symbol,
                        watchlist.name or watchlist.symbol,
                        current_result,
                        reason,
                        importance
                    )
                    notification_service.send_turning_alert(title, message)
                except ImportError:
                    logger.warning("[SCHEDULER] Notification service not available")

                logger.info(f"[SCHEDULER] Turning point detected for {watchlist.symbol}: {reason}")

            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[SCHEDULER] Error in on_analysis_complete: {e}", exc_info=True)


# ------------------------------------------------------------------
# Scheduler Service
# ------------------------------------------------------------------

class SchedulerService:
    """
    APScheduler-based scheduler service for watchlist monitoring.

    Manages scheduled jobs for:
    - Full analysis (daily 02:00)
    - Morning quick analysis (9:20-11:30 weekdays)
    - Afternoon quick analysis (13:00-14:55 weekdays)
    - High-frequency batch (every 2 minutes)
    """

    def __init__(self):
        self._scheduler: Optional[BackgroundScheduler] = None
        self._is_running = False

    def _persist_monitoring_state(self, active: bool) -> None:
        """Persist scheduler monitoring state to watchlist configuration."""
        try:
            from webapi.config.database import SessionLocal
            from webapi.models.database import WatchlistConfig

            db = SessionLocal()
            try:
                WatchlistConfig.set_value(db, "monitoring_active", "true" if active else "false")
                WatchlistConfig.set_value(
                    db,
                    "monitoring_started_at",
                    datetime.utcnow().isoformat() if active else "",
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to persist monitoring state: {e}", exc_info=True)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get list of all scheduled jobs."""
        if not self._scheduler:
            return []
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in self._scheduler.get_jobs()
        ]

    def trigger_job(self, job_id: str) -> bool:
        """
        Manually trigger a scheduled job by ID.

        Args:
            job_id: ID of the job to trigger

        Returns:
            True if job was found and triggered, False otherwise
        """
        if not self._scheduler:
            return False

        try:
            job = self._scheduler.get_job(job_id)
            if job:
                job.modify(next_run_time=datetime.utcnow())
                self._scheduler.print_jobs()
                return True
        except Exception as e:
            logger.error(f"[SCHEDULER] Error triggering job {job_id}: {e}")
        return False

    def restore_state(self) -> None:
        """
        Restore scheduler state from persistent watchlist configuration.

        Auto-starts scheduler when `monitoring_active` is stored as true.
        """
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
        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to restore monitoring state: {e}", exc_info=True)
            return

        if should_start and not self._is_running:
            logger.info("[SCHEDULER] Restoring persisted active monitoring state")
            self.start(persist=False)

    def start(self, persist: bool = True):
        """Start the scheduler with all configured jobs."""
        if self._is_running:
            logger.warning("[SCHEDULER] Scheduler already running")
            return

        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._setup_jobs()
        self._scheduler.start()
        self._is_running = True
        if persist:
            self._persist_monitoring_state(active=True)
        logger.info("[SCHEDULER] Scheduler started successfully")

    def _setup_jobs(self):
        """Configure all scheduled jobs."""
        if not self._scheduler:
            return

        # Full analysis job - daily at 02:00
        self._scheduler.add_job(
            full_analysis_job,
            CronTrigger(hour=2, minute=0, timezone="Asia/Shanghai"),
            id="watchlist_full_analysis",
            name="Full Analysis (Daily 02:00)",
            replace_existing=True,
        )
        logger.info("[SCHEDULER] Added job: watchlist_full_analysis (daily 02:00)")

        # Morning quick analysis - 9:20-11:30, every 5 minutes on weekdays
        self._scheduler.add_job(
            quick_analysis_job,
            CronTrigger(
                hour="9-11",
                minute="20,25,30,35,40,45,50,55",
                day_of_week="mon-fri",
                timezone="Asia/Shanghai",
            ),
            id="watchlist_morning_quick",
            name="Morning Quick Analysis (9:20-11:55)",
            replace_existing=True,
        )
        logger.info("[SCHEDULER] Added job: watchlist_morning_quick (9:20-11:55 weekdays)")

        # Afternoon quick analysis - 13:00-14:55, every 5 minutes on weekdays
        self._scheduler.add_job(
            quick_analysis_job,
            CronTrigger(
                hour="13-14",
                minute="0,5,10,15,20,25,30,35,40,45,50,55",
                day_of_week="mon-fri",
                timezone="Asia/Shanghai",
            ),
            id="watchlist_afternoon_quick",
            name="Afternoon Quick Analysis (13:00-14:55)",
            replace_existing=True,
        )
        logger.info("[SCHEDULER] Added job: watchlist_afternoon_quick (13:00-14:55 weekdays)")

        # High-frequency batch job - every 2 minutes
        self._scheduler.add_job(
            high_frequency_batch_job,
            IntervalTrigger(minutes=2),
            id="watchlist_high_freq_batch",
            name="High Frequency Batch (Every 2 min)",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("[SCHEDULER] Added job: watchlist_high_freq_batch (every 2 min)")

    def stop(self, persist: bool = True):
        """Stop the scheduler."""
        if not self._is_running or not self._scheduler:
            if persist:
                self._persist_monitoring_state(active=False)
            return

        self._scheduler.shutdown(wait=False)
        self._is_running = False
        if persist:
            self._persist_monitoring_state(active=False)
        logger.info("[SCHEDULER] Scheduler stopped")

    def print_status(self):
        """Print current scheduler status and jobs."""
        if not self._scheduler:
            logger.info("[SCHEDULER] Scheduler not initialized")
            return

        logger.info(f"[SCHEDULER] Status: {'Running' if self._is_running else 'Stopped'}")
        logger.info(f"[SCHEDULER] Jobs count: {len(self._scheduler.get_jobs())}")
        self._scheduler.print_jobs()


class WatchlistScheduler(SchedulerService):
    """Backward-compatible alias for the watchlist scheduler service."""


# Global singleton instance
scheduler_service = SchedulerService()


if __name__ == "__main__":
    # Test script - run scheduler standalone
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print("Starting Scheduler Service (standalone mode)...")
    scheduler_service.start()

    try:
        # Keep running
        import time
        while True:
            time.sleep(60)
            scheduler_service.print_status()
    except KeyboardInterrupt:
        print("Shutting down...")
        scheduler_service.stop()
