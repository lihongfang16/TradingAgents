"""
ChinaDataManager - Multi-source failover manager for A-share stocks.
Priority chain: Ashare > AkShare > BaoStock

Provides unified interface across data providers:
- get_kline(): K-line data (daily/weekly/monthly)
- get_realtime_quote(): Real-time quote
- get_fundamental_data(): Fundamental/financial data

Auto-failover: if primary source fails, tries next in chain.
"""

import logging
import re
from typing import Optional, Dict, Any, List

import pandas as pd

from .ashare_provider import AshareProvider
from .akshare_provider import AkShareProvider
from .baostock_provider import BaoStockProvider

logger = logging.getLogger(__name__)


class ChinaDataManager:
    """
    Multi-source data manager for A-share stocks.
    
    Implements priority-based failover across three data providers:
    1. AshareProvider  - Sina + Tencent dual-core (fastest, no install needed)
    2. AkShareProvider - AkShare library (richest data, needs pip install)
    3. BaoStockProvider - BaoStock library (reliable history, needs pip install + login)
    """

    def __init__(self):
        """Initialize providers in priority order."""
        self.providers: List[Any] = [
            AshareProvider(),      # Priority 1: Sina/Tencent (no deps)
            AkShareProvider(),     # Priority 2: AkShare (rich data)
            BaoStockProvider(),    # Priority 3: BaoStock (reliable history)
        ]

    # ── Symbol helpers ──────────────────────────────────────────────

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Normalize symbol to 6-digit format.

        Handles formats like: '000001', '000001.SZ', 'SZ000001',
        'sh000001', 'sz.000001', '1' -> '000001'

        Args:
            symbol: Stock symbol in any common format.

        Returns:
            6-digit symbol string.
        """
        s = str(symbol).strip().upper()

        # Remove exchange suffixes
        for suffix in ('.SZ', '.SH', '.BJ'):
            if s.endswith(suffix):
                s = s[:-3]
                break

        # Remove exchange prefixes (including BaoStock's 'sz.'/'sh.')
        for prefix in ('SZ', 'SH', 'BJ', 'SZ.', 'SH.', 'BJ.'):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break

        # Strip remaining dots (e.g. 'sz.000001' after upper)
        s = s.replace('.', '')

        # Zero-pad to 6 digits
        return s.zfill(6)

    @staticmethod
    def _is_a_share(symbol: str) -> bool:
        """
        Detect whether a symbol is a valid A-share code.

        A-share codes: 6 digits, starting with 0/3/6.
        - 0xxxxx: Shenzhen main board (000xxx, 001xxx, 002xxx, 003xxx)
        - 3xxxxx: ChiNext / 创业板 (300xxx, 301xxx, 303xxx)
        - 6xxxxx: Shanghai main board / STAR (600xxx-605xxx, 688xxx-689xxx)

        Args:
            symbol: Stock symbol (will be normalized internally).

        Returns:
            True if A-share, False otherwise.
        """
        s = str(symbol).strip().upper()
        # Remove exchange prefixes (SH, SZ, BJ)
        for prefix in ("SZ", "SH", "BJ"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        if len(s) < 6:
            s = s.zfill(6)
        return bool(re.fullmatch(r'[03468]\d{5}', s))

    # ── Failover helpers ────────────────────────────────────────────

    def _failover_kline(
        self,
        symbol: str,
        period: str,
        limit: int,
    ) -> Optional[pd.DataFrame]:
        """Try each provider's get_kline() with period/limit normalization."""
        symbol = self._normalize_symbol(symbol)

        # BaoStock uses different param names (frequency, count)
        # We adapt on the fly
        period_map_baostock = {
            'day': 'd', 'daily': 'd',
            'week': 'w', 'weekly': 'w',
            'month': 'm', 'monthly': 'm',
            '1m': '5', '5m': '5', '15m': '15', '30m': '30', '60m': '60',
        }

        for provider in self.providers:
            provider_name = provider.__class__.__name__
            try:
                if isinstance(provider, BaoStockProvider):
                    bs_freq = period_map_baostock.get(period.lower(), 'd')
                    data = provider.get_kline(
                        symbol=symbol,
                        frequency=bs_freq,
                        count=limit,
                        adjustflag="2",  # 前复权
                    )
                else:
                    data = provider.get_kline(symbol, period, limit)

                if data is not None and not data.empty:
                    logger.info(
                        "ChinaDataManager: get_kline(%s) succeeded via %s (%d rows)",
                        symbol, provider_name, len(data),
                    )
                    return data

            except Exception as exc:
                logger.warning(
                    "ChinaDataManager: %s failed for get_kline(%s): %s",
                    provider_name, symbol, exc,
                )
                continue

        logger.error(
            "ChinaDataManager: all providers failed for get_kline(%s)", symbol,
        )
        return None

    def _failover_realtime_quote(
        self,
        symbol: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Try each provider's get_realtime_quote().
        Note: BaoStockProvider does not have get_realtime_quote, skip it.
        """
        symbol = self._normalize_symbol(symbol)

        for provider in self.providers:
            provider_name = provider.__class__.__name__
            # BaoStock has no realtime quote
            if isinstance(provider, BaoStockProvider):
                continue

            try:
                data = provider.get_realtime_quote(symbol)

                if data is not None:
                    logger.info(
                        "ChinaDataManager: get_realtime_quote(%s) succeeded via %s",
                        symbol, provider_name,
                    )
                    return data

            except Exception as exc:
                logger.warning(
                    "ChinaDataManager: %s failed for get_realtime_quote(%s): %s",
                    provider_name, symbol, exc,
                )
                continue

        logger.error(
            "ChinaDataManager: all providers failed for get_realtime_quote(%s)",
            symbol,
        )
        return None

    def _failover_fundamental_data(
        self,
        symbol: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Try each provider's get_fundamental_data().
        BaoStock uses get_stock_basic_info() instead — adapt.
        """
        symbol = self._normalize_symbol(symbol)

        for provider in self.providers:
            provider_name = provider.__class__.__name__
            try:
                if isinstance(provider, BaoStockProvider):
                    data = provider.get_stock_basic_info(symbol)
                else:
                    data = provider.get_fundamental_data(symbol)

                if data is not None:
                    logger.info(
                        "ChinaDataManager: get_fundamental_data(%s) succeeded via %s",
                        symbol, provider_name,
                    )
                    return data

            except Exception as exc:
                logger.warning(
                    "ChinaDataManager: %s failed for get_fundamental_data(%s): %s",
                    provider_name, symbol, exc,
                )
                continue

        logger.error(
            "ChinaDataManager: all providers failed for get_fundamental_data(%s)",
            symbol,
        )
        return None

    # ── Public unified interface ────────────────────────────────────

    def get_kline(
        self,
        symbol: str,
        period: str = "day",
        limit: int = 120,
    ) -> Optional[pd.DataFrame]:
        """
        Get K-line data with automatic failover.

        Args:
            symbol: Stock symbol (e.g. '000001', '600519', '300750').
            period: K-line period — 'day', 'week', 'month', or minute
                    ('1m', '5m', '15m', '30m', '60m'). Default 'day'.
            limit:  Max number of bars to return. Default 120.

        Returns:
            DataFrame with OHLCV columns, or None if all providers fail.
        """
        if not self._is_a_share(symbol):
            logger.warning("ChinaDataManager: %s is not an A-share code, skipping", symbol)
            return None

        return self._failover_kline(symbol, period, limit)

    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote with automatic failover.

        Args:
            symbol: Stock symbol.

        Returns:
            Dict with quote fields (price, change, volume, etc.),
            or None if all providers fail.
        """
        if not self._is_a_share(symbol):
            logger.warning("ChinaDataManager: %s is not an A-share code, skipping", symbol)
            return None

        return self._failover_realtime_quote(symbol)

    def get_fundamental_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get fundamental/financial data with automatic failover.

        Args:
            symbol: Stock symbol.

        Returns:
            Dict with fundamental fields (pe, pb, market_cap, etc.),
            or None if all providers fail.
        """
        if not self._is_a_share(symbol):
            logger.warning("ChinaDataManager: %s is not an A-share code, skipping", symbol)
            return None

        return self._failover_fundamental_data(symbol)
