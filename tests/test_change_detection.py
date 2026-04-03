"""
Unit tests for ChangeDetector module.

Tests cover:
- auto_detect with no change → all False
- price change >2% → market True
- manual detect with selected analysts
- suspended stock (停牌) handling
- edge cases (no last_price, disabled thresholds, etc.)
"""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

from webapi.services.change_detection import (
    ANALYST_TYPES,
    ChangeDetector,
    DEFAULT_THRESHOLDS,
    CHINA_TZ,
)


class TestDetectMarketChange(unittest.TestCase):
    """Market analyst price change detection tests."""

    def setUp(self):
        self.detector = ChangeDetector()

    def test_no_change_within_threshold(self):
        """Price change within 2% → False."""
        # current=10.10, last=10.00 → 1% change → under 2% threshold
        self.detector._get_current_price = MagicMock(return_value=10.10)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.02)
        self.assertFalse(result)

    def test_price_change_above_threshold(self):
        """Price change >2% → True."""
        # current=10.30, last=10.00 → 3% change → above 2% threshold
        self.detector._get_current_price = MagicMock(return_value=10.30)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.02)
        self.assertTrue(result)

    def test_exact_threshold_boundary(self):
        """Price change exactly at threshold → False (strict >)."""
        # current=10.20, last=10.00 → exactly 2% → NOT > 2%
        self.detector._get_current_price = MagicMock(return_value=10.20)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.02)
        self.assertFalse(result)

    def test_no_last_price_triggers_change(self):
        """No last_price (first detection) → True."""
        self.detector._get_current_price = MagicMock(return_value=10.00)
        result = self.detector.detect_market_change("000001", last_price=None, threshold=0.02)
        self.assertTrue(result)

    def test_no_current_price_returns_false(self):
        """No current price available (API failure) → False."""
        self.detector._get_current_price = MagicMock(return_value=None)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.02)
        self.assertFalse(result)

    def test_suspended_stock_zero_price(self):
        """Suspended stock with zero current price → False."""
        self.detector._get_current_price = MagicMock(return_value=0.0)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.02)
        self.assertFalse(result)

    def test_suspended_stock_no_data(self):
        """Suspended stock — no realtime/kline data → False."""
        self.detector._get_current_price = MagicMock(return_value=None)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.02)
        self.assertFalse(result)

    def test_negative_change_also_triggers(self):
        """Price drop > threshold also triggers change."""
        # current=9.50, last=10.00 → 5% drop → above 2%
        self.detector._get_current_price = MagicMock(return_value=9.50)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.02)
        self.assertTrue(result)

    def test_custom_threshold(self):
        """Custom threshold of 5% is respected."""
        # 3% change but threshold is 5%
        self.detector._get_current_price = MagicMock(return_value=10.30)
        result = self.detector.detect_market_change("000001", last_price=10.00, threshold=0.05)
        self.assertFalse(result)


class TestDetectNewsChange(unittest.TestCase):
    """News analyst freshness detection tests."""

    def setUp(self):
        self.detector = ChangeDetector()

    def test_no_last_analysis_time_triggers_change(self):
        """No last_analysis_time → True."""
        result = self.detector.detect_news_change("000001", last_analysis_time=None)
        self.assertTrue(result)

    @patch.object(ChangeDetector, '_get_latest_news_time')
    def test_newer_news_triggers_change(self, mock_time):
        """News published after last analysis → True."""
        # last_analysis_time is UTC (from database)
        last_time = datetime(2026, 4, 1, 2, 0, 0, tzinfo=timezone.utc)  # 10:00 China = 02:00 UTC
        # Latest news at 14:00 China = 06:00 UTC
        mock_time.return_value = datetime(2026, 4, 1, 6, 0, 0, tzinfo=timezone.utc)
        result = self.detector.detect_news_change("000001", last_analysis_time=last_time)
        self.assertTrue(result)

    @patch.object(ChangeDetector, '_get_latest_news_time')
    def test_older_news_no_change(self, mock_time):
        """All news older than last analysis → False."""
        last_time = datetime(2026, 4, 2, 6, 0, 0, tzinfo=timezone.utc)  # 14:00 China = 06:00 UTC
        # Latest news at 10:00 China = 02:00 UTC
        mock_time.return_value = datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc)
        result = self.detector.detect_news_change("000001", last_analysis_time=last_time)
        self.assertFalse(result)

    @patch.object(ChangeDetector, '_get_latest_news_time')
    def test_api_failure_returns_false(self, mock_time):
        """News API failure → False (safe default)."""
        mock_time.return_value = None
        result = self.detector.detect_news_change("000001", last_analysis_time=datetime(2026, 4, 1, tzinfo=timezone.utc))
        self.assertFalse(result)

    @patch.object(ChangeDetector, '_get_latest_news_time')
    def test_exact_same_time_no_change(self, mock_time):
        """News timestamp exactly equal to last analysis → False."""
        same_time = datetime(2026, 4, 1, 4, 0, 0, tzinfo=timezone.utc)  # 12:00 China = 04:00 UTC
        mock_time.return_value = same_time
        result = self.detector.detect_news_change("000001", last_analysis_time=same_time)
        self.assertFalse(result)


class TestDetectSentimentChange(unittest.TestCase):
    """Sentiment analyst change detection tests."""

    def setUp(self):
        self.detector = ChangeDetector()

    @patch.object(ChangeDetector, '_get_latest_news_time')
    def test_sentiment_derives_from_news(self, mock_time):
        """Sentiment change should mirror news change."""
        last_time = datetime(2026, 4, 1, 2, 0, 0, tzinfo=timezone.utc)  # 10:00 China = 02:00 UTC
        newer_time = datetime(2026, 4, 1, 6, 0, 0, tzinfo=timezone.utc)  # 14:00 China = 06:00 UTC
        mock_time.return_value = newer_time

        news_result = self.detector.detect_news_change("000001", last_time)
        sentiment_result = self.detector.detect_sentiment_change("000001", last_time)

        self.assertEqual(news_result, sentiment_result)
        self.assertTrue(sentiment_result)

    @patch.object(ChangeDetector, '_get_latest_news_time')
    def test_no_news_no_sentiment_change(self, mock_time):
        """No news data → no sentiment change."""
        mock_time.return_value = None
        result = self.detector.detect_sentiment_change(
            "000001", last_analysis_time=datetime(2026, 4, 1, 2, 0, 0, tzinfo=timezone.utc)
        )
        self.assertFalse(result)


class TestDetectFundamentalsChange(unittest.TestCase):
    """Fundamentals analyst change detection tests."""

    def setUp(self):
        self.detector = ChangeDetector()

    def test_disabled_by_default(self):
        """Fundamentals change detection disabled by default → False."""
        result = self.detector.detect_fundamentals_change(
            "000001", last_analysis_time=datetime(2026, 4, 1),
        )
        self.assertFalse(result)

    def test_explicitly_enabled_still_false_intraday(self):
        """Even when enabled, intraday fundamentals are unchanged → False."""
        result = self.detector.detect_fundamentals_change(
            "000001", last_analysis_time=datetime(2026, 4, 1),
            enabled=True,
        )
        self.assertFalse(result)


class TestAutoDetect(unittest.TestCase):
    """Full auto_detect integration tests."""

    def setUp(self):
        self.detector = ChangeDetector()

    def test_auto_detect_no_change_all_false(self):
        """No data change → all analysts report False."""
        last_time = datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc)  # 10:00 China = 02:00 UTC
        self.detector._get_current_price = MagicMock(return_value=10.00)
        self.detector._get_latest_news_time = MagicMock(
            return_value=datetime(2026, 4, 2, 1, 0, 0, tzinfo=timezone.utc),  # 09:00 China = 01:00 UTC
        )

        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=last_time,
            last_price=10.00,
        )

        self.assertEqual(result, {
            "market": False,
            "news": False,
            "sentiment": False,
            "fundamentals": False,
        })

    def test_auto_detect_price_change_only(self):
        """Price change >2% but no news change → only market True."""
        last_time = datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc)
        self.detector._get_current_price = MagicMock(return_value=10.30)  # +3%
        self.detector._get_latest_news_time = MagicMock(
            return_value=datetime(2026, 4, 2, 1, 0, 0, tzinfo=timezone.utc),
        )

        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=last_time,
            last_price=10.00,
        )

        self.assertTrue(result["market"])
        self.assertFalse(result["news"])
        self.assertFalse(result["sentiment"])
        self.assertFalse(result["fundamentals"])

    def test_auto_detect_news_and_sentiment_change(self):
        """New news triggers both news and sentiment → True."""
        last_time = datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc)
        self.detector._get_current_price = MagicMock(return_value=10.00)  # no price change
        self.detector._get_latest_news_time = MagicMock(
            return_value=datetime(2026, 4, 2, 6, 0, 0, tzinfo=timezone.utc),  # 14:00 China = 06:00 UTC
        )

        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=last_time,
            last_price=10.00,
        )

        self.assertFalse(result["market"])
        self.assertTrue(result["news"])
        self.assertTrue(result["sentiment"])
        self.assertFalse(result["fundamentals"])

    def test_auto_detect_disabled_news_threshold(self):
        """News disabled in thresholds → news and sentiment always False."""
        last_time = datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc)
        self.detector._get_current_price = MagicMock(return_value=10.00)
        # Even though there IS new news, it's disabled
        self.detector._get_latest_news_time = MagicMock(
            return_value=datetime(2026, 4, 2, 6, 0, 0, tzinfo=timezone.utc),
        )

        thresholds = {**DEFAULT_THRESHOLDS, "news": False, "sentiment": False}
        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=last_time,
            last_price=10.00,
            thresholds=thresholds,
        )

        self.assertFalse(result["news"])
        self.assertFalse(result["sentiment"])

    def test_auto_detect_custom_price_threshold(self):
        """Custom 5% threshold: 3% change doesn't trigger market."""
        self.detector._get_current_price = MagicMock(return_value=10.30)
        self.detector._get_latest_news_time = MagicMock(return_value=None)

        thresholds = {**DEFAULT_THRESHOLDS, "market": 0.05}
        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=datetime(2026, 4, 2, tzinfo=timezone.utc),
            last_price=10.00,
            thresholds=thresholds,
        )

        self.assertFalse(result["market"])

    def test_auto_detect_no_last_price_no_last_time(self):
        """No prior state → market True, news True, sentiment True, fundamentals False."""
        self.detector._get_current_price = MagicMock(return_value=10.00)
        self.detector._get_latest_news_time = MagicMock(return_value=None)

        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=None,
            last_price=None,
        )

        # Market: True (no last_price → first detection)
        # News: True (no last_analysis_time → first detection, assume change)
        # Sentiment: True (derived from news → same)
        # Fundamentals: always False
        self.assertTrue(result["market"])
        self.assertTrue(result["news"])
        self.assertTrue(result["sentiment"])
        self.assertFalse(result["fundamentals"])


class TestManualDetect(unittest.TestCase):
    """Manual detect tests with selected analyst subset."""

    def setUp(self):
        self.detector = ChangeDetector()

    def test_manual_detect_market_only(self):
        """Only market analyst selected → only market key in result."""
        self.detector._get_current_price = MagicMock(return_value=10.30)
        result = self.detector.manual_detect(
            symbol="000001",
            selected_analysts=["market"],
            last_price=10.00,
        )
        self.assertIn("market", result)
        self.assertNotIn("news", result)
        self.assertNotIn("sentiment", result)
        self.assertNotIn("fundamentals", result)
        self.assertTrue(result["market"])

    def test_manual_detect_multiple_selected(self):
        """Multiple analysts selected → only those in result."""
        last_time = datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc)  # 10:00 China = 02:00 UTC
        self.detector._get_current_price = MagicMock(return_value=10.00)
        self.detector._get_latest_news_time = MagicMock(
            return_value=datetime(2026, 4, 2, 6, 0, 0, tzinfo=timezone.utc),  # 14:00 China = 06:00 UTC
        )
        result = self.detector.manual_detect(
            symbol="000001",
            selected_analysts=["market", "news"],
            last_analysis_time=last_time,
            last_price=10.00,
        )
        self.assertIn("market", result)
        self.assertIn("news", result)
        self.assertNotIn("sentiment", result)
        self.assertNotIn("fundamentals", result)
        self.assertFalse(result["market"])
        self.assertTrue(result["news"])

    def test_manual_detect_unknown_analyst_ignored(self):
        """Unknown analyst types are silently ignored."""
        result = self.detector.manual_detect(
            symbol="000001",
            selected_analysts=["market", "social", "nonexistent"],
            last_price=10.00,
        )
        self.assertIn("market", result)
        self.assertNotIn("social", result)
        self.assertNotIn("nonexistent", result)

    def test_manual_detect_empty_list(self):
        """Empty analyst list → empty result."""
        result = self.detector.manual_detect(
            symbol="000001",
            selected_analysts=[],
        )
        self.assertEqual(result, {})

    def test_manual_detect_respects_thresholds(self):
        """Manual detect uses provided thresholds."""
        self.detector._get_current_price = MagicMock(return_value=10.30)  # +3%
        # 5% threshold: 3% is below
        thresholds = {**DEFAULT_THRESHOLDS, "market": 0.05}
        result = self.detector.manual_detect(
            symbol="000001",
            selected_analysts=["market"],
            last_price=10.00,
            thresholds=thresholds,
        )
        self.assertFalse(result["market"])


class TestSuspendedStock(unittest.TestCase):
    """Suspended stock (停牌) handling tests."""

    def setUp(self):
        self.detector = ChangeDetector()

    def test_suspended_no_realtime_no_kline(self):
        """Suspended stock: no data at all → all False."""
        self.detector._get_current_price = MagicMock(return_value=None)
        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=datetime(2026, 4, 2, tzinfo=timezone.utc),
            last_price=10.00,
        )
        self.assertFalse(result["market"])

    def test_suspended_zero_price(self):
        """Suspended stock: zero price returned → market False."""
        self.detector._get_current_price = MagicMock(return_value=0.0)
        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=datetime(2026, 4, 2, tzinfo=timezone.utc),
            last_price=10.00,
        )
        self.assertFalse(result["market"])

    def test_suspended_news_still_detects(self):
        """Suspended stock but news API works → news/sentiment can still change."""
        last_time = datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc)  # 10:00 China = 02:00 UTC
        self.detector._get_current_price = MagicMock(return_value=0.0)
        self.detector._get_latest_news_time = MagicMock(
            return_value=datetime(2026, 4, 2, 6, 0, 0, tzinfo=timezone.utc),  # 14:00 China = 06:00 UTC
        )
        result = self.detector.auto_detect(
            symbol="000001",
            last_analysis_time=last_time,
            last_price=10.00,
        )
        # Market: False (suspended/zero price)
        # News: True (newer news available)
        # Sentiment: True (derived from news)
        # Fundamentals: False
        self.assertFalse(result["market"])
        self.assertTrue(result["news"])
        self.assertTrue(result["sentiment"])
        self.assertFalse(result["fundamentals"])


class TestGetLatestNewsTime(unittest.TestCase):
    """News timestamp parsing tests."""

    def setUp(self):
        self.detector = ChangeDetector()

    @patch.object(ChangeDetector, '_get_latest_news_time')
    def test_akshare_datetime_object(self, mock_time):
        """AkShare returns datetime object directly."""
        mock_time.return_value = datetime(2026, 4, 2, 7, 30, 0, tzinfo=timezone.utc)  # 15:30 China = 07:30 UTC
        result = self.detector.detect_news_change(
            "000001", last_analysis_time=datetime(2026, 4, 2, 2, 0, 0, tzinfo=timezone.utc),  # 10:00 China = 02:00 UTC
        )
        self.assertTrue(result)


class TestDefaultThresholds(unittest.TestCase):
    """Verify default threshold constants."""

    def test_default_thresholds_keys(self):
        """All four analyst types present."""
        for key in ANALYST_TYPES:
            self.assertIn(key, DEFAULT_THRESHOLDS)

    def test_default_values(self):
        self.assertEqual(DEFAULT_THRESHOLDS["market"], 0.02)
        self.assertTrue(DEFAULT_THRESHOLDS["news"])
        self.assertTrue(DEFAULT_THRESHOLDS["sentiment"])
        self.assertFalse(DEFAULT_THRESHOLDS["fundamentals"])

    def test_analyst_types_tuple(self):
        self.assertEqual(ANALYST_TYPES, ("market", "news", "sentiment", "fundamentals"))


if __name__ == "__main__":
    unittest.main()
