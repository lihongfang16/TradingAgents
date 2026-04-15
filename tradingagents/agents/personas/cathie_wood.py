"""Cathie Wood persona agent — Disruptive innovation, exponential growth."""
import logging
from typing import Any, Callable, Dict

from langchain_core.messages import AIMessage

from tradingagents.agents.personas.base_persona import (
    format_quantitative_summary,
    parse_persona_signal,
)
from tradingagents.agents.personas.scoring import (
    calc_growth_metrics,
    calc_momentum_metrics,
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


WOOD_SYSTEM_PROMPT = """你现在是凯瑟琳·伍德(Cathie Wood)，ARK Invest创始人，以投资颠覆式创新而闻名。

投资哲学：
- 寻找具有颠覆性创新潜力的公司，关注未来5年的增长前景
- 营收增长率是最重要的指标——加速增长比绝对水平更重要
- 研发投入强度反映公司的创新能力（R&D/Revenue > 15%为优）
- 关注总可寻址市场(TAM)的扩张潜力
- 平台经济、网络效应和规模优势是关键价值驱动因素
- 估值应基于未来增长的折现，而非当前利润（DCF with high growth assumptions）
- 在A股市场特别关注：科创板/创业板的成长特性、专精特新政策、国产替代主题
- 不要被短期估值指标（PE/PB）吓到——创新公司的价值在未来

当前分析股票：{symbol}

## 量化分析数据
{quantitative_summary}

## 基本面报告摘要
{fundamentals_report}

请基于以上数据，以伍德的颠覆式创新视角进行分析：
1. 这家公司的营收增长是否在加速？
2. 研发投入强度是否表明持续创新能力？
3. 公司是否处于具有长期增长潜力的赛道？
4. 从5年视角看，当前估值是否合理？

请以JSON格式输出你的判断：
```json
{{
    "signal": "bullish/bearish/neutral",
    "confidence": 0-100,
    "reasoning": "简短理由（200字以内）",
    "key_metrics": {{}}
}}
```"""


def create_cathie_wood(llm) -> Callable:
    """Create a Cathie Wood persona node for LangGraph."""

    def cathie_wood_node(state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["company_of_interest"]

        # 1. Fetch data
        adapter = _get_adapter()
        metrics_data = adapter.get_financial_metrics(symbol)
        income_stmt = adapter.get_income_statement(symbol)
        prices = adapter.get_prices(symbol)

        # 2. Quantitative scoring
        # Pass ENTIRE metrics_data (with "quarters") for multi-quarter trend analysis
        try:
            growth = calc_growth_metrics(metrics_data)
        except Exception:
            logger.warning("⚠️ Wood: 成长指标计算失败")
            growth = {}

        try:
            momentum = calc_momentum_metrics(prices)
        except Exception:
            logger.warning("⚠️ Wood: 动量指标计算失败")
            momentum = {}

        # Compute R&D intensity from income statement
        rd_intensity = 0.0
        if income_stmt:
            revenue = float(income_stmt.get("revenue", 0) or 0)
            rd_expenses = float(income_stmt.get("rd_expenses", 0) or 0)
            if revenue > 0:
                rd_intensity = rd_expenses / revenue

        # Current price
        current_price = (
            float(prices["close"].iloc[-1])
            if prices is not None and len(prices) > 0
            else 0.0
        )

        # 3. Build prompt with quantitative data
        quant_summary = format_quantitative_summary(
            growth=growth,
            momentum=momentum,
            innovation={"rd_intensity": rd_intensity},
            current_price={"price": current_price},
        )
        prompt_text = WOOD_SYSTEM_PROMPT.format(
            symbol=symbol,
            quantitative_summary=quant_summary,
            fundamentals_report=state.get("fundamentals_report", ""),
        )

        # 4. Invoke LLM (plain, no bind_tools)
        response = llm.invoke(prompt_text)

        # 5. Parse structured signal
        signal = parse_persona_signal(response.content, "cathie_wood")

        # 6. Log and return
        logger.info(
            "✅ Cathie Wood: %s signal for %s (confidence: %d)",
            signal.get("signal", "N/A"),
            symbol,
            signal.get("confidence", 0),
        )

        return {
            "messages": [AIMessage(content=response.content)],
            "persona_signals": {"cathie_wood": signal},
        }

    return cathie_wood_node
