"""Nassim Taleb persona agent — tail risk, antifragile, convex payoffs, downside protection."""
import logging
from typing import Any, Callable, Dict

from langchain_core.messages import AIMessage

from tradingagents.agents.personas.base_persona import (
    format_quantitative_summary,
    parse_persona_signal,
)
from tradingagents.agents.personas.scoring import (
    calc_financial_health,
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


TALEB_SYSTEM_PROMPT = """你现在是纳西姆·塔勒布(Nassim Nicholas Taleb)，著名风险分析师、《黑天鹅》和《反脆弱》的作者。

投资哲学：
- 市场的核心风险来自不可预测的极端事件（黑天鹅）
- 投资应该在极端波动中获益而非受损（反脆弱性）
- 关注尾部风险：最大回撤、VaR、峰度（肥尾分布）
- 永远不要忽视"未知的未知"——模型无法预测的风险
- 资产负债表的韧性比利润表更重要
- 选择性暴露：收益有上限，损失有下限（凸性策略）
- 在A股市场特别关注：涨跌停板对尾部风险的影响、强制平仓风险、政策驱动的波动性
- 杠杆是脆弱性的放大器

当前分析股票：{symbol}

## 量化分析数据
{quantitative_summary}

## 基本面报告摘要
{fundamentals_report}

请基于以上数据，以塔勒布的风险视角进行分析：
1. 这只股票的尾部风险有多大？（最大回撤、VaR、肥尾程度）
2. 公司资产负债表是否有足够的韧性抵御极端事件？
3. 当前的波动率水平是否意味着隐藏的风险或机会？
4. 从反脆弱的角度看，持有这只股票是否能在极端事件中获益？

请以JSON格式输出你的判断：
```json
{{{{
    "signal": "bullish/bearish/neutral",
    "confidence": 0-100,
    "reasoning": "简短理由（200字以内）",
    "key_metrics": {{{{}}}}
}}}}
```"""


def create_nassim_taleb(llm) -> Callable:
    """Create a Nassim Taleb persona node for LangGraph."""

    def nassim_taleb_node(state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["company_of_interest"]

        # 1. Fetch data — prices are primary for Taleb
        adapter = _get_adapter()

        try:
            prices = adapter.get_prices(symbol)
        except Exception:
            logger.warning("⚠️ Taleb: 获取价格数据失败 %s", symbol)
            prices = None

        try:
            metrics_data = adapter.get_financial_metrics(symbol)
        except Exception:
            logger.warning("⚠️ Taleb: 获取财务指标失败 %s", symbol)
            metrics_data = {}

        try:
            balance_data = adapter.get_balance_sheet(symbol)
        except Exception:
            logger.warning("⚠️ Taleb: 获取资产负债表失败 %s", symbol)
            balance_data = {}

        # 2. Quantitative scoring
        metrics = metrics_data.get("latest", {}) if metrics_data else {}

        try:
            volatility_scores = calc_volatility_metrics(prices)
        except Exception:
            logger.warning("⚠️ Taleb: 波动率指标计算失败 %s", symbol)
            volatility_scores = {}

        try:
            health_scores = calc_financial_health(metrics, balance_data)
        except Exception:
            logger.warning("⚠️ Taleb: 财务健康指标计算失败 %s", symbol)
            health_scores = {}

        # 3. Build prompt with quantitative data
        quant_summary = format_quantitative_summary(
            volatility=volatility_scores,
            health=health_scores,
        )

        prompt_text = TALEB_SYSTEM_PROMPT.format(
            symbol=symbol,
            quantitative_summary=quant_summary,
            fundamentals_report=state.get("fundamentals_report", ""),
        )

        # 4. Invoke LLM (plain, no bind_tools)
        response = llm.invoke(prompt_text)

        # 5. Parse structured signal
        signal = parse_persona_signal(response.content, "nassim_taleb")

        # 6. Log and return
        logger.info(
            "✅ Nassim Taleb: %s signal for %s (confidence: %d)",
            signal.get("signal", "N/A"),
            symbol,
            signal.get("confidence", 0),
        )

        return {
            "messages": [AIMessage(content=response.content)],
            "persona_signals": {"nassim_taleb": signal},
        }

    return nassim_taleb_node
