# TradingAgents WebAPI Services - Incremental Analysis Service
"""
Incremental analysis service that re-runs only changed analysts
while injecting cached results for unchanged ones.

Steps:
1. Verify today's full analysis exists
2. Check for concurrent analysis conflicts
3. Auto-detect changes via ChangeDetector
4. Invalidate cache for changed analysts
5. Run CachedAnalysisRunner (changed recomputed, cached injected)
6. Persist results
7. Return structured response
"""

import logging
import uuid
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from webapi.models.database import (
    AnalysisTask,
    WatchlistAnalysis,
    Watchlist,
)
from webapi.services.analysis_cache_service import AnalysisCacheService

logger = logging.getLogger(__name__)

# All analyst types supported by incremental analysis
ALL_ANALYSTS = ["market", "news", "social", "fundamentals"]

# Mapping from external API names → internal cache/runner names
# The API uses "sentiment" externally, but the cache and runner use "sentiment"
# (the runner also accepts "social" as an alias for "sentiment")
EXTERNAL_TO_INTERNAL = {
    "sentiment": "sentiment",
    "social": "sentiment",
}

# Mapping from internal names back to external API names
INTERNAL_TO_EXTERNAL = {
    "sentiment": "sentiment",
}


class IncrementalAnalysisService:
    """Service for running incremental stock analysis.

    Incremental analysis re-runs only the analysts whose underlying data
    has changed since the last full analysis, injecting cached results
    for the remaining analysts via CachedAnalysisRunner.
    """

    def __init__(self, db_session: Session):
        """Initialize incremental analysis service.

        Args:
            db_session: SQLAlchemy database session for persistence.
        """
        self.db = db_session

    def run_incremental(
        self,
        symbol: str,
        analysis_date: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run incremental analysis for a symbol.

        Args:
            symbol: Stock symbol (e.g., "000001.SZ").
            analysis_date: Analysis date in 'YYYY-MM-DD' format.
            options: Optional dict with overrides:
                - llm_provider: LLM provider name
                - llm_model: LLM model name
                - thresholds: Dict of change-detection thresholds
                - triggered_by: Trigger source (default 'manual')
                - watchlist_id: Watchlist ID for persisting WatchlistAnalysis

        Returns:
            Dict with analysis result, or error dict with status code.
        """
        if options is None:
            options = {}

        # ── Step 1: Check for full analysis today ─────────────────────
        # NOTE: Use range query instead of func.date() to ensure index usage
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        tomorrow_start = datetime.combine(today + timedelta(days=1), datetime.min.time())
        full_today = self.db.query(WatchlistAnalysis).filter(
            WatchlistAnalysis.analysis_type == 'full',
            WatchlistAnalysis.completed_at.isnot(None),
            WatchlistAnalysis.error_message.is_(None),
            WatchlistAnalysis.created_at >= today_start,
            WatchlistAnalysis.created_at < tomorrow_start,
        ).first()

        if not full_today:
            return {"error": "需要先完成今日全量分析"}

        # Get the watchlist_id for this symbol (required for WatchlistAnalysis)
        watchlist_id = options.get("watchlist_id")
        if watchlist_id is None:
            watchlist_entry = self.db.query(Watchlist).filter(
                Watchlist.symbol == symbol,
                Watchlist.is_active == 'Y',
            ).first()
            watchlist_id = watchlist_entry.id if watchlist_entry else None

        # ── Step 2: Check concurrent analysis ─────────────────────────
        running_tasks = self.db.query(AnalysisTask).filter(
            AnalysisTask.symbol == symbol,
            AnalysisTask.status.in_(["RUNNING", "PENDING"]),
        ).first()

        if running_tasks:
            return {"error": "分析正在进行中", "status": 409}

        # ── Step 3: Auto-detect changes ────────────────────────────────
        last_analysis_time = full_today.completed_at
        thresholds = options.get("thresholds", {})

        try:
            from webapi.services.change_detection import ChangeDetector
            detector = ChangeDetector()
            detection_result = detector.auto_detect(
                symbol=symbol,
                last_analysis_time=last_analysis_time,
                thresholds=thresholds,
            )
            # detection_result is Dict[str, bool], filter for True values
            needs_refresh = [k for k, v in detection_result.items() if v]
        except ImportError:
            logger.warning(
                "ChangeDetector not available, treating all analysts as changed"
            )
            needs_refresh = ALL_ANALYSTS.copy()
        except Exception as e:
            logger.error(f"ChangeDetector.auto_detect failed: {e}")
            needs_refresh = ALL_ANALYSTS.copy()

        # Convert external names to internal names for cache/runner
        needs_refresh_internal = []
        for analyst in needs_refresh:
            internal = EXTERNAL_TO_INTERNAL.get(analyst, analyst)
            needs_refresh_internal.append(internal)

        # ── Step 4: Invalidate cache for changed analysts ──────────────
        cache_service = AnalysisCacheService(self.db)
        for analyst_internal in needs_refresh_internal:
            invalidated = cache_service.invalidate_cache(
                symbol=symbol,
                analyst_type=analyst_internal,
            )
            logger.info(
                f"Invalidated {invalidated} cache entries for "
                f"{symbol}:{analyst_internal}"
            )

        # ── Step 5: Run CachedAnalysisRunner with ALL analysts ────────
        from tradingagents.core.cached_analysis_runner import CachedAnalysisRunner
        from tradingagents.default_config import DEFAULT_CONFIG

        llm_provider = options.get("llm_provider", DEFAULT_CONFIG.get("llm_provider", "minimax"))
        llm_model = options.get("llm_model", DEFAULT_CONFIG.get("deep_think_llm", "MiniMax-M2.7-highspeed"))

        task_id = str(uuid.uuid4())

        # Create AnalysisTask record early so callers can poll status
        task = AnalysisTask(
            task_id=task_id,
            symbol=symbol,
            status="RUNNING",
            created_at=datetime.utcnow(),
        )
        self.db.add(task)
        self.db.commit()

        try:
            runner = CachedAnalysisRunner(
                symbol=symbol,
                date=analysis_date,
                analysts=ALL_ANALYSTS,
                llm_model=llm_model,
                llm_provider=llm_provider,
                cache_service=cache_service,
            )
            result = runner.run()

            # ── Step 6: Persist results ───────────────────────────────
            task.status = result.get("status", "completed")
            task.completed_at = datetime.utcnow()
            task.updated_at = datetime.utcnow()
            task.result = result
            task.decision = result.get("signal")
            task.agents_progress = result.get("agents_progress")
            task.current_agent = result.get("current_agent")
            task.progress_pct = result.get("progress_pct")
            task.llm_streams = result.get("llm_streams")

            if result.get("status") == "error":
                task.error = result.get("error")
                task.status = "FAILED"

            self.db.commit()

            # Create WatchlistAnalysis record
            signal = result.get("signal")
            confidence = result.get("confidence")
            price = result.get("price")

            if watchlist_id is not None:
                wa = WatchlistAnalysis(
                    watchlist_id=watchlist_id,
                    analysis_id=task_id,
                    analysis_type="incremental",
                    triggered_by=options.get("triggered_by", "manual"),
                    completed_at=datetime.utcnow() if result.get("status") != "error" else None,
                    signal=signal,
                    confidence=str(confidence) if confidence is not None else None,
                    price=str(price) if price is not None else None,
                    error_message=result.get("error") if result.get("status") == "error" else None,
                )
                self.db.add(wa)

                # Update watchlist last analysis state
                wl = self.db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
                if wl:
                    wl.last_analysis_at = datetime.utcnow()
                    wl.last_signal = signal
                    wl.last_confidence = str(confidence) if confidence is not None else None
                    wl.last_price = str(price) if price is not None else None

                self.db.commit()

            # ── Step 7: Build response ────────────────────────────────
            # Determine which analysts were refreshed vs skipped
            cache_metadata = result.get("cache_metadata", {})
            cached_analysts = set(cache_metadata.get("cached_analysts", []))

            # Convert internal names back to external names for the response
            refresh_external = []
            skipped_external = []
            for analyst in ALL_ANALYSTS:
                internal_name = EXTERNAL_TO_INTERNAL.get(analyst, analyst)
                external_name = INTERNAL_TO_EXTERNAL.get(internal_name, internal_name)
                if internal_name in needs_refresh_internal:
                    refresh_external.append(external_name)
                else:
                    skipped_external.append(external_name)

            return {
                "analysis_type": "incremental",
                "task_id": task_id,
                "refresh_analysts": refresh_external,
                "skipped_analysts": skipped_external,
                "result": result,
            }

        except Exception as e:
            logger.error(f"Incremental analysis failed for {symbol}: {e}", exc_info=True)
            task.status = "FAILED"
            task.error = str(e)
            task.completed_at = datetime.utcnow()
            task.updated_at = datetime.utcnow()
            self.db.commit()

            return {
                "error": str(e),
                "task_id": task_id,
                "status": 500,
            }
