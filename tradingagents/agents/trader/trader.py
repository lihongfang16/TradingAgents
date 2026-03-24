import functools
import time
import json

from tradingagents.agents.utils.agent_utils import build_instrument_context


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "未找到过去的记忆。"

        context = {
            "role": "user",
            "content": f"根据分析师团队的全面分析，这是为 {company_name} 量身定制的投资计划。{instrument_context} 该计划融入了当前技术市场趋势、宏观经济指标和社交媒体情绪的洞察。以此计划为基础评估你的下一个交易决策。\n\n建议投资计划：{investment_plan}\n\n利用这些洞察做出明智和战略性的决策。",
        }

        messages = [
            {
                "role": "system",
                "content": f"""你是一位交易代理，分析市场数据以做出投资决策。根据你的分析，提供买入、卖出或持有的具体建议。以坚定决策结束，并始终以 'FINAL TRANSACTION PROPOSAL: **买入/持有/卖出**' 结尾以确认你的建议。将过去的决策经验应用到分析中以加强分析。以下是你交易过的类似情况的反思和经验教训：{past_memory_str}""",
            },
            context,
        ]

        result = llm.invoke(messages)

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
