from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        trader_decision = state["trader_investment_plan"]

        prompt = f"""作为中立型风险分析师，你的角色是提供平衡的视角，权衡交易员决策或计划的潜在收益和风险。你优先考虑全面的方法，在评估优势和劣势的同时考虑更广泛的市场趋势、潜在经济转变和多元化策略。以下是交易员的决策：

{trader_decision}

你的任务是挑战激进派和保守派分析师，指出每个观点可能在哪些方面过于乐观或过于谨慎。利用以下数据来源的洞察，支持温和、可持续的策略来调整交易员的决策：

市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新国际新闻：{news_report}
公司基本面报告：{fundamentals_report}
当前对话历史：{history} 激进派分析师的最后回应：{current_aggressive_response} 保守派分析师的最后回应：{current_conservative_response}。如果其他观点还没有回应，根据可用数据提出你自己的论点。

Engage actively by analyzing both sides critically, addressing weaknesses in the aggressive and conservative arguments to advocate for a more balanced approach. Challenge each of their points to illustrate why a moderate risk strategy might offer the best of both worlds, providing growth potential while safeguarding against extreme volatility. Focus on debating rather than simply presenting data, aiming to show that a balanced view can lead to the most reliable outcomes. Output conversationally as if you are speaking without any special formatting.""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Neutral Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
