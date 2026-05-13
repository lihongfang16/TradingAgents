"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        position_section = ""
        if cost_price is not None and position_shares is not None:
            # Compute current position ratio
            current_pct_str = "未计算"
            if reference_capital and reference_capital > 0:
                # Use cost_price as proxy for current price (we don't have live price in state)
                current_pct = (position_shares * cost_price) / reference_capital * 100
                current_pct_str = f"{current_pct:.1f}%"

            target_pct_str = f"{(target_position_pct or 0) * 100:.0f}%"

            position_section = f"""
**用户持仓信息：**
- 持仓成本价：¥{cost_price:.2f}
- 当前持仓股数：{position_shares} 股
- 参考本金：¥{reference_capital or 0:,.0f}
- 当前持仓比例：{current_pct_str}
- 目标仓位比例：{target_pct_str}
- 参考市值：¥{cost_price * position_shares:,.2f}

**持仓相关要求：**
- 基于用户现有持仓成本和仓位，给出具体的操作建议
- 如果建议"增持"或"减持"，必须明确建议的股数和价格区间
- 在回复的最末尾，附上一个 JSON 代码块（如下格式）

```json
{{
  "rating": "买入|增持|持有|减持|卖出",
  "action": "买入|增持|持有|减持|卖出",
  "price_range": "建议操作的价格区间，如 10.50-11.00",
  "target_shares": 建议增减的具体股数（整数），
  "reason": "简要操作理由"
}}
```
"""

        prompt = f"""作为投资组合经理，综合风险分析师的辩论并交付最终交易决策。

{instrument_context}

---

**评级标准**（严格使用其中之一）：
- **买入（Buy）**：强烈信念进入或增加仓位
- **增持（Overweight）**：前景看好，逐步增加敞口
- **持有（Hold）**：维持当前仓位，无需操作
- **减持（Underweight）**：减少敞口，获取部分利润
- **卖出（Sell）**：退出仓位或避免入场

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

要果断，每个结论都要基于分析师的具体证据。{get_language_instruction()}"""

        final_trade_decision = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
        )

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
