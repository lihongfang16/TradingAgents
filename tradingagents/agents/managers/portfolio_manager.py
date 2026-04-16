from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction


def create_portfolio_manager(llm, memory):
    def portfolio_manager_node(state) -> dict:

        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        trader_plan = state["investment_plan"]

        cost_price = state.get("cost_price")
        position_shares = state.get("position_shares")
        target_position_pct = state.get("target_position_pct")
        reference_capital = state.get("reference_capital")

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

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

**背景：**
- 交易员提出的计划：**{trader_plan}**
- 过去决策的经验教训：**{past_memory_str}**
{position_section}
**必需输出结构：**
1. **评级**：明确给出买入/增持/持有/减持/卖出之一。
2. **执行摘要**：涵盖入场策略、仓位规模、关键风险水平和时间范围的简洁行动计划。
3. **投资论点**：基于分析师辩论和过去反思的详细推理。

---

**风险分析师辩论历史：**
{history}

---

要果断，每个结论都要基于分析师的具体证据。{get_language_instruction()}"""

        response = llm.invoke(prompt)

        new_risk_debate_state = {
            "judge_decision": response.content,
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
            "final_trade_decision": response.content,
        }

    return portfolio_manager_node
