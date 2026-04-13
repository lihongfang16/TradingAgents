"""
Market index and sector data tools for the Market Index Analyst.

Provides board-to-index mapping, index K-line data, and sector K-line data
via AkShare APIs for Chinese A-share markets.
"""
import logging
import re
from typing import Dict, Tuple

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Board → Index mapping (first 3 digits of stock code → board name + index)
# ---------------------------------------------------------------------------
BOARD_INDEX_MAP: Dict[str, Tuple[str, str]] = {
    "002": ("深证主板", "399001"),
    "000": ("深证主板", "399001"),
    "300": ("创业板", "399006"),
    "301": ("创业板", "399006"),
    "303": ("创业板", "399006"),
    "688": ("科创板", "000688"),
    "689": ("科创板", "000688"),
    "600": ("沪市主板", "000001"),
    "601": ("沪市主板", "000001"),
    "603": ("沪市主板", "000001"),
    "605": ("沪市主板", "000001"),
    "430": ("北交所", "899050"),
    "832": ("北交所", "899050"),
    "835": ("北交所", "899050"),
    "836": ("北交所", "899050"),
    "870": ("北交所", "899050"),
    "872": ("北交所", "899050"),
}

# Friendly names for common index symbols
INDEX_NAME_MAP: Dict[str, str] = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000688": "科创50",
    "899050": "北证50",
}


def _strip_exchange_prefix(symbol: str) -> str:
    """Remove exchange prefixes/suffixes to get a pure 6-digit stock code.

    Handles: SZ000001, SH600000, BJ430001, 000001.SZ, 600000.SH, etc.
    """
    symbol = str(symbol).strip().upper()
    # Remove trailing exchange suffix (.SZ, .SH, .BJ)
    symbol = re.sub(r"\.(SZ|SH|BJ)$", "", symbol)
    # Remove leading exchange prefix (SZ, SH, BJ)
    symbol = re.sub(r"^(SZ|SH|BJ)", "", symbol)
    # Strip any remaining non-digit characters
    symbol = re.sub(r"[^0-9]", "", symbol)
    return symbol.zfill(6)


def get_stock_market_and_sector(symbol: str) -> Dict[str, str]:
    """Return board type, primary index, and industry for a stock code.

    Args:
        symbol: Stock code like "002172", "SZ000001", "600000.SH", etc.

    Returns:
        Dict with keys: board_type, primary_index, primary_index_name, industry.
        Values are empty strings when lookup fails.
    """
    result: Dict[str, str] = {
        "board_type": "",
        "primary_index": "",
        "primary_index_name": "",
        "industry": "",
    }

    # --- Board & index lookup ---
    pure_code = _strip_exchange_prefix(symbol)
    prefix = pure_code[:3]
    mapping = BOARD_INDEX_MAP.get(prefix)
    if mapping:
        board_name, index_code = mapping
        result["board_type"] = board_name
        result["primary_index"] = index_code
        result["primary_index_name"] = INDEX_NAME_MAP.get(index_code, "")
    else:
        logger.warning(f"⚠️ Unknown board prefix '{prefix}' for symbol '{symbol}'")
        return result

    # --- Industry lookup via AkShare ---
    try:
        import akshare as ak  # noqa: F401

        df = ak.stock_individual_info_em(symbol=pure_code)
        if df is not None and not df.empty:
            # The DataFrame has columns "item" and "value" (as seen in akshare_provider.py)
            for _, row in df.iterrows():
                item = str(row.get("item", ""))
                if item == "行业":
                    result["industry"] = str(row.get("value", ""))
                    break
    except ImportError:
        logger.warning("⚠️ AkShare not installed — industry lookup skipped")
    except Exception as e:
        logger.warning(f"⚠️ Failed to get industry for {pure_code}: {e}")

    return result


@tool
def get_index_kline(index_symbol: str, start_date: str, end_date: str) -> str:
    """获取大盘指数K线数据。index_symbol: 指数代码如 000001(上证指数), 399001(深证成指), 399006(创业板指), 000688(科创50)。start_date: 开始日期 YYYYMMDD。end_date: 结束日期 YYYYMMDD。返回CSV格式数据。"""
    try:
        import akshare as ak

        df = ak.index_zh_a_hist(
            symbol=index_symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
        )

        if df is None or df.empty:
            return f"未找到指数 {index_symbol} 在 {start_date} 至 {end_date} 期间的数据"

        return df.to_string()

    except ImportError:
        return "错误: AkShare 未安装，请运行 pip install akshare"
    except Exception as e:
        return f"获取指数K线数据失败 ({index_symbol}): {e}"


@tool
def get_sector_kline(sector_name: str, start_date: str, end_date: str) -> str:
    """获取行业板块K线数据。sector_name: 板块名称如 医药生物、电子、计算机。start_date: 开始日期 YYYYMMDD。end_date: 结束日期 YYYYMMDD。返回CSV格式数据。"""
    try:
        import akshare as ak

        df = ak.stock_board_industry_hist_em(
            symbol=sector_name,
            period="daily",
            start_date=start_date,
            end_date=end_date,
        )

        if df is None or df.empty:
            return f"未找到板块 '{sector_name}' 在 {start_date} 至 {end_date} 期间的数据"

        return df.to_string()

    except ImportError:
        return "错误: AkShare 未安装，请运行 pip install akshare"
    except Exception as e:
        return f"获取板块K线数据失败 ({sector_name}): {e}"
