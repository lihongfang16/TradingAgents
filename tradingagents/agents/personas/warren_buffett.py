"""Warren Buffett persona agent — value investing, long-term ownership, margin of safety."""
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


BUFFETT_SYSTEM_PROMPT = """你现在是沃伦·巴菲特(Warren Buffett)，世界上最成功的价值投资者。你以长期持有优质公司股票而闻名。

投资哲学：
- 只投资你理解的企业（能力圈原则）
- 寻找具有持久竞争优势（经济护城河）的公司
- 以合理的价格买入优秀公司，而不是以便宜的价格买入平庸公司
- 关注净资产收益率(ROE)是否长期稳定在15%以上
- 债务股本比低于0.5，流动比率大于2.0
- 营业利润率稳定在15%以上
- 自由现金流充沛，盈余质量高（经营现金流与净利润匹配）
- 管理层诚信且以股东利益为导向
- 分红历史稳定，特别是A股市场中的国企蓝筹

当前分析股票：{symbol}

## 量化分析数据
{quantitative_summary}

## 基本面报告摘要
{fundamentals_report}

请基于以上数据，以巴菲特的投资视角进行分析：
1. 这家公司是否具有持久的竞争优势？
2. 管理层是否值得信赖？
3. 当前价格是否提供了足够的安全边际？
4. 长期持有5-10年的前景如何？

请以JSON格式输出你的判断：
```json
{{{{
    "signal": "bullish/bearish/neutral",
    "confidence": 0-100,
    "reasoning": "简短理由（200字以内）",
    "key_metrics": {{{{}}}}
}}}}
```"""


def create_warren_buffett(llm) -> Callable:
    """Create a Warren Buffett persona node for LangGraph."""

    def warren_buffett_node(state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["company_of_interest"]

        # 1. Fetch data
        adapter = _get_adapter()

        try:
            metrics_data = adapter.get_financial_metrics(symbol)
        except Exception:
            logger.warning("⚠️ Buffett: 获取财务指标失败 %s", symbol)
            metrics_data = {}

        try:
            balance_data = adapter.get_balance_sheet(symbol)
        except Exception:
            logger.warning("⚠️ Buffett: 获取资产负债表失败 %s", symbol)
            balance_data = {}

        try:
            income_data = adapter.get_income_statement(symbol)
        except Exception:
            logger.warning("⚠️ Buffett: 获取利润表失败 %s", symbol)
            income_data = {}

        try:
            cash_flow_data = adapter.get_cash_flow_statement(symbol)
        except Exception:
            logger.warning("⚠️ Buffett: 获取现金流量表失败 %s", symbol)
            cash_flow_data = {}

        try:
            prices = adapter.get_prices(symbol)
        except Exception:
            logger.warning("⚠️ Buffett: 获取价格数据失败 %s", symbol)
            prices = None

        try:
            market_cap = adapter.get_market_cap(symbol)
        except Exception:
            logger.warning("⚠️ Buffett: 获取市值数据失败 %s", symbol)
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
            logger.warning("⚠️ Buffett: 价值指标计算失败 %s", symbol)
            value_scores = {}

        try:
            health_scores = calc_financial_health(metrics, balance_data)
        except Exception:
            logger.warning("⚠️ Buffett: 财务健康指标计算失败 %s", symbol)
            health_scores = {}

        try:
            earnings_scores = calc_earnings_quality(income_data, cash_flow_data)
        except Exception:
            logger.warning("⚠️ Buffett: 盈余质量指标计算失败 %s", symbol)
            earnings_scores = {}

        try:
            safety_scores = calc_margin_safety(metrics, current_price)
        except Exception:
            logger.warning("⚠️ Buffett: 安全边际指标计算失败 %s", symbol)
            safety_scores = {}

        # 4. Build prompt with quantitative data
        quant_summary = format_quantitative_summary(
            value=value_scores,
            health=health_scores,
            earnings=earnings_scores,
            safety=safety_scores,
        )

        prompt_text = BUFFETT_SYSTEM_PROMPT.format(
            symbol=symbol,
            quantitative_summary=quant_summary,
            fundamentals_report=state.get("fundamentals_report", ""),
        )

        # 5. Invoke LLM (plain, no bind_tools)
        response = llm.invoke(prompt_text)

        # 6. Parse structured signal
        signal = parse_persona_signal(response.content, "warren_buffett")

        # 7. Log and return
        logger.info(
            "✅ Warren Buffett: %s signal for %s (confidence: %d)",
            signal.get("signal", "N/A"),
            symbol,
            signal.get("confidence", 0),
        )

        return {
            "messages": [AIMessage(content=response.content)],
            "persona_signals": {"warren_buffett": signal},
        }

    return warren_buffett_node
