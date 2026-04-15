from langchain_core.messages import AIMessage
import time
import json


def create_bull_researcher(llm, memory):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        persona_report = state.get("persona_report", "")

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        prompt = f"""你是一位看涨分析师，倡导投资该股票。你的任务是构建一个强有力的、基于证据的看涨观点，强调增长潜力、竞争优势和积极市场指标。利用提供的研究和数据，有效解决看空观点并反驳看空论点。

需要重点关注的关键点：
- 增长潜力：突出公司的市场机会、收入预测和可扩展性。
- 竞争优势：强调独特产品、强品牌力或主导市场地位等因素。
- 积极指标：利用财务健康状况、行业趋势和近期正面新闻作为证据。
- 看空观点反驳：用具体数据和合理推理批判性分析看空论点，彻底解决担忧，表明为什么看涨观点具有更强说服力。
- 互动：以一种对话风格呈现你的论点，直接与看空分析师的观点互动，进行有效辩论，而不仅仅是罗列数据。

可用的资源：
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新国际新闻：{news_report}
公司基本面报告：{fundamentals_report}
{f"投资者人设投票报告：{persona_report}" if persona_report else ""}
辩论对话历史：{history}
看空方最后论点：{current_response}
类似情况的反思和经验教训：{past_memory_str}
利用这些信息提供令人信服的看涨论点，反驳看空担忧，并参与展示看涨立场优势的动态辩论。你还必须回应反思内容，从过去的教训和错误中学习。
"""

        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
