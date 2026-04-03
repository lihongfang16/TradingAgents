from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction, get_news
from tradingagents.dataflows.config import get_config


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        # Skip if sentiment report already exists (from cache)
        if state.get("sentiment_report"):
            return {
                "messages": [],
                "sentiment_report": state["sentiment_report"],
            }

        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
        ]

        system_message = (
            "你是一位社交媒体和公司特定新闻研究员/分析师，负责分析过去一周特定公司的社交媒体帖子、最新公司新闻和公众情绪。你将获得公司名称，目标是在查看社交媒体上人们的讨论、分析每日情绪数据以及查看近期公司新闻后，撰写一份详细的报告，阐述你对该公司当前状态的的分析、见解以及对交易者和投资者的影响。使用 get_news(query, start_date, end_date) 工具搜索公司特定新闻和社交媒体讨论。尽可能涵盖所有来源，从社交媒体到情绪数据到新闻。提供具体的、可操作的见解和支撑证据，帮助交易者做出明智的决策。"
            + " 请在报告末尾附上 Markdown 表格，整理报告中的关键要点，清晰易读。"
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "sentiment_report": report,
        }

    return social_media_analyst_node
