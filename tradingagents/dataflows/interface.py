from typing import Annotated

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .china_data_manager import ChinaDataManager

# Configuration and routing logic
from .config import get_config

# A-share 数据管理器单例
china_manager = ChinaDataManager()


# ── Adapter wrappers ─────────────────────────────────────────────
# Tool functions have different signatures than ChinaDataManager methods.
# These adapters bridge the gap.

def _china_get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Adapter: get_stock_data(symbol, start_date, end_date) → china_manager.get_kline()."""
    import pandas as pd
    df = china_manager.get_kline(symbol, period="day", limit=120)
    if df is None or df.empty:
        return f"No data available for {symbol}"
    return df.to_string()


def _china_get_indicators(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    """Adapter: get_indicators(symbol, indicator, curr_date, look_back_days) → kline + stockstats."""
    import pandas as pd
    from stockstats import StockDataFrame as Sdf

    limit = max(look_back_days + 50, 120)  # extra bars for indicator warm-up
    df = china_manager.get_kline(symbol, period="day", limit=limit)
    if df is None or df.empty:
        return f"No data available for {symbol}"

    # stockstats requires integer index, not DatetimeIndex
    df_work = df.reset_index(drop=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df_work.columns:
            df_work[col] = pd.to_numeric(df_work[col], errors='coerce')

    sdf = Sdf.retype(df_work)

    # Normalize indicator name
    ind = indicator.strip().lower()

    # Map common names to stockstats column names
    ind_map = {
        'rsi': 'rsi_14',
        'macd': 'macd',
        'macd_signal': 'macds',
        'macd_hist': 'macdh',
        'bollinger': 'boll_ub',
        'sma': 'close_20_sma',
        'sma_20': 'close_20_sma',
        'ema': 'close_20_ema',
        'ema_12': 'close_12_ema',
        'stochastic': 'kdjk_9',
        'atr': 'atr_14',
        'obv': 'obv',
        'volume': 'volume',
        'vwap': 'vwap',
    }
    col = ind_map.get(ind)
    if col is None:
        col = f'{ind}_14'  # default period

    # stockstats computes lazily — columns only appear after access.
    # Try to access the target column directly; if it fails, brute-force
    # scan known indicator names.
    target_col = None
    try:
        _ = sdf[col]
        target_col = col
    except Exception:
        pass

    if target_col is None:
        # Brute-force: try to match by checking if indicator name appears
        # in the lazily-computable column names
        candidates = {
            'rsi': ['rsi_6', 'rsi_12', 'rsi_14'],
            'macd': ['macd', 'macds', 'macdh'],
            'boll': ['boll_ub', 'boll_lb', 'boll_mid'],
            'sma': ['close_5_sma', 'close_10_sma', 'close_20_sma'],
            'ema': ['close_12_ema', 'close_20_ema', 'close_26_ema'],
            'stochastic': ['kdjk_9', 'kdjk', 'kdjd_9'],
            'atr': ['atr_14'],
            'obv': ['obv'],
            'cci': ['cci_14'],
            'wr': ['wr_14'],
            'mfi': ['mfi_14'],
            'vwap': ['vwap'],
            'volume': ['volume'],
        }
        test_cols = candidates.get(ind, [col])
        for tc in test_cols:
            try:
                _ = sdf[tc]
                target_col = tc
                break
            except Exception:
                pass

    if target_col is None:
        # Last resort: brute-force scan all known indicator names
        all_indicators = []
        all_test_cols = ['rsi_6','rsi_14','rsi_12','macd','macds','macdh','boll_ub','boll_lb','boll_mid',
                         'sma_5','sma_10','sma_20','ema_12','ema_20','ema_26','kdjk_9','kdjk',
                         'kdjd_9','atr_14','obv','cci_14','wr_14','mfi_14','vwma_14','volume']
        for test_col in all_test_cols:
            try:
                _ = sdf[test_col]
                all_indicators.append(test_col)
                # If the indicator name matches exactly, use it
                if test_col == ind or test_col == col:
                    target_col = test_col
            except Exception:
                pass
        if target_col is None:
            return f"Indicator '{indicator}' not found. Available: {all_indicators[:15]}"

    try:
        result = sdf[[target_col]].dropna().tail(look_back_days)
        return result.to_string()
    except Exception as e:
        return f"Error computing indicator '{indicator}': {e}"


def _china_get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Adapter: get_news(ticker, start_date, end_date) -> china_manager.get_realtime_quote()."""
    data = china_manager.get_realtime_quote(ticker)
    if data is None:
        return f"No realtime quote data available for {ticker}"
    return str(data)


def _china_get_fundamentals(ticker: str, curr_date: str) -> str:
    """Adapter: get_fundamentals(ticker, curr_date) -> china_manager.get_fundamental_data()."""
    data = china_manager.get_fundamental_data(ticker)
    if data is None:
        return f"No fundamental data available for {ticker}"
    return str(data)


def is_a_share(symbol: str) -> bool:
    """判断是否为 A 股代码。
    
    支持格式: 000001, 600000, 301188, SH600000, sz000001, BJ430047 等。
    规则: 纯 6 位数字，且首位为 0（深市主板）、3（创业板/北交所）或 6（沪市主板）。
    """
    symbol = str(symbol).strip().upper()
    for prefix in ("SZ", "SH", "BJ"):
        if symbol.startswith(prefix):
            symbol = symbol[2:]
    return len(symbol) == 6 and symbol.isdigit() and symbol[0] in ("0", "3", "6")

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "china",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "china": _china_get_stock_data,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "china": _china_get_indicators,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "china": _china_get_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "china": _china_get_news,  # A 股使用实时行情作为新闻替代
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    # A 股优先路由：如果 symbol 是 A 股代码，强制使用 ChinaDataManager
    symbol = kwargs.get("symbol") or (args[0] if args else None)
    if symbol and is_a_share(symbol):
        if method in VENDOR_METHODS and "china" in VENDOR_METHODS[method]:
            china_impl = VENDOR_METHODS[method]["china"]
            impl_func = china_impl[0] if isinstance(china_impl, list) else china_impl
            return impl_func(*args, **kwargs)

    # 美股/港股等其他市场：使用现有路由逻辑
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError:
            continue  # Only rate limits trigger fallback

    raise RuntimeError(f"No available vendor for '{method}'")