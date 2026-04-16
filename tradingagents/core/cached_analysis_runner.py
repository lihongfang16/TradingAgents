# TradingAgents/core/cached_analysis_runner.py
"""Cached wrapper around ``AnalysisRunner`` with analyst report reuse."""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportDeprecated=false, reportUnannotatedClassAttribute=false, reportUnusedImport=false, reportReturnType=false, reportIndexIssue=false, reportCallIssue=false, reportUnusedVariable=false, reportImplicitOverride=false, reportImplicitStringConcatenation=false, reportUnnecessaryIsInstance=false, reportPrivateUsage=false

import logging
import time
import uuid
from datetime import date, datetime
from typing import Any, Callable, Optional

from tradingagents.core.analysis_runner import AnalysisRunner, AGENT_STEPS
from webapi.services.analysis_cache_service import AnalysisCacheService

logger = logging.getLogger(__name__)


class CachedAnalysisRunner(AnalysisRunner):
    """Run analysis with selective analyst-cache injection."""

    CACHED_ANALYST_TYPES: tuple[str, ...] = ("market", "sentiment", "news", "fundamentals")
    ANALYST_TO_STATE_FIELD = {
        "market": "market_report",
        "sentiment": "sentiment_report",
        "social": "sentiment_report",
        "news": "news_report",
        "fundamentals": "fundamentals_report",
    }

    def __init__(
        self,
        symbol: str,
        date: str,
        analysts: list[str],
        llm_model: str,
        llm_provider: str,
        cache_service: AnalysisCacheService,
        initial_cash: float = 100000.0,
        max_iterations: int = 300,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        fast_mode: bool = False,
        cost_price: Optional[float] = None,
        position_shares: Optional[int] = None,
        target_position_pct: Optional[float] = None,
    ):
        """Initialize cached runner."""
        super().__init__(
            symbol=symbol,
            date=date,
            analysts=analysts,
            llm_model=llm_model,
            llm_provider=llm_provider,
            initial_cash=initial_cash,
            max_iterations=max_iterations,
            base_url=base_url,
            api_key=api_key,
            progress_callback=progress_callback,
            fast_mode=fast_mode,
            cost_price=cost_price,
            position_shares=position_shares,
            target_position_pct=target_position_pct,
        )
        self.cache_service: AnalysisCacheService = cache_service
        self._cached_reports: dict[str, str] = {}
        self._acquired_locks: list[tuple[str, str]] = []
        self._initially_cached: set[str] = set()
        self._lock_session_id: str = str(uuid.uuid4())

    def _get_analysis_date(self) -> date:
        """Parse analysis date from string."""
        return datetime.strptime(self.date, "%Y-%m-%d").date()

    def _normalize_analyst(self, analyst: str) -> str:
        """Normalize analyst aliases used by graph selection."""
        return "sentiment" if analyst == "social" else analyst

    def _check_cache(self) -> dict[str, bool]:
        """Load currently valid cached reports for configured analysts."""
        cache_status: dict[str, bool] = {}
        analysis_date = self._get_analysis_date()

        for analyst in self.analysts:
            normalized_analyst = self._normalize_analyst(analyst)
            if normalized_analyst not in self.CACHED_ANALYST_TYPES:
                cache_status[analyst] = False
                continue

            cached_report = self.cache_service.get_cached_report(
                symbol=self.symbol,
                analyst_type=normalized_analyst,
                analysis_date=analysis_date,
            )
            cache_status[analyst] = cached_report is not None
            if cached_report:
                self._cached_reports[normalized_analyst] = cached_report
        self._initially_cached = set(self._cached_reports)
        return cache_status

    def _acquire_concurrent_locks(self) -> None:
        """Acquire locks for uncached analysts or wait for peers to populate cache."""
        analysis_date = self._get_analysis_date()
        for analyst in self.analysts:
            normalized_analyst = self._normalize_analyst(analyst)
            if normalized_analyst in self._cached_reports:
                continue
            if normalized_analyst not in self.CACHED_ANALYST_TYPES:
                continue

            acquired = self.cache_service.acquire_lock(self.symbol, normalized_analyst)
            if acquired:
                self._acquired_locks.append((self.symbol, normalized_analyst))
                continue

            cached_report = self._wait_for_cached_report(
                self.symbol,
                normalized_analyst,
                analysis_date,
                max_wait_seconds=60,
                poll_interval=2,
            )
            if cached_report:
                self._cached_reports[normalized_analyst] = cached_report
            else:
                logger.warning(
                    "Lock wait timed out for %s:%s; proceeding without cache reuse",
                    self.symbol,
                    normalized_analyst,
                )

    def _wait_for_cached_report(
        self,
        symbol: str,
        analyst_type: str,
        analysis_date: date,
        max_wait_seconds: int = 300,
        poll_interval: int = 2,
    ) -> Optional[str]:
        """Poll cache until a peer session writes the requested report."""
        waited = 0
        while waited < max_wait_seconds:
            cached = self.cache_service.get_cached_report(symbol, analyst_type, analysis_date)
            if cached:
                return cached
            time.sleep(poll_interval)
            waited += poll_interval
            if waited % 30 == 0:
                logger.info("Still waiting for %s:%s... (%ss)", symbol, analyst_type, waited)
        return None

    def _release_concurrent_locks(self) -> None:
        """Release all acquired PostgreSQL Advisory Locks."""
        for symbol, analyst_type in self._acquired_locks:
            _ = self.cache_service.release_lock(symbol, analyst_type)
        self._acquired_locks.clear()

    def _inject_cached_reports_into_state(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        """Inject cached analyst outputs into the initial graph state."""
        for analyst_type, report_content in self._cached_reports.items():
            state_field = self.ANALYST_TO_STATE_FIELD.get(analyst_type)
            if state_field:
                initial_state[state_field] = report_content
        return initial_state

    def _save_analyst_reports_to_cache(self, final_state: dict[str, Any], *, force_refresh: bool) -> None:
        """Persist newly-computed analyst reports to cache."""
        analysis_date = self._get_analysis_date()
        for analyst_type in self.CACHED_ANALYST_TYPES:
            if analyst_type not in {self._normalize_analyst(a) for a in self.analysts}:
                continue
            if not force_refresh and analyst_type in self._initially_cached:
                continue
            state_field = self.ANALYST_TO_STATE_FIELD.get(analyst_type)
            if not state_field:
                continue
            report_content = final_state.get(state_field)
            if not report_content:
                continue

            success = self.cache_service.set_cached_report(
                symbol=self.symbol,
                analyst_type=analyst_type,
                analysis_date=analysis_date,
                report_content=str(report_content),
                cache_version=1,
                lock_session_id=self._lock_session_id,
            )
            if not success:
                logger.error("Failed to cache %s report for %s:%s", analyst_type, self.symbol, analysis_date)

    def run(self, force_refresh: bool = False) -> dict[str, Any]:
        """Run analysis with cache injection and optional force refresh."""
        self._cached_reports.clear()
        self._acquired_locks.clear()
        self._initially_cached.clear()
        self._llm_streams.clear()
        self._lock_session_id = str(uuid.uuid4())

        try:
            if not force_refresh:
                cache_status = self._check_cache()
                self._acquire_concurrent_locks()
            else:
                cache_status = {analyst: False for analyst in self.analysts}

            graph_obj = self.graph
            initial_state = graph_obj.propagator.create_initial_state(self.symbol, self.date)
            if self._cached_reports and not force_refresh:
                self._inject_cached_reports_into_state(initial_state)

            result = self._run_with_injected_state(initial_state)
            if result.get("status") == "success" and result.get("final_state"):
                self._save_analyst_reports_to_cache(result["final_state"], force_refresh=force_refresh)

            result["cache_metadata"] = {
                "force_refresh": force_refresh,
                "cached_analysts": list(self._cached_reports.keys()),
                "cache_hit_count": len(self._cached_reports),
                "cache_status": cache_status,
            }
            return result
        except Exception:
            logger.exception("Error in CachedAnalysisRunner.run, falling back to base runner")
            return super().run()
        finally:
            self._release_concurrent_locks()

    def _run_with_injected_state(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        """Execute the LangGraph using a pre-populated initial state."""
        return self._run_graph_with_progress(initial_state=initial_state)
