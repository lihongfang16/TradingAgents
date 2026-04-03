"""
Change Detection Module for Watchlist Analysis.

Detects whether per-analyst-type data has changed enough to warrant
re-running specific analysts. Used by CachedAnalysisRunner to decide
which analyst reports can be reused from cache.

Analyst types (external naming):
  - "market":       price change detection via ChinaDataManager
  - "news":         news freshness detection via AkShare stock_news_em
  - "sentiment":    derived from news (same trigger)
  - "fundamentals": defaults to False within the same day

Typical usage:
    detector = ChangeDetector()
    changes = detector.auto_detect("000001", last_analysis_time, thresholds)
"""

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# China timezone (UTC+8)
CHINA_TZ = timezone(timedelta(hours=8))

# ── Default thresholds ────────────────────────────────────────────

DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "market": 0.02,       # 2% price change
    "news": True,          # enabled by default
    "sentiment": True,     # derived from news
    "fundamentals": False, # disabled: fundamentals don't change intraday
}

# All supported analyst keys
ANALYST_TYPES = ("market", "news", "sentiment", "fundamentals")


class ChangeDetector:
    """
    Per-analyst-type data change detector.

    Each detection method returns ``True`` when the underlying data has
    changed enough to invalidate the cached analyst report.

    The detector is stateless — all context (symbol, last price, last
    analysis time) is passed in per-call, making it safe for concurrent
    use across multiple analysis sessions.
    """

    def __init__(self) -> None:
        # Lazy-loaded to avoid import-time side effects
        self._china_manager = None

    # ── Lazy accessor for ChinaDataManager ────────────────────────

    @property
    def china_manager(self):
        """Lazy-initialize ChinaDataManager singleton."""
        if self._china_manager is None:
            from tradingagents.dataflows.china_data_manager import ChinaDataManager
            self._china_manager = ChinaDataManager()
        return self._china_manager

    # ── Market analyst: price change detection ────────────────────

    def detect_market_change(
        self,
        symbol: str,
        last_price: Optional[float],
        threshold: float = 0.02,
    ) -> bool:
        """
        Detect whether price has changed beyond threshold.

        Args:
            symbol:      Stock symbol (e.g. '000001').
            last_price:  Previously cached price. If None, always
                         return True (first detection).
            threshold:   Fractional change threshold (default 0.02 = 2%).

        Returns:
            True if price change exceeds threshold, False otherwise.
            Returns False if the stock is suspended (停牌) or price
            data is unavailable.
        """
        current_price = self._get_current_price(symbol)

        if current_price is None:
            # No realtime data available — could be suspended or
            # outside market hours. Don't trigger re-analysis.
            logger.debug("ChangeDetector: no current price for %s, skipping market change", symbol)
            return False

        if last_price is None:
            # No baseline — first time, report change so analysis runs
            logger.debug("ChangeDetector: no last price for %s, reporting change", symbol)
            return True

        if current_price == 0:
            # Zero price likely means suspended stock
            logger.debug("ChangeDetector: current price is 0 for %s (suspended?), skipping", symbol)
            return False

        change_pct = abs(current_price - last_price) / last_price
        changed = change_pct > threshold

        logger.debug(
            "ChangeDetector[market] %s: current=%.4f last=%.4f change=%.4f%% threshold=%.4f%% changed=%s",
            symbol, current_price, last_price, change_pct * 100, threshold * 100, changed,
        )
        return changed

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Fetch current price using ChinaDataManager failover chain.

        Tries realtime quote first, falls back to latest kline close.

        Args:
            symbol: Stock symbol.

        Returns:
            Current price as float, or None if unavailable.
        """
        # Strategy 1: realtime quote
        try:
            quote = self.china_manager.get_realtime_quote(symbol)
            if quote is not None:
                price = quote.get("price")
                if price is not None:
                    return float(price)
        except Exception as exc:
            logger.warning("ChangeDetector: get_realtime_quote failed for %s: %s", symbol, exc)

        # Strategy 2: latest kline close
        try:
            kline = self.china_manager.get_kline(symbol, "day", 1)
            if kline is not None and not kline.empty:
                # Try common column names
                for col in ("close", "收盘", "Close"):
                    if col in kline.columns:
                        return float(kline[col].iloc[-1])
        except Exception as exc:
            logger.warning("ChangeDetector: get_kline fallback failed for %s: %s", symbol, exc)

        return None

    # ── News analyst: news freshness detection ────────────────────

    def detect_news_change(
        self,
        symbol: str,
        last_analysis_time: Optional[datetime],
    ) -> bool:
        """
        Detect whether new news has been published since last analysis.

        Uses AkShare ``stock_news_em`` to fetch latest news and compares
        timestamps. If the API fails, returns False (safe default).

        Args:
            symbol:              Stock symbol.
            last_analysis_time:  When the last analysis was run. If None,
                                 always return True.

        Returns:
            True if new news is available, False otherwise.
        """
        if last_analysis_time is None:
            logger.debug("ChangeDetector[news] %s: no last_analysis_time, reporting change", symbol)
            return True

        latest_news_time = self._get_latest_news_time(symbol)

        if latest_news_time is None:
            # API failed — don't trigger re-analysis
            logger.debug("ChangeDetector[news] %s: no news data available, skipping", symbol)
            return False

        # Ensure last_analysis_time is timezone-aware (UTC)
        if last_analysis_time.tzinfo is None:
            last_analysis_time = last_analysis_time.replace(tzinfo=timezone.utc)

        changed = latest_news_time > last_analysis_time

        logger.debug(
            "ChangeDetector[news] %s: latest=%s last=%s changed=%s",
            symbol, latest_news_time, last_analysis_time, changed,
        )
        return changed

    def _get_latest_news_time(self, symbol: str) -> Optional[datetime]:
        """
        Fetch latest news timestamp from AkShare.

        Args:
            symbol: Stock symbol.

        Returns:
            Datetime of the latest news article, or None if unavailable.
        """
        try:
            import akshare as ak
            df = ak.stock_news_em(symbol=symbol)

            if df is None or df.empty:
                return None

            # Get the most recent news timestamp
            # AkShare stock_news_em returns columns: '发布时间', '标题', '内容', '来源', '链接'
            time_col = "发布时间"
            if time_col not in df.columns:
                # Fallback: try common alternatives
                for col in ("datetime", "time", "publish_time", "新闻时间"):
                    if col in df.columns:
                        time_col = col
                        break
                else:
                    logger.debug("ChangeDetector: no time column found in news data for %s", symbol)
                    return None

            raw_time = df[time_col].iloc[0]

            # Parse the time string — AkShare typically returns format like
            # "2026-04-02 10:30:00" or "2026-04-02 10:30"
            # AkShare returns China local time (UTC+8), need to convert to UTC
            if isinstance(raw_time, datetime):
                # If naive, assume China time; if aware, convert to UTC
                if raw_time.tzinfo is None:
                    raw_time = raw_time.replace(tzinfo=CHINA_TZ)
                return raw_time.astimezone(timezone.utc)

            if isinstance(raw_time, str):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(raw_time.strip(), fmt)
                        # Assume China local time, convert to UTC
                        return dt.replace(tzinfo=CHINA_TZ).astimezone(timezone.utc)
                    except ValueError:
                        continue

            return None

        except Exception as exc:
            logger.warning("ChangeDetector: stock_news_em failed for %s: %s", symbol, exc)
            return None

    # ── Sentiment analyst: derived from news ──────────────────────

    def detect_sentiment_change(
        self,
        symbol: str,
        last_analysis_time: Optional[datetime],
    ) -> bool:
        """
        Detect sentiment change — derived from news freshness.

        Sentiment is driven by the same news data, so the detection
        logic is identical to news change detection.

        Args:
            symbol:              Stock symbol.
            last_analysis_time:  When the last analysis was run.

        Returns:
            True if new news is available (sentiment may have changed).
        """
        return self.detect_news_change(symbol, last_analysis_time)

    # ── Fundamentals analyst: defaults to no change intraday ──────

    def detect_fundamentals_change(
        self,
        symbol: str,
        last_analysis_time: Optional[datetime],
        enabled: bool = False,
    ) -> bool:
        """
        Detect fundamentals data change.

        By default, fundamentals are considered static within a trading
        day (financial reports are published after market close or on
        specific disclosure dates).

        Args:
            symbol:              Stock symbol (reserved for future use).
            last_analysis_time:  Last analysis timestamp.
            enabled:              If False, always returns False.

        Returns:
            False by default. Returns True only if explicitly enabled
            and data version has changed (future implementation).
        """
        if not enabled:
            return False

        # Future: could compare against financial report disclosure dates
        # or cache version timestamps. For now, fundamentals are always
        # considered unchanged within the same day.
        return False

    # ── Dispatcher: auto_detect ──────────────────────────────────

    def auto_detect(
        self,
        symbol: str,
        last_analysis_time: Optional[datetime],
        last_price: Optional[float] = None,
        thresholds: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """
        Run all change detectors with configurable thresholds.

        Args:
            symbol:              Stock symbol.
            last_analysis_time:  When the last analysis was completed.
            last_price:          Previously cached price (for market detection).
            thresholds:          Override default thresholds. Keys:
                                 "market" → float (fractional, e.g. 0.02),
                                 "news" → bool,
                                 "sentiment" → bool,
                                 "fundamentals" → bool.

        Returns:
            Dict mapping analyst type to whether data has changed:
            ``{"market": True, "news": False, "sentiment": False, "fundamentals": False}``
        """
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS.copy()

        return {
            "market": self.detect_market_change(
                symbol,
                last_price,
                threshold=float(thresholds.get("market", 0.02)),
            ),
            "news": (
                self.detect_news_change(symbol, last_analysis_time)
                if thresholds.get("news", True)
                else False
            ),
            "sentiment": (
                self.detect_sentiment_change(symbol, last_analysis_time)
                if thresholds.get("sentiment", True)
                else False
            ),
            "fundamentals": self.detect_fundamentals_change(
                symbol,
                last_analysis_time,
                enabled=bool(thresholds.get("fundamentals", False)),
            ),
        }

    # ── Dispatcher: manual_detect ────────────────────────────────

    def manual_detect(
        self,
        symbol: str,
        selected_analysts: List[str],
        last_analysis_time: Optional[datetime] = None,
        last_price: Optional[float] = None,
        thresholds: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """
        Run change detection only for selected analyst types.

        Useful when the caller wants to force re-check specific analysts
        (e.g., user explicitly requested market re-analysis).

        Args:
            symbol:              Stock symbol.
            selected_analysts:   List of analyst types to check
                                 (e.g. ["market", "news"]).
            last_analysis_time:  When the last analysis was completed.
            last_price:          Previously cached price.
            thresholds:          Optional threshold overrides.

        Returns:
            Dict mapping selected analyst types to change status.
            Unselected analysts are not included.
        """
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS.copy()

        # Validate input — ignore unknown analyst types
        valid_analysts = {a for a in selected_analysts if a in ANALYST_TYPES}
        invalid = set(selected_analysts) - valid_analysts
        if invalid:
            logger.warning(
                "ChangeDetector: ignoring unknown analyst types: %s", invalid,
            )

        results: Dict[str, bool] = {}

        if "market" in valid_analysts:
            results["market"] = self.detect_market_change(
                symbol, last_price,
                threshold=float(thresholds.get("market", 0.02)),
            )

        if "news" in valid_analysts:
            results["news"] = (
                self.detect_news_change(symbol, last_analysis_time)
                if thresholds.get("news", True)
                else False
            )

        if "sentiment" in valid_analysts:
            results["sentiment"] = (
                self.detect_sentiment_change(symbol, last_analysis_time)
                if thresholds.get("sentiment", True)
                else False
            )

        if "fundamentals" in valid_analysts:
            results["fundamentals"] = self.detect_fundamentals_change(
                symbol, last_analysis_time,
                enabled=bool(thresholds.get("fundamentals", False)),
            )

        return results
