"""
FinancialDataAdapter — Standalone AkShare financial data adapter.

Provides per-instance caching and Chinese→English column name mapping for
A-share financial statements (income, balance sheet, cash flow) and key metrics.

Designed to be shared across multiple persona agents in a single analysis run,
avoiding duplicate AkShare API calls via a simple dict cache keyed by
(method_name, symbol).
"""

from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import pandas as pd

import logging

logger = logging.getLogger(__name__)

# Maximum seconds to wait for a single AkShare API call before giving up.
# Prevents proxy/network issues from blocking the entire analysis pipeline.
_API_CALL_TIMEOUT_SECONDS = 30


# ── Column name mappings (Chinese → English) ──────────────────────────

_METRICS_COLUMNS: Dict[str, str] = {
    "净资产收益率": "roe",
    "总资产净利率": "roa",
    "销售净利率": "net_profit_margin",
    "销售毛利率": "gross_margin",
    "资产负债率": "debt_to_asset_ratio",
    "流动比率": "current_ratio",
    "速动比率": "quick_ratio",
    "营业收入同比增长率": "revenue_growth_yoy",
    "净利润同比增长率": "profit_growth_yoy",
    "每股收益": "eps",
    "每股净资产": "bps",
    "每股未分配利润": "undistributed_profit_per_share",
}

_INCOME_COLUMNS: Dict[str, str] = {
    "一、营业收入": "revenue",
    "营业收入": "revenue",
    "减：营业成本": "cost_of_revenue",
    "营业成本": "cost_of_revenue",
    "营业利润": "operating_profit",
    "利润总额": "total_profit",
    "净利润": "net_income",
    "销售费用": "selling_expenses",
    "管理费用": "admin_expenses",
    "财务费用": "financial_expenses",
    "研发费用": "rd_expenses",
    "所得税费用": "income_tax",
}

_BALANCE_COLUMNS: Dict[str, str] = {
    "货币资金": "cash",
    "应收账款": "accounts_receivable",
    "存货": "inventory",
    "流动资产合计": "total_current_assets",
    "非流动资产合计": "total_noncurrent_assets",
    "资产总计": "total_assets",
    "短期借款": "short_term_debt",
    "应付账款": "accounts_payable",
    "流动负债合计": "total_current_liabilities",
    "非流动负债合计": "total_noncurrent_liabilities",
    "负债合计": "total_liabilities",
    "所有者权益合计": "total_equity",
}

_CASHFLOW_COLUMNS: Dict[str, str] = {
    "经营活动现金流入小计": "operating_cash_inflow",
    "经营活动现金流出小计": "operating_cash_outflow",
    "经营活动产生的现金流量净额": "operating_cash_flow",
    "投资活动产生的现金流量净额": "investing_cash_flow",
    "筹资活动产生的现金流量净额": "financing_cash_flow",
    "现金及现金等价物净增加额": "net_change_in_cash",
}


class FinancialDataAdapter:
    """
    AkShare financial data adapter with per-instance caching.

    Wraps four AkShare financial APIs and delegates price/market-cap queries
    to the existing ``AkShareProvider``.  The instance-level dict cache ensures
    that when multiple persona agents share *one* adapter, each unique
    (method, symbol) combination is fetched at most once.

    Example::

        adapter = FinancialDataAdapter()
        metrics = adapter.get_financial_metrics("000001")
        income  = adapter.get_income_statement("000001")
        prices  = adapter.get_prices("000001", days=60)
    """

    def __init__(self) -> None:
        self._ak: Any = None
        self._cache: Dict[str, Any] = {}
        self._akshare_provider: Any = None  # lazy AkShareProvider instance

        self._initialize()

    # ── Initialization ────────────────────────────────────────────

    def _initialize(self) -> None:
        """Lazy-import akshare; fail silently so the class is always usable."""
        try:
            import akshare as ak
            self._ak = ak
            logger.info("✅ FinancialDataAdapter: AkShare 初始化成功")
        except ImportError:
            logger.error("❌ FinancialDataAdapter: AkShare 未安装，请运行: pip install akshare")
            self._ak = None

    def _ensure_akshare_provider(self) -> Any:
        """Lazily create an ``AkShareProvider`` for delegated calls."""
        if self._akshare_provider is None:
            from .akshare_provider import AkShareProvider
            self._akshare_provider = AkShareProvider()
        return self._akshare_provider

    # ── Helpers ───────────────────────────────────────────────────

    def _call_with_timeout(self, fn, *args, **kwargs) -> Any:
        """Call an AkShare API function with a timeout to prevent blocking.

        AkShare internally uses ``requests`` without exposing timeout params,
        so we run the call in a thread and enforce our own deadline.
        """
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn, *args, **kwargs)
            try:
                return future.result(timeout=_API_CALL_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                logger.warning(
                    "FinancialDataAdapter: API call %s timed out after %ds",
                    getattr(fn, "__name__", "unknown"),
                    _API_CALL_TIMEOUT_SECONDS,
                )
                return None

    @staticmethod
    def _convert_symbol(symbol: str) -> str:
        """Normalize symbol to 6-digit string (matches AkShareProvider)."""
        return str(symbol).zfill(6)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Safely convert a value to float, returning None on failure."""
        try:
            if value is None or value == "" or pd.isna(value):
                return None
            return float(value)
        except (ValueError, TypeError):
            return None

    def _get_cache(self, method: str, symbol: str) -> Optional[Any]:
        """Return cached result or ``None`` sentinel (not cached yet)."""
        return self._cache.get(f"{method}:{symbol}")

    def _set_cache(self, method: str, symbol: str, data: Any) -> None:
        """Store data in the per-instance cache."""
        self._cache[f"{method}:{symbol}"] = data

    @staticmethod
    def _map_row(row: pd.Series, mapping: Dict[str, str]) -> Dict[str, Optional[float]]:
        """
        Map Chinese column names in *row* to English keys using *mapping*.

        Skips missing columns silently (AkShare column names can change between
        versions).  All mapped values are passed through ``_safe_float``.
        """
        result: Dict[str, Optional[float]] = {}
        safe_float = FinancialDataAdapter._safe_float
        for cn_name, en_name in mapping.items():
            if cn_name in row.index:
                result[en_name] = safe_float(row[cn_name])
        return result

    # ── Public API: Financial Metrics ─────────────────────────────

    def get_financial_metrics(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch key financial analysis indicators for the most recent 4 quarters.

        AkShare API: ``ak.stock_financial_analysis_indicator_em(symbol=...)``

        Args:
            symbol: 6-digit A-share stock code.

        Returns:
            ``{"quarters": [dict, ...], "latest": dict}`` with English keys.
            Empty dict ``{}`` on failure.
        """
        symbol = self._convert_symbol(symbol)
        cached = self._get_cache("financial_metrics", symbol)
        if cached is not None:
            return cached

        if self._ak is None:
            logger.warning("⚠️ FinancialDataAdapter: AkShare 不可用，返回空数据")
            self._set_cache("financial_metrics", symbol, {})
            return {}

        try:
            df: pd.DataFrame = self._call_with_timeout(
                self._ak.stock_financial_analysis_indicator_em,
                symbol=symbol,
            )

            if df is None or df.empty:
                logger.warning("⚠️ FinancialDataAdapter: 未找到 %s 财务指标数据", symbol)
                self._set_cache("financial_metrics", symbol, {})
                return {}

            # Each row is a different reporting period; first column is the date.
            quarters: List[Dict[str, Any]] = []
            date_col = df.columns[0]

            for _, row in df.head(4).iterrows():
                period = str(row[date_col])
                mapped = self._map_row(row, _METRICS_COLUMNS)
                mapped["period"] = period
                quarters.append(mapped)

            result: Dict[str, Any] = {
                "quarters": quarters,
                "latest": quarters[0] if quarters else {},
            }

            # Log missing columns for diagnostics
            if quarters:
                found_keys = set(quarters[0].keys())
                expected_en = set(_METRICS_COLUMNS.values())
                missing = expected_en - found_keys
                if missing:
                    logger.warning(
                        "⚠️ FinancialDataAdapter: %s 缺少指标列: %s",
                        symbol,
                        missing,
                    )

            logger.info(
                "✅ FinancialDataAdapter: 获取 %s 财务指标 %d 个季度",
                symbol,
                len(quarters),
            )
            self._set_cache("financial_metrics", symbol, result)
            return result

        except Exception as e:
            logger.error("❌ FinancialDataAdapter: 获取财务指标失败 %s: %s", symbol, e)
            self._set_cache("financial_metrics", symbol, {})
            return {}

    # ── Public API: Income Statement ──────────────────────────────

    def get_income_statement(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch the most recent income statement.

        AkShare API: ``ak.stock_profit_sheet_by_report_em(symbol=...)``

        Args:
            symbol: 6-digit A-share stock code.

        Returns:
            Dict with English keys (revenue, cost_of_revenue, etc.) and a
            ``"period"`` field.  Empty dict ``{}`` on failure.
        """
        symbol = self._convert_symbol(symbol)
        cached = self._get_cache("income_statement", symbol)
        if cached is not None:
            return cached

        if self._ak is None:
            self._set_cache("income_statement", symbol, {})
            return {}

        try:
            df: pd.DataFrame = self._call_with_timeout(
                self._ak.stock_profit_sheet_by_report_em,
                symbol=symbol,
            )

            if df is None or df.empty:
                logger.warning("⚠️ FinancialDataAdapter: 未找到 %s 利润表数据", symbol)
                self._set_cache("income_statement", symbol, {})
                return {}

            # First row = most recent period
            row = df.iloc[0]
            date_col = df.columns[0]
            result: Dict[str, Any] = {"period": str(row[date_col])}
            result.update(self._map_row(row, _INCOME_COLUMNS))

            logger.info("✅ FinancialDataAdapter: 获取 %s 利润表成功", symbol)
            self._set_cache("income_statement", symbol, result)
            return result

        except Exception as e:
            logger.error("❌ FinancialDataAdapter: 获取利润表失败 %s: %s", symbol, e)
            self._set_cache("income_statement", symbol, {})
            return {}

    # ── Public API: Balance Sheet ─────────────────────────────────

    def get_balance_sheet(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch the most recent balance sheet.

        AkShare API: ``ak.stock_balance_sheet_by_report_em(symbol=...)``

        Args:
            symbol: 6-digit A-share stock code.

        Returns:
            Dict with English keys (cash, total_assets, etc.) and a
            ``"period"`` field.  Empty dict ``{}`` on failure.
        """
        symbol = self._convert_symbol(symbol)
        cached = self._get_cache("balance_sheet", symbol)
        if cached is not None:
            return cached

        if self._ak is None:
            self._set_cache("balance_sheet", symbol, {})
            return {}

        try:
            df: pd.DataFrame = self._call_with_timeout(
                self._ak.stock_balance_sheet_by_report_em,
                symbol=symbol,
            )

            if df is None or df.empty:
                logger.warning("⚠️ FinancialDataAdapter: 未找到 %s 资产负债表数据", symbol)
                self._set_cache("balance_sheet", symbol, {})
                return {}

            row = df.iloc[0]
            date_col = df.columns[0]
            result: Dict[str, Any] = {"period": str(row[date_col])}
            result.update(self._map_row(row, _BALANCE_COLUMNS))

            logger.info("✅ FinancialDataAdapter: 获取 %s 资产负债表成功", symbol)
            self._set_cache("balance_sheet", symbol, result)
            return result

        except Exception as e:
            logger.error("❌ FinancialDataAdapter: 获取资产负债表失败 %s: %s", symbol, e)
            self._set_cache("balance_sheet", symbol, {})
            return {}

    # ── Public API: Cash Flow Statement ───────────────────────────

    def get_cash_flow_statement(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch the most recent cash flow statement and compute free cash flow.

        AkShare API: ``ak.stock_cash_flow_sheet_by_report_em(symbol=...)``

        ``free_cash_flow = operating_cash_flow + investing_cash_flow``
        (investing_cash_flow is usually negative).

        Args:
            symbol: 6-digit A-share stock code.

        Returns:
            Dict with English keys and ``"period"``, including
            ``"free_cash_flow"``.  Empty dict ``{}`` on failure.
        """
        symbol = self._convert_symbol(symbol)
        cached = self._get_cache("cash_flow_statement", symbol)
        if cached is not None:
            return cached

        if self._ak is None:
            self._set_cache("cash_flow_statement", symbol, {})
            return {}

        try:
            df: pd.DataFrame = self._call_with_timeout(
                self._ak.stock_cash_flow_sheet_by_report_em,
                symbol=symbol,
            )

            if df is None or df.empty:
                logger.warning("⚠️ FinancialDataAdapter: 未找到 %s 现金流量表数据", symbol)
                self._set_cache("cash_flow_statement", symbol, {})
                return {}

            row = df.iloc[0]
            date_col = df.columns[0]
            result: Dict[str, Any] = {"period": str(row[date_col])}
            result.update(self._map_row(row, _CASHFLOW_COLUMNS))

            # Compute free cash flow
            ocf = result.get("operating_cash_flow") or 0
            icf = result.get("investing_cash_flow") or 0
            result["free_cash_flow"] = self._safe_float(ocf + icf)

            logger.info("✅ FinancialDataAdapter: 获取 %s 现金流量表成功", symbol)
            self._set_cache("cash_flow_statement", symbol, result)
            return result

        except Exception as e:
            logger.error("❌ FinancialDataAdapter: 获取现金流量表失败 %s: %s", symbol, e)
            self._set_cache("cash_flow_statement", symbol, {})
            return {}

    # ── Public API: Prices (delegated) ────────────────────────────

    def get_prices(self, symbol: str, days: int = 120) -> Optional[pd.DataFrame]:
        """
        Fetch daily price history by delegating to ``AkShareProvider``.

        Args:
            symbol: 6-digit A-share stock code.
            days: Number of calendar days of history.

        Returns:
            DataFrame with date/open/close/high/low/volume columns,
            or ``None`` on failure.
        """
        symbol = self._convert_symbol(symbol)
        cached = self._get_cache("prices", symbol)
        if cached is not None:
            return cached

        try:
            provider = self._ensure_akshare_provider()
            data = provider.get_daily_hist(symbol, days)

            if data is not None:
                logger.info("✅ FinancialDataAdapter: 获取 %s 价格数据 %d 条", symbol, len(data))
            self._set_cache("prices", symbol, data)
            return data

        except Exception as e:
            logger.error("❌ FinancialDataAdapter: 获取价格数据失败 %s: %s", symbol, e)
            self._set_cache("prices", symbol, None)
            return None

    # ── Public API: Market Cap (delegated) ────────────────────────

    def get_market_cap(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        Fetch total and circulating market capitalization.

        Delegates to ``AkShareProvider.get_fundamental_data()`` and extracts
        ``total_mv`` / ``circulating_mv``.

        Args:
            symbol: 6-digit A-share stock code.

        Returns:
            ``{"total_market_cap": ..., "circulating_market_cap": ...}``
            or ``None`` on failure.
        """
        symbol = self._convert_symbol(symbol)
        cached = self._get_cache("market_cap", symbol)
        if cached is not None:
            return cached

        try:
            provider = self._ensure_akshare_provider()
            data = provider.get_fundamental_data(symbol)

            if data is None:
                logger.warning("⚠️ FinancialDataAdapter: 未获取到 %s 基本面数据", symbol)
                self._set_cache("market_cap", symbol, None)
                return None

            result: Dict[str, float] = {
                "total_market_cap": data.get("total_mv"),
                "circulating_market_cap": data.get("circulating_mv"),
            }

            logger.info("✅ FinancialDataAdapter: 获取 %s 市值数据成功", symbol)
            self._set_cache("market_cap", symbol, result)
            return result

        except Exception as e:
            logger.error("❌ FinancialDataAdapter: 获取市值数据失败 %s: %s", symbol, e)
            self._set_cache("market_cap", symbol, None)
            return None
