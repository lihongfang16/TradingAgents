from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        trader_decision = state["trader_investment_plan"]

        prompt = f"""作为激进型风险分析师，你的角色是积极倡导高回报、高风险机会，强调大胆策略和竞争优势。在评估交易员的决策或计划时，密切关注潜在上行空间、增长潜力和创新收益——即使这些伴随着更高的风险。利用提供的市场数据和情绪分析加强你的论点，并挑战对立观点。具体而言，直接回应保守派和中立派分析师提出的每个观点，用数据驱动的反驳和有说服力的推理进行反击。突出他们可能错过关键机会的地方，或他们的假设可能过于保守的地方。以下是交易员的决策：

{trader_decision}

你的任务是创建一个令人信服的案例来支持交易员的决策，通过质疑和批评保守派和中立派的立场，证明为什么你的高回报视角提供了最佳前进路径。将以下来源的洞察纳入你的论点：

市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新国际新闻：{news_report}
公司基本面报告：{fundamentals_report}
当前对话历史：{history} 保守派分析师的最后论点：{current_conservative_response} 中立派分析师的最后论点：{current_neutral_response}。如果其他观点还没有回应，根据可用数据提出你自己的论点。

Engage actively by addressing any specific concerns raised, refuting the weaknesses in their logic, and asserting the benefits of risk-taking to outpace market norms. Maintain a focus on debating and persuading, not just presenting data. Challenge each counterpoint to underscore why a high-risk approach is optimal. Output conversationally as if you are speaking without any special formatting.""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Aggressive Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
