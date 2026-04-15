"""Michael Burry persona agent — deep value, contrarian, financial statement forensics."""
import logging
from typing import Any, Callable, Dict

from langchain_core.messages import AIMessage

from tradingagents.agents.personas.base_persona import (
    format_quantitative_summary,
    parse_persona_signal,
)
from tradingagents.agents.personas.scoring import (
    calc_earnings_quality,
    calc_financial_health,
    calc_margin_safety,
    calc_value_metrics,
)
from tradingagents.dataflows.financial_data_adapter import FinancialDataAdapter

logger = logging.getLogger(__name__)

# Shared adapter instance — per-process singleton for cache reuse
_adapter: FinancialDataAdapter = None


def _get_adapter() -> FinancialDataAdapter:
    global _adapter
    if _adapter is None:
        _adapter = FinancialDataAdapter()
    return _adapter


BURRY_SYSTEM_PROMPT = """你现在是迈克尔·布瑞(Michael Burry)，著名的深度价值投资者和逆向投资者。你因成功预测2008年次贷危机而闻名。

投资哲学：
- 寻找被市场严重低估的公司，特别是市净率(P/B)低于1的公司（净资产破净）
- 通过财务报表的深入分析发现隐藏资产和隐藏风险
- 关注自由现金流收益率（FCF Yield）
- 现金流与报告利润的背离是重要的预警信号（应计异常）
- 关注资产负债表的流动性：现金是否充足，短期债务是否可控
- 在市场恐慌时买入，在市场狂热时卖出
- A股特别关注：控股股东质押率过高是风险信号，特别分红潜力是加分项
- 关注EV/EBITDA（企业价值倍数）寻找低估机会

当前分析股票：{symbol}

## 量化分析数据
{quantitative_summary}

## 基本面报告摘要
{fundamentals_report}

请基于以上数据，以布瑞的深度价值视角进行分析：
1. 这家公司是否被市场严重低估？
2. 财务报表中是否有隐藏资产或隐藏风险？
3. 现金流是否支撑报告利润？
4. 资产负债表是否足够健康以抵御经济下行？

请以JSON格式输出你的判断：
```json
{{{{
    "signal": "bullish/bearish/neutral",
    "confidence": 0-100,
    "reasoning": "简短理由（200字以内）",
    "key_metrics": {{{{}}}}
}}}}
```"""


def create_michael_burry(llm) -> Callable:
    """Create a Michael Burry persona node for LangGraph."""

    def michael_burry_node(state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["company_of_interest"]

        # 1. Fetch data
        adapter = _get_adapter()

        try:
            metrics_data = adapter.get_financial_metrics(symbol)
        except Exception:
            logger.warning("⚠️ Burry: 获取财务指标失败 %s", symbol)
            metrics_data = {}

        try:
            balance_data = adapter.get_balance_sheet(symbol)
        except Exception:
            logger.warning("⚠️ Burry: 获取资产负债表失败 %s", symbol)
            balance_data = {}

        try:
            income_data = adapter.get_income_statement(symbol)
        except Exception:
            logger.warning("⚠️ Burry: 获取利润表失败 %s", symbol)
            income_data = {}

        try:
            cash_flow_data = adapter.get_cash_flow_statement(symbol)
        except Exception:
            logger.warning("⚠️ Burry: 获取现金流量表失败 %s", symbol)
            cash_flow_data = {}

        try:
            prices = adapter.get_prices(symbol)
        except Exception:
            logger.warning("⚠️ Burry: 获取价格数据失败 %s", symbol)
            prices = None

        try:
            market_cap = adapter.get_market_cap(symbol)
        except Exception:
            logger.warning("⚠️ Burry: 获取市值数据失败 %s", symbol)
            market_cap = None

        # 2. Extract current price
        current_price = 0.0
        if prices is not None and len(prices) > 0:
            try:
                current_price = float(prices["close"].iloc[-1])
            except Exception:
                current_price = 0.0

        # 3. Quantitative scoring
        metrics = metrics_data.get("latest", {}) if metrics_data else {}

        try:
            value_scores = calc_value_metrics(metrics, current_price, market_cap)
        except Exception:
            logger.warning("⚠️ Burry: 价值指标计算失败 %s", symbol)
            value_scores = {}

        try:
            health_scores = calc_financial_health(metrics, balance_data)
        except Exception:
            logger.warning("⚠️ Burry: 财务健康指标计算失败 %s", symbol)
            health_scores = {}

        try:
            earnings_scores = calc_earnings_quality(income_data, cash_flow_data)
        except Exception:
            logger.warning("⚠️ Burry: 盈余质量指标计算失败 %s", symbol)
            earnings_scores = {}

        try:
            safety_scores = calc_margin_safety(metrics, current_price)
        except Exception:
            logger.warning("⚠️ Burry: 安全边际指标计算失败 %s", symbol)
            safety_scores = {}

        # 4. Build prompt with quantitative data
        quant_summary = format_quantitative_summary(
            value=value_scores,
            health=health_scores,
            earnings=earnings_scores,
            safety=safety_scores,
        )

        prompt_text = BURRY_SYSTEM_PROMPT.format(
            symbol=symbol,
            quantitative_summary=quant_summary,
            fundamentals_report=state.get("fundamentals_report", ""),
        )

        # 5. Invoke LLM (plain, no bind_tools)
        response = llm.invoke(prompt_text)

        # 6. Parse structured signal
        signal = parse_persona_signal(response.content, "michael_burry")

        # 7. Log and return
        logger.info(
            "✅ Michael Burry: %s signal for %s (confidence: %d)",
            signal.get("signal", "N/A"),
            symbol,
            signal.get("confidence", 0),
        )

        return {
            "messages": [AIMessage(content=response.content)],
            "persona_signals": {"michael_burry": signal},
        }

    return michael_burry_node
