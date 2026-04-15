"""Charlie Munger persona agent — Moat analysis, mental models, quality at reasonable price."""
import logging
from typing import Any, Callable, Dict

from langchain_core.messages import AIMessage

from tradingagents.agents.personas.base_persona import (
    format_quantitative_summary,
    parse_persona_signal,
)
from tradingagents.agents.personas.scoring import (
    calc_moat_score,
    calc_financial_health,
    calc_earnings_quality,
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


MUNGER_SYSTEM_PROMPT = """你现在是查理·芒格(Charlie Munger)，伯克希尔·哈撒韦副董事长，沃伦·巴菲特的长期合作伙伴。你以多维思维模型和严格的价值评估著称。

投资哲学：
- 寻找具有持久竞争优势（经济护城河）的公司
- ROIC（投入资本回报率）是最重要的单一指标——高于15%为优
- 关注盈利的可预测性和稳定性——稳定比高增长更有价值
- 毛利率的稳定性反映定价权和竞争壁垒
- 规模效率（营业利润率）反映运营能力
- 以合理的价格买入优秀公司，远胜于以便宜的价格买入普通公司
- 运用多元思维模型避免认知偏差：确认偏误、锚定效应、过度自信
- 在A股市场特别关注：行业集中度反映护城河宽度、品牌溢价（毛利率稳定性）、国企改革对治理的影响

当前分析股票：{symbol}

## 量化分析数据
{quantitative_summary}

## 基本面报告摘要
{fundamentals_report}

请基于以上数据，以芒格的护城河与思维模型视角进行分析：
1. 这家公司是否具有持久的经济护城河？（ROIC、定价权、规模效率）
2. 盈利是否具有可预测性和稳定性？（ROE稳定性、毛利率稳定性）
3. 财务健康和盈余质量如何？
4. 是否存在需要警惕的认知偏差？（过度乐观/悲观）

请以JSON格式输出你的判断：
```json
{{
    "signal": "bullish/bearish/neutral",
    "confidence": 0-100,
    "reasoning": "简短理由（200字以内）",
    "key_metrics": {{}}
}}
```"""


def create_charlie_munger(llm) -> Callable:
    """Create a Charlie Munger persona node for LangGraph."""

    def charlie_munger_node(state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = state["company_of_interest"]

        # 1. Fetch data
        adapter = _get_adapter()
        metrics_data = adapter.get_financial_metrics(symbol)
        income_stmt = adapter.get_income_statement(symbol)
        balance = adapter.get_balance_sheet(symbol)
        cash_flow = adapter.get_cash_flow_statement(symbol)

        # 2. Quantitative scoring
        # Pass ENTIRE metrics_data (with "quarters") for stability analysis
        try:
            moat = calc_moat_score(metrics_data, income_stmt)
        except Exception:
            logger.warning("⚠️ Munger: 护城河评分计算失败")
            moat = {}

        metrics_latest = metrics_data.get("latest", {}) if metrics_data else {}
        try:
            health = calc_financial_health(metrics_latest, balance)
        except Exception:
            logger.warning("⚠️ Munger: 财务健康指标计算失败")
            health = {}

        try:
            quality = calc_earnings_quality(income_stmt, cash_flow)
        except Exception:
            logger.warning("⚠️ Munger: 盈余质量指标计算失败")
            quality = {}

        # Current price (from metrics or 0)
        current_price = float(metrics_latest.get("price", 0) or 0)

        # 3. Build prompt with quantitative data
        quant_summary = format_quantitative_summary(
            moat=moat,
            financial_health=health,
            earnings_quality=quality,
            current_price={"price": current_price},
        )
        prompt_text = MUNGER_SYSTEM_PROMPT.format(
            symbol=symbol,
            quantitative_summary=quant_summary,
            fundamentals_report=state.get("fundamentals_report", ""),
        )

        # 4. Invoke LLM (plain, no bind_tools)
        response = llm.invoke(prompt_text)

        # 5. Parse structured signal
        signal = parse_persona_signal(response.content, "charlie_munger")

        # 6. Log and return
        logger.info(
            "✅ Munger: %s signal for %s (confidence: %d)",
            signal.get("signal", "N/A"),
            symbol,
            signal.get("confidence", 0),
        )

        return {
            "messages": [AIMessage(content=response.content)],
            "persona_signals": {"charlie_munger": signal},
        }

    return charlie_munger_node
