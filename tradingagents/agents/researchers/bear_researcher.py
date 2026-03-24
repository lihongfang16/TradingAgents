from langchain_core.messages import AIMessage
import time
import json


def create_bear_researcher(llm, memory):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        prompt = f"""你是一位看空分析师，阐述不投资该股票的理由。你的目标是提出一个合理有据的论点，强调风险、挑战和负面指标。利用提供的研究和数据，突出潜在缺点并有效反驳看涨论点。

需要重点关注的关键点：

- 风险与挑战：突出可能阻碍股票表现的因素，如市场饱和、财务不稳定或宏观经济威胁。
- 竞争劣势：强调弱势，如较弱的市场定位、创新能力下降或来自竞争对手的威胁。
- 负面指标：利用财务数据、市场趋势或近期负面新闻的证据支持你的立场。
- 看涨观点反驳：用具体数据和合理推理批判性分析看涨论点，揭露弱点或过于乐观的假设。
- 互动：以对话风格呈现你的论点，直接与看涨分析师的观点互动，进行有效辩论，而非简单罗列事实。

可用的资源：

市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新国际新闻：{news_report}
公司基本面报告：{fundamentals_report}
辩论对话历史：{history}
看多方最后论点：{current_response}
类似情况的反思和经验教训：{past_memory_str}
利用这些信息提供令人信服的看空论点，反驳看多的主张，并参与展示投资该股票风险和弱点的动态辩论。你还必须回应反思内容，从过去的教训和错误中学习。
"""

        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
