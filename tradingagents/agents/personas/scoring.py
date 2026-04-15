"""Quantitative scoring functions for persona agents.

Ported concepts from virattt/ai-hedge-fund, adapted for A-share data structures.
Each function receives plain Python dicts/DataFrames from FinancialDataAdapter
and returns Dict[str, float] of named metric values.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_ANNUALIZATION_FACTOR = 252  # trading days per year (China A-share)


def _safe_div(numerator, denominator, default: float = 0.0) -> float:
    """Safely divide two values, returning *default* on zero / None inputs."""
    try:
        if numerator is None or denominator is None:
            return default
        num = float(numerator)
        den = float(denominator)
        if den == 0:
            return default
        return num / den
    except (TypeError, ValueError):
        return default


def _compute_daily_returns(prices: pd.DataFrame) -> pd.Series:
    """Compute daily percentage returns from close prices, dropping NaN."""
    if prices is None or not isinstance(prices, pd.DataFrame) or prices.empty:
        return pd.Series(dtype=float)
    close = pd.to_numeric(prices["close"], errors="coerce")
    returns = close.pct_change().dropna()
    return returns


# ---------------------------------------------------------------------------
# 1. Value metrics
# ---------------------------------------------------------------------------

def calc_value_metrics(
    metrics: Dict,
    price: float = 0,
    market_cap: Optional[Dict] = None,
) -> Dict[str, float]:
    """Calculate valuation ratios used by Buffett / Munger / Burry personas.

    Args:
        metrics: ``FinancialDataAdapter.get_financial_metrics()["latest"]`` —
            expects keys like ``roe``, ``roa``, ``gross_margin``, ``eps``, ``bps``.
        price: Current stock price.
        market_cap: Optional dict with ``total_market_cap``, ``total_debt``,
            ``cash`` keys for EV/EBITDA approximation.

    Returns:
        Dict with ``pe_ratio``, ``pb_ratio``, ``ev_ebitda``, ``dividend_yield``.
    """
    if not metrics or not isinstance(metrics, dict):
        metrics = {}

    eps = float(metrics.get("eps", 0) or 0)
    bps = float(metrics.get("bps", 0) or 0)
    price = float(price or 0)

    # P/E ratio
    pe_ratio = _safe_div(price, eps) if eps > 0 else 0.0

    # P/B ratio
    pb_ratio = _safe_div(price, bps) if bps > 0 else 0.0

    # EV/EBITDA (approximate)
    ev_ebitda = 0.0
    ebitda = float(metrics.get("ebitda", 0) or 0)
    if market_cap and isinstance(market_cap, dict) and ebitda > 0:
        cap = float(market_cap.get("total_market_cap", 0) or 0)
        debt = float(market_cap.get("total_debt", 0) or 0)
        cash = float(market_cap.get("cash", 0) or 0)
        ev = cap + debt - cash
        ev_ebitda = _safe_div(ev, ebitda)

    # Dividend yield (already in metrics or derivable)
    div_yield = float(metrics.get("dividend_yield", 0) or 0)
    if div_yield == 0 and price > 0:
        dps = float(metrics.get("dps", 0) or 0)
        if dps > 0:
            div_yield = _safe_div(dps, price) * 100  # as percentage

    return {
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "ev_ebitda": ev_ebitda,
        "dividend_yield": div_yield,
    }


# ---------------------------------------------------------------------------
# 2. Financial health
# ---------------------------------------------------------------------------

def calc_financial_health(
    metrics: Dict,
    balance_sheet: Dict,
) -> Dict[str, float]:
    """Calculate solvency and bankruptcy-risk indicators.

    Args:
        metrics: Financial metrics dict (roe, debt_to_asset_ratio, current_ratio,
            quick_ratio, etc.).
        balance_sheet: Balance sheet dict with total_assets, total_liabilities,
            total_equity, total_current_assets, total_current_liabilities, cash.

    Returns:
        Dict with ``debt_to_equity``, ``current_ratio``, ``quick_ratio``,
        ``altman_z_score``, ``equity_multiplier``.
    """
    if not metrics or not isinstance(metrics, dict):
        metrics = {}
    if not balance_sheet or not isinstance(balance_sheet, dict):
        balance_sheet = {}

    total_assets = float(balance_sheet.get("total_assets", 0) or 0)
    total_liabilities = float(balance_sheet.get("total_liabilities", 0) or 0)
    total_equity = float(balance_sheet.get("total_equity", 0) or 0)
    current_assets = float(balance_sheet.get("total_current_assets", 0) or 0)
    current_liabilities = float(balance_sheet.get("total_current_liabilities", 0) or 0)
    cash = float(balance_sheet.get("cash", 0) or 0)
    inventory = float(balance_sheet.get("inventory", 0) or 0)

    # Debt to equity
    debt_to_equity = _safe_div(total_liabilities, total_equity)

    # Current ratio — prefer pre-calculated from metrics
    current_ratio = float(metrics.get("current_ratio", 0) or 0)
    if current_ratio == 0:
        current_ratio = _safe_div(current_assets, current_liabilities)

    # Quick ratio — prefer pre-calculated from metrics
    quick_ratio = float(metrics.get("quick_ratio", 0) or 0)
    if quick_ratio == 0:
        quick_ratio = _safe_div(current_assets - inventory, current_liabilities)

    # Equity multiplier
    equity_multiplier = _safe_div(total_assets, total_equity)

    # Altman Z-Score (simplified)
    altman_z = 0.0
    if total_assets > 0 and total_liabilities > 0:
        # X1: working capital / total assets
        x1 = _safe_div(current_assets - current_liabilities, total_assets)

        # X2: retained earnings / total assets
        retained = float(balance_sheet.get("retained_earnings", 0) or 0)
        if retained == 0:
            # approximate with 50% of equity
            retained = total_equity * 0.5
        x2 = _safe_div(retained, total_assets)

        # X3: EBIT / total assets
        ebit = float(balance_sheet.get("ebit", 0) or 0)
        if ebit == 0:
            ebit = float(metrics.get("operating_profit", 0) or 0)
        x3 = _safe_div(ebit, total_assets)

        # X4: market value of equity / total liabilities (use equity as proxy)
        x4 = _safe_div(total_equity, total_liabilities)

        # X5: revenue / total assets
        revenue = float(balance_sheet.get("revenue", 0) or 0)
        if revenue == 0:
            revenue = float(metrics.get("net_income", 0) or 0)
        x5 = _safe_div(revenue, total_assets)

        altman_z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

    return {
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "altman_z_score": altman_z,
        "equity_multiplier": equity_multiplier,
    }


# ---------------------------------------------------------------------------
# 3. Earnings quality
# ---------------------------------------------------------------------------

def calc_earnings_quality(
    income_stmt: Dict,
    cash_flow: Dict,
) -> Dict[str, float]:
    """Assess how closely reported earnings match cash generation.

    Args:
        income_stmt: From ``get_income_statement()`` — keys: net_income, revenue,
            operating_profit, rd_expenses.
        cash_flow: From ``get_cash_flow_statement()`` — keys:
            operating_cash_flow, free_cash_flow.

    Returns:
        Dict with ``accrual_ratio``, ``fcf_to_net_income``,
        ``operating_leverage``, ``rd_intensity``.
    """
    if not income_stmt or not isinstance(income_stmt, dict):
        income_stmt = {}
    if not cash_flow or not isinstance(cash_flow, dict):
        cash_flow = {}

    net_income = float(income_stmt.get("net_income", 0) or 0)
    revenue = float(income_stmt.get("revenue", 0) or 0)
    operating_profit = float(income_stmt.get("operating_profit", 0) or 0)
    rd_expenses = float(income_stmt.get("rd_expenses", 0) or 0)
    ocf = float(cash_flow.get("operating_cash_flow", 0) or 0)
    fcf = float(cash_flow.get("free_cash_flow", 0) or 0)

    # Accrual ratio: (net_income - OCF) / |net_income|
    if net_income != 0:
        accrual_ratio = (net_income - ocf) / abs(net_income)
    else:
        accrual_ratio = 0.0

    # FCF to net income
    fcf_to_ni = _safe_div(fcf, net_income) if net_income > 0 else 0.0

    # Operating leverage (operating margin)
    operating_leverage = _safe_div(operating_profit, revenue)

    # R&D intensity
    rd_intensity = _safe_div(rd_expenses, revenue)

    return {
        "accrual_ratio": float(accrual_ratio),
        "fcf_to_net_income": float(fcf_to_ni),
        "operating_leverage": float(operating_leverage),
        "rd_intensity": float(rd_intensity),
    }


# ---------------------------------------------------------------------------
# 4. Margin of safety
# ---------------------------------------------------------------------------

def calc_margin_safety(
    metrics: Dict,
    price: float,
) -> Dict[str, float]:
    """Estimate intrinsic value and margin of safety for value investors.

    Args:
        metrics: Financial metrics dict (eps, bps, roe).
        price: Current stock price.

    Returns:
        Dict with ``book_value_per_share``, ``intrinsic_value_estimate``,
        ``margin_of_safety_pct``, ``price_to_book``.
    """
    if not metrics or not isinstance(metrics, dict):
        metrics = {}
    price = float(price or 0)

    bps = float(metrics.get("bps", 0) or 0)
    eps = float(metrics.get("eps", 0) or 0)
    roe = float(metrics.get("roe", 0) or 0)  # percentage

    # Graham-style intrinsic value: bps * (1 + roe/100)^5
    # Also consider earnings power: eps * 15 (conservative PE)
    iv_graham = bps * ((1 + roe / 100) ** 5) if bps > 0 and roe > 0 else 0.0
    iv_earnings = eps * 15 if eps > 0 else 0.0

    # Use the higher of the two estimates (more conservative for MoS)
    intrinsic_value = max(iv_graham, iv_earnings)

    # Margin of safety percentage
    margin_of_safety_pct = 0.0
    if intrinsic_value > 0:
        margin_of_safety_pct = (intrinsic_value - price) / intrinsic_value * 100

    # Price to book
    price_to_book = _safe_div(price, bps) if bps > 0 else 0.0

    return {
        "book_value_per_share": float(bps),
        "intrinsic_value_estimate": float(intrinsic_value),
        "margin_of_safety_pct": float(margin_of_safety_pct),
        "price_to_book": float(price_to_book),
    }


# ---------------------------------------------------------------------------
# 5. Volatility metrics
# ---------------------------------------------------------------------------

_EMPTY_VOL: Dict[str, float] = {
    "realized_vol_30d": 0.0,
    "realized_vol_90d": 0.0,
    "max_drawdown": 0.0,
    "var_95": 0.0,
    "kurtosis": 0.0,
    "avg_daily_range": 0.0,
}


def calc_volatility_metrics(prices: pd.DataFrame) -> Dict[str, float]:
    """Compute risk / tail-risk metrics for Taleb / Druckenmiller personas.

    Args:
        prices: DataFrame from ``get_prices()`` with columns:
            date, open, close, high, low, volume, amount.

    Returns:
        Dict with ``realized_vol_30d``, ``realized_vol_90d``, ``max_drawdown``,
        ``var_95``, ``kurtosis``, ``avg_daily_range``.
    """
    if (
        prices is None
        or not isinstance(prices, pd.DataFrame)
        or len(prices) < 10
    ):
        return dict(_EMPTY_VOL)

    daily_returns = _compute_daily_returns(prices)
    if daily_returns.empty or len(daily_returns) < 5:
        return dict(_EMPTY_VOL)

    close = pd.to_numeric(prices["close"], errors="coerce")
    high = pd.to_numeric(prices["high"], errors="coerce")
    low = pd.to_numeric(prices["low"], errors="coerce")

    # Realized volatility (annualized)
    realized_vol_30d = 0.0
    if len(daily_returns) >= 20:
        realized_vol_30d = float(daily_returns.tail(30).std() * np.sqrt(_ANNUALIZATION_FACTOR))

    realized_vol_90d = 0.0
    if len(daily_returns) >= 60:
        realized_vol_90d = float(daily_returns.tail(90).std() * np.sqrt(_ANNUALIZATION_FACTOR))

    # Max drawdown
    cummax = close.cummax()
    drawdown = (close - cummax) / cummax
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    # Parametric VaR at 95% (5th percentile annualized)
    var_95 = float(daily_returns.quantile(0.05) * np.sqrt(_ANNUALIZATION_FACTOR))

    # Excess kurtosis (fat tails)
    try:
        kurt = float(daily_returns.kurtosis())
        if np.isnan(kurt):
            kurt = 0.0
    except Exception:
        kurt = 0.0

    # Average daily range as % of close
    valid_range = (high - low) / close.replace(0, np.nan)
    valid_range = valid_range.dropna()
    avg_daily_range = float(valid_range.mean()) if not valid_range.empty else 0.0

    return {
        "realized_vol_30d": realized_vol_30d,
        "realized_vol_90d": realized_vol_90d,
        "max_drawdown": max_drawdown,
        "var_95": var_95,
        "kurtosis": kurt,
        "avg_daily_range": avg_daily_range,
    }


# ---------------------------------------------------------------------------
# 6. Momentum metrics
# ---------------------------------------------------------------------------

_EMPTY_MOMENTUM_KEYS = [
    "sma_20", "sma_50", "sma_200",
    "rsi_14", "macd_line", "macd_signal", "macd_histogram",
    "price_vs_sma50_pct", "volume_sma_20", "volume_ratio",
]


def calc_momentum_metrics(prices: pd.DataFrame) -> Dict[str, float]:
    """Compute trend / momentum indicators for Druckenmiller / Wood personas.

    Args:
        prices: DataFrame with columns: date, open, close, high, low, volume, amount.

    Returns:
        Dict with SMA values, RSI, MACD, and volume indicators.
    """
    empty = {k: 0.0 for k in _EMPTY_MOMENTUM_KEYS}

    if (
        prices is None
        or not isinstance(prices, pd.DataFrame)
        or len(prices) < 20
    ):
        return empty

    close = pd.to_numeric(prices["close"], errors="coerce")
    volume = pd.to_numeric(prices["volume"], errors="coerce")

    # Simple moving averages
    sma_20 = float(close.tail(20).mean()) if len(close) >= 20 else 0.0
    sma_50 = float(close.tail(50).mean()) if len(close) >= 50 else 0.0
    sma_200 = float(close.tail(200).mean()) if len(close) >= 200 else 0.0

    # RSI-14 (standard Wilder smoothing)
    rsi_14 = _compute_rsi(close, period=14)

    # MACD (12-26-9)
    macd_line_val, macd_signal_val, macd_hist_val = _compute_macd(close)

    # Price vs SMA-50
    last_close = float(close.iloc[-1])
    price_vs_sma50_pct = _safe_div(last_close - sma_50, sma_50) * 100 if sma_50 > 0 else 0.0

    # Volume SMA and ratio
    vol_sma_20 = float(volume.tail(20).mean()) if len(volume) >= 20 else 0.0
    last_volume = float(volume.iloc[-1])
    volume_ratio = _safe_div(last_volume, vol_sma_20)

    return {
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "rsi_14": rsi_14,
        "macd_line": macd_line_val,
        "macd_signal": macd_signal_val,
        "macd_histogram": macd_hist_val,
        "price_vs_sma50_pct": price_vs_sma50_pct,
        "volume_sma_20": vol_sma_20,
        "volume_ratio": volume_ratio,
    }


def _compute_rsi(series: pd.Series, period: int = 14) -> float:
    """Compute RSI using standard Wilder smoothing method."""
    if len(series) < period + 1:
        return 0.0

    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Initial averages (simple mean for first `period` values)
    avg_gain = float(gain.iloc[:period].mean())
    avg_loss = float(loss.iloc[:period].mean())

    if avg_loss == 0:
        return 100.0

    # Wilder smoothing for remaining values
    for i in range(period, len(gain)):
        avg_gain = (avg_gain * (period - 1) + float(gain.iloc[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(loss.iloc[i])) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi)


def _compute_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple:
    """Compute MACD line, signal line, and histogram.

    Returns:
        (macd_line, signal_line, histogram) as floats.
    """
    if len(series) < slow:
        return 0.0, 0.0, 0.0

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    last_macd = float(macd_line.iloc[-1])
    last_signal = float(signal_line.iloc[-1])
    last_hist = float(histogram.iloc[-1])

    # Replace NaN with 0
    if np.isnan(last_macd):
        last_macd = 0.0
    if np.isnan(last_signal):
        last_signal = 0.0
    if np.isnan(last_hist):
        last_hist = 0.0

    return last_macd, last_signal, last_hist


# ---------------------------------------------------------------------------
# 7. Growth metrics
# ---------------------------------------------------------------------------

def calc_growth_metrics(metrics: Dict) -> Dict[str, float]:
    """Calculate growth indicators for Wood persona.

    Args:
        metrics: Financial metrics dict. If it contains a ``quarters`` key with
            multiple quarters of data, trend calculations use them. Otherwise
            single-quarter values are used.

    Returns:
        Dict with ``revenue_growth_yoy``, ``profit_growth_yoy``, ``eps_growth``,
        ``margin_trend``.
    """
    if not metrics or not isinstance(metrics, dict):
        metrics = {}

    # Direct YoY growth rates (may already be pre-calculated)
    revenue_growth_yoy = float(metrics.get("revenue_growth_yoy", 0) or 0)
    profit_growth_yoy = float(metrics.get("profit_growth_yoy", 0) or 0)

    # EPS growth — prefer multi-quarter calculation
    eps_growth = float(metrics.get("eps_growth", 0) or 0)

    quarters = metrics.get("quarters")
    if quarters and isinstance(quarters, list) and len(quarters) >= 2:
        # Compute EPS growth from quarter data
        eps_values = []
        for q in quarters:
            val = q.get("eps")
            if val is not None:
                try:
                    eps_values.append((q.get("period", ""), float(val)))
                except (TypeError, ValueError):
                    pass

        if len(eps_values) >= 2:
            # Sort by period (descending — latest first)
            eps_values.sort(key=lambda x: x[0], reverse=True)
            latest_eps = eps_values[0][1]
            earliest_eps = eps_values[-1][1]
            eps_growth = _safe_div(latest_eps - earliest_eps, abs(earliest_eps)) * 100

    # Margin trend (gross margin expansion/contraction)
    margin_trend = 0.0
    if quarters and isinstance(quarters, list) and len(quarters) >= 2:
        margin_values = []
        for q in quarters:
            val = q.get("gross_margin")
            if val is not None:
                try:
                    margin_values.append((q.get("period", ""), float(val)))
                except (TypeError, ValueError):
                    pass

        if len(margin_values) >= 2:
            margin_values.sort(key=lambda x: x[0], reverse=True)
            latest_margin = margin_values[0][1]
            earliest_margin = margin_values[-1][1]
            if earliest_margin != 0:
                margin_trend = (latest_margin - earliest_margin) / abs(earliest_margin) * 100

    return {
        "revenue_growth_yoy": float(revenue_growth_yoy),
        "profit_growth_yoy": float(profit_growth_yoy),
        "eps_growth": float(eps_growth),
        "margin_trend": float(margin_trend),
    }


# ---------------------------------------------------------------------------
# 8. Moat score
# ---------------------------------------------------------------------------

def calc_moat_score(
    metrics: Dict,
    income_stmt: Dict,
) -> Dict[str, float]:
    """Assess economic moat strength for Munger persona.

    Args:
        metrics: Financial metrics dict (roe, gross_margin, net_profit_margin,
            possibly with ``quarters`` for stability analysis).
        income_stmt: Income statement dict (revenue, operating_profit, rd_expenses).

    Returns:
        Dict with ``roic``, ``roe_stability``, ``margin_stability``,
        ``pricing_power``, ``scale_efficiency``.
    """
    if not metrics or not isinstance(metrics, dict):
        metrics = {}
    if not income_stmt or not isinstance(income_stmt, dict):
        income_stmt = {}

    operating_profit = float(income_stmt.get("operating_profit", 0) or 0)
    revenue = float(income_stmt.get("revenue", 0) or 0)
    total_assets = float(metrics.get("total_assets", 0) or 0)
    total_equity = float(metrics.get("total_equity", 0) or 0)
    total_debt = float(metrics.get("total_debt", 0) or 0)
    gross_margin = float(metrics.get("gross_margin", 0) or 0)

    # ROIC: (operating_profit * (1 - tax_rate)) / (total_equity + total_debt)
    tax_rate = 0.25  # standard China corporate tax
    invested_capital = total_equity + total_debt
    if invested_capital == 0 and total_assets > 0:
        invested_capital = total_assets
    roic = _safe_div(operating_profit * (1 - tax_rate), invested_capital) * 100

    # ROE stability (negative std of ROE — higher = more stable)
    roe_stability = 0.0
    quarters = metrics.get("quarters")
    if quarters and isinstance(quarters, list) and len(quarters) >= 2:
        roe_values = []
        for q in quarters:
            val = q.get("roe")
            if val is not None:
                try:
                    roe_values.append(float(val))
                except (TypeError, ValueError):
                    pass
        if len(roe_values) >= 2:
            roe_stability = -float(np.std(roe_values, ddof=1))

    # Margin stability (negative std of gross_margin — higher = more stable)
    margin_stability = 0.0
    if quarters and isinstance(quarters, list) and len(quarters) >= 2:
        gm_values = []
        for q in quarters:
            val = q.get("gross_margin")
            if val is not None:
                try:
                    gm_values.append(float(val))
                except (TypeError, ValueError):
                    pass
        if len(gm_values) >= 2:
            margin_stability = -float(np.std(gm_values, ddof=1))

    # Pricing power (gross margin as proxy)
    pricing_power = gross_margin * 100 if gross_margin <= 1 else gross_margin

    # Scale efficiency (operating margin)
    scale_efficiency = _safe_div(operating_profit, revenue) * 100

    return {
        "roic": float(roic),
        "roe_stability": float(roe_stability),
        "margin_stability": float(margin_stability),
        "pricing_power": float(pricing_power),
        "scale_efficiency": float(scale_efficiency),
    }
