"""Stanley Druckenmiller persona agent — Macro momentum, asymmetric risk-reward."""
import logging
from typing import Any, Callable, Dict

from langchain_core.messages import AIMessage

from tradingagents.agents.personas.base_persona import (
    format_quantitative_summary,
    parse_persona_signal,
)
from tradingagents.agents.personas.scoring import (
    calc_momentum_metrics,
    calc_volatility_metrics,
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


DRUCKENMILLER_SYSTEM_PROMPT = """你现在是斯坦利·德鲁肯米勒(Stanley Druckenmiller)，传奇宏观对冲基金经理。你在量子基金与索罗斯合作期间创造了惊人的投资回报。

投资哲学：
- 自上而下的宏观分析：先看大势，再选个股
- 趋势是你的朋友——不要对抗市场趋势
- 关注技术指标：均线交叉（SMA20/SMA50/SMA200）、RSI、MACD
- 成交量是价格趋势的确认指标
- 追求不对称的风险回报比——潜在收益远大于潜在损失
- 当趋势结束时果断止损，绝不恋战
- 在A股市场特别关注：北向资金流向趋势、板块轮动速度、政策风口变化
- 动态调整仓位，集中持仓于高确信度标的

当前分析股票：{symbol}

## 量化分析数据
{quantitative_summary}

## 基本面报告摘要
{fundamentals_report}

请基于以上数据，以德鲁肯米勒的宏观趋势视角进行分析：
1. 当前价格趋势如何？（均线排列、MACD方向、RSI水平）
2. 成交量是否支撑价格趋势？
3. 波动率水平是否意味着风险或机会？
4. 从风险回报比的角度看，当前是否是好的入场时机？

请以JSON格式输出你的判断：
```json
{{
    "signal": "bullish/bearish/neutral",
    "confidence": 0-100,
    "reasoning": "简短理由（200字以内）",
    "key_metrics": {{}}
}}
```"""


def create_stanley_druckenmiller(llm) -> Callable:
    """Create a Stanley Druckenmiller persona node for LangGraph."""

    def stanley_druckenmiller_node(state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["company_of_interest"]

        # 1. Fetch data
        adapter = _get_adapter()
        prices = adapter.get_prices(symbol)
        metrics_data = adapter.get_financial_metrics(symbol)

        # 2. Quantitative scoring
        try:
            momentum = calc_momentum_metrics(prices)
        except Exception:
            logger.warning("⚠️ Druckenmiller: 动量指标计算失败")
            momentum = {}

        try:
            volatility = calc_volatility_metrics(prices)
        except Exception:
            logger.warning("⚠️ Druckenmiller: 波动率指标计算失败")
            volatility = {}

        # Current price
        current_price = (
            float(prices["close"].iloc[-1])
            if prices is not None and len(prices) > 0
            else 0.0
        )

        # 3. Build prompt with quantitative data
        quant_summary = format_quantitative_summary(
            momentum=momentum,
            volatility=volatility,
            current_price={"price": current_price},
        )
        prompt_text = DRUCKENMILLER_SYSTEM_PROMPT.format(
            symbol=symbol,
            quantitative_summary=quant_summary,
            fundamentals_report=state.get("fundamentals_report", ""),
        )

        # 4. Invoke LLM (plain, no bind_tools)
        response = llm.invoke(prompt_text)

        # 5. Parse structured signal
        signal = parse_persona_signal(response.content, "stanley_druckenmiller")

        # 6. Log and return
        logger.info(
            "✅ Druckenmiller: %s signal for %s (confidence: %d)",
            signal.get("signal", "N/A"),
            symbol,
            signal.get("confidence", 0),
        )

        return {
            "messages": [AIMessage(content=response.content)],
            "persona_signals": {"stanley_druckenmiller": signal},
        }

    return stanley_druckenmiller_node
