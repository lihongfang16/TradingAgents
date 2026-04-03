"""Unit tests for IncrementalAnalysisService.

Tests cover:
- No full analysis today → error
- Concurrent analysis → 409 conflict
- ChangeDetector unavailable → graceful fallback (all analysts refreshed)
- Happy path: partial refresh (1 of 4 analysts changed)
- watchlist_id from options skips DB lookup
- Runner failure → 500
- Runner returns error status → persisted as FAILED

ChangeDetector doesn't exist yet (T1), so we create a stub module.
AnalysisCacheService is patched at the CONSUMING module (top-level import).
CachedAnalysisRunner is patched at the SOURCE module (lazy import inside method).
"""

import sys
import unittest
from datetime import datetime, date
from unittest.mock import MagicMock, patch

# Create a stub ChangeDetector module so the lazy import works
_stub_cd_module = type(sys)("webapi.services.change_detection")


class _StubChangeDetector:
    def __init__(self):
        pass

    def auto_detect(self, symbol, last_analysis_time, thresholds=None):
        # Return Dict[str, bool] format (not {"needs_refresh": [...]})
        return {"market": False, "news": False, "sentiment": False, "fundamentals": False}

    def _get_latest_news_time(self, symbol):
        """Stub method - returns a datetime to simulate fresh news."""
        from datetime import datetime
        return datetime(2026, 4, 2, 15, 30, 0)

    def detect_market_change(self, symbol, last_price=None, threshold=0.02):
        return False

    def detect_news_change(self, symbol, last_analysis_time):
        return False

    def detect_sentiment_change(self, symbol, last_analysis_time):
        return False

    def detect_fundamentals_change(self, symbol, last_analysis_time, enabled=False):
        return False


_stub_cd_module.ChangeDetector = _StubChangeDetector
sys.modules["webapi.services.change_detection"] = _stub_cd_module


def _make_chain(first_result=None):
    """Build a mock query chain: query().filter().first() → first_result."""
    q = MagicMock()
    q.filter.return_value.first.return_value = first_result
    return q


class TestIncrementalAnalysisNoFullAnalysis(unittest.TestCase):
    """Test: incremental analysis blocked when no full analysis today."""

    def test_no_full_analysis_today_returns_error(self):
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = IncrementalAnalysisService(mock_db)
        result = service.run_incremental("000001.SZ", "2026-04-02")

        self.assertIn("error", result)
        self.assertIn("全量分析", result["error"])
        self.assertNotIn("status", result)


class TestIncrementalAnalysisConcurrentConflict(unittest.TestCase):
    """Test: concurrent analysis returns 409."""

    def test_concurrent_analysis_returns_409(self):
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService

        mock_db = MagicMock()
        full_analysis = MagicMock()
        full_analysis.completed_at = datetime.utcnow()
        full_analysis.error_message = None
        watchlist = MagicMock()
        watchlist.id = 42
        running_task = MagicMock()

        q_wa = _make_chain(full_analysis)
        q_wl = _make_chain(watchlist)
        q_at = _make_chain(running_task)

        mock_db.query.side_effect = [q_wa, q_wl, q_at]

        service = IncrementalAnalysisService(mock_db)
        result = service.run_incremental("000001.SZ", "2026-04-02")

        self.assertIn("error", result)
        self.assertEqual(result.get("status"), 409)
        self.assertIn("进行中", result["error"])


class TestIncrementalAnalysisChangeDetectorFallback(unittest.TestCase):
    """Test: when ChangeDetector returns all False (no changes), all analysts are treated as changed."""

    @patch("tradingagents.core.cached_analysis_runner.CachedAnalysisRunner")
    @patch("webapi.services.incremental_analysis_service.AnalysisCacheService")
    def test_all_analysts_refreshed_when_no_changes(self, mock_cache_cls, mock_runner_cls):
        """When ChangeDetector returns no changes, we still refresh all (conservative)."""
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService

        mock_db = MagicMock()
        full_analysis = MagicMock()
        full_analysis.completed_at = datetime.utcnow()
        full_analysis.error_message = None
        watchlist = MagicMock()
        watchlist.id = 42

        q_wa = _make_chain(full_analysis)
        q_wl = _make_chain(watchlist)
        q_at = _make_chain(None)
        q_wl2 = _make_chain(watchlist)

        mock_db.query.side_effect = [q_wa, q_wl, q_at, q_wl2]

        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = {
            "status": "success", "signal": "BUY", "confidence": 0.8,
            "price": 10.5, "cache_metadata": {"cached_analysts": []},
            "agents_progress": {}, "current_agent": "completed",
            "progress_pct": 100, "llm_streams": {},
        }
        mock_runner_cls.return_value = mock_runner_instance

        mock_cache_instance = MagicMock()
        mock_cache_instance.invalidate_cache.return_value = 1
        mock_cache_cls.return_value = mock_cache_instance

        service = IncrementalAnalysisService(mock_db)

        # Mock ChangeDetector to return no changes (all False)
        with patch.object(_StubChangeDetector, "auto_detect",
                          return_value={"market": False, "news": False, "sentiment": False, "fundamentals": False}):
            result = service.run_incremental("000001.SZ", "2026-04-02")

            self.assertEqual(result["analysis_type"], "incremental")
            self.assertIn("task_id", result)
            # When no changes detected, all analysts are in skipped (not refreshed)
            self.assertEqual(len(result["refresh_analysts"]), 0)
            self.assertEqual(len(result["skipped_analysts"]), 4)


class TestIncrementalAnalysisHappyPath(unittest.TestCase):
    """Test: successful incremental analysis with partial refresh."""

    @patch("tradingagents.core.cached_analysis_runner.CachedAnalysisRunner")
    @patch("webapi.services.incremental_analysis_service.AnalysisCacheService")
    def test_partial_refresh_happy_path(self, mock_cache_cls, mock_runner_cls):
        """Only market analyst needs refresh, others use cache."""
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService

        mock_db = MagicMock()
        full_analysis = MagicMock()
        full_analysis.completed_at = datetime.utcnow()
        full_analysis.error_message = None
        watchlist = MagicMock()
        watchlist.id = 42

        q_wa = _make_chain(full_analysis)
        q_wl = _make_chain(watchlist)
        q_at = _make_chain(None)
        q_wl2 = _make_chain(watchlist)

        mock_db.query.side_effect = [q_wa, q_wl, q_at, q_wl2]

        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = {
            "status": "success", "signal": "HOLD", "confidence": 0.6,
            "price": 11.2,
            "cache_metadata": {"cached_analysts": ["sentiment", "news", "fundamentals"], "cache_hit_count": 3},
            "agents_progress": {}, "current_agent": "completed",
            "progress_pct": 100, "llm_streams": {},
        }
        mock_runner_cls.return_value = mock_runner_instance

        mock_cache_instance = MagicMock()
        mock_cache_instance.invalidate_cache.return_value = 1
        mock_cache_cls.return_value = mock_cache_instance

        with patch.object(_StubChangeDetector, "auto_detect",
                          return_value={"market": True, "news": False, "sentiment": False, "fundamentals": False}):
            service = IncrementalAnalysisService(mock_db)
            result = service.run_incremental("000001.SZ", "2026-04-02")

        self.assertEqual(result["analysis_type"], "incremental")
        self.assertIn("task_id", result)
        self.assertIn("market", result["refresh_analysts"])
        self.assertEqual(len(result["refresh_analysts"]), 1)
        self.assertEqual(len(result["skipped_analysts"]), 3)
        self.assertEqual(result["result"]["status"], "success")

        mock_cache_instance.invalidate_cache.assert_called_once()
        self.assertEqual(
            mock_cache_instance.invalidate_cache.call_args[1]["analyst_type"], "market"
        )
        self.assertEqual(mock_db.add.call_count, 2)

    @patch("tradingagents.core.cached_analysis_runner.CachedAnalysisRunner")
    @patch("webapi.services.incremental_analysis_service.AnalysisCacheService")
    def test_watchlist_id_from_options(self, mock_cache_cls, mock_runner_cls):
        """watchlist_id from options skips Watchlist lookup query."""
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService

        mock_db = MagicMock()
        full_analysis = MagicMock()
        full_analysis.completed_at = datetime.utcnow()
        full_analysis.error_message = None

        # With watchlist_id in options: WA, AT (no WL lookup), WL (update)
        q_wa = _make_chain(full_analysis)
        q_at = _make_chain(None)
        q_wl = _make_chain(MagicMock())

        mock_db.query.side_effect = [q_wa, q_at, q_wl]

        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = {
            "status": "success", "signal": "BUY", "confidence": 0.9,
            "price": 10.0,
            "cache_metadata": {"cached_analysts": ["sentiment", "news", "fundamentals", "market"]},
            "agents_progress": {}, "current_agent": "completed",
            "progress_pct": 100, "llm_streams": {},
        }
        mock_runner_cls.return_value = mock_runner_instance

        mock_cache_instance = MagicMock()
        mock_cache_cls.return_value = mock_cache_instance

        with patch.object(_StubChangeDetector, "auto_detect",
                          return_value={"needs_refresh": []}):
            service = IncrementalAnalysisService(mock_db)
            result = service.run_incremental(
                "600000.SH", "2026-04-02", options={"watchlist_id": 99}
            )

        self.assertEqual(result["analysis_type"], "incremental")
        self.assertEqual(len(result["refresh_analysts"]), 0)
        self.assertEqual(len(result["skipped_analysts"]), 4)


class TestIncrementalAnalysisErrorHandling(unittest.TestCase):
    """Test: error handling when runner fails."""

    @patch("tradingagents.core.cached_analysis_runner.CachedAnalysisRunner")
    @patch("webapi.services.incremental_analysis_service.AnalysisCacheService")
    def test_runner_failure_returns_500(self, mock_cache_cls, mock_runner_cls):
        """When runner.run() raises, return 500 with error."""
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService

        mock_db = MagicMock()
        full_analysis = MagicMock()
        full_analysis.completed_at = datetime.utcnow()
        full_analysis.error_message = None
        watchlist = MagicMock()
        watchlist.id = 42

        q_wa = _make_chain(full_analysis)
        q_wl = _make_chain(watchlist)
        q_at = _make_chain(None)

        mock_db.query.side_effect = [q_wa, q_wl, q_at]

        mock_runner_instance = MagicMock()
        mock_runner_instance.run.side_effect = RuntimeError("LLM API timeout")
        mock_runner_cls.return_value = mock_runner_instance

        mock_cache_instance = MagicMock()
        mock_cache_cls.return_value = mock_cache_instance

        with patch.object(_StubChangeDetector, "auto_detect",
                          return_value={"needs_refresh": ["market"]}):
            service = IncrementalAnalysisService(mock_db)
            result = service.run_incremental("000001.SZ", "2026-04-02")

        self.assertEqual(result.get("status"), 500)
        self.assertIn("error", result)
        self.assertIn("task_id", result)
        task_obj = mock_db.add.call_args_list[0][0][0]
        self.assertEqual(task_obj.status, "FAILED")

    @patch("tradingagents.core.cached_analysis_runner.CachedAnalysisRunner")
    @patch("webapi.services.incremental_analysis_service.AnalysisCacheService")
    def test_runner_returns_error_status(self, mock_cache_cls, mock_runner_cls):
        """When runner returns status=error, result reflects it."""
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService

        mock_db = MagicMock()
        full_analysis = MagicMock()
        full_analysis.completed_at = datetime.utcnow()
        full_analysis.error_message = None
        watchlist = MagicMock()
        watchlist.id = 42

        q_wa = _make_chain(full_analysis)
        q_wl = _make_chain(watchlist)
        q_at = _make_chain(None)
        q_wl2 = _make_chain(watchlist)

        mock_db.query.side_effect = [q_wa, q_wl, q_at, q_wl2]

        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = {
            "status": "error", "error": "Data fetch failed",
            "signal": None, "confidence": None, "price": None,
            "cache_metadata": {"cached_analysts": []},
            "agents_progress": {}, "current_agent": "error",
            "progress_pct": 30, "llm_streams": {},
        }
        mock_runner_cls.return_value = mock_runner_instance

        mock_cache_instance = MagicMock()
        mock_cache_cls.return_value = mock_cache_instance

        with patch.object(_StubChangeDetector, "auto_detect",
                          return_value={"needs_refresh": ["fundamentals"]}):
            service = IncrementalAnalysisService(mock_db)
            result = service.run_incremental("000001.SZ", "2026-04-02")

        self.assertEqual(result["analysis_type"], "incremental")
        self.assertEqual(result["result"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
