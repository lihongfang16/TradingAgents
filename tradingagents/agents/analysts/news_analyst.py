import logging
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from typing import Annotated
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
)
from tradingagents.dataflows.interface import is_a_share

logger = logging.getLogger(__name__)


def _fetch_ashare_news(symbol: str, limit: int = 10) -> str:
    """
    通过 AkShare 获取 A 股新闻，格式化为文本返回。

    Args:
        symbol: 股票代码 (6位数字)
        limit: 最大返回条数

    Returns:
        str: 格式化的新闻文本
    """
    try:
        import akshare as ak
    except ImportError:
        return "⚠️ AkShare 未安装，无法获取 A 股新闻。请运行: pip install akshare"

    try:
        # 标准化代码：去除交易所前缀，补零
        s = str(symbol).strip().upper()
        for prefix in ("SZ", "SH", "BJ"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        s = s.zfill(6)

        df = ak.stock_news_em(symbol=s)

        if df is None or df.empty:
            return f"未找到 {s} 的相关新闻。"

        df = df.head(limit)

        lines = [f"## {s} 相关新闻 (共 {len(df)} 条)\n"]
        for i, row in enumerate(df.iterrows(), 1):
            title = row[1].get("标题", "")
            content = row[1].get("内容", "")
            source = row[1].get("来源", "")
            pub_time = row[1].get("发布时间", "")
            lines.append(f"### {i}. {title}")
            if pub_time:
                lines.append(f"- 发布时间: {pub_time}")
            if source:
                lines.append(f"- 来源: {source}")
            if content:
                lines.append(f"- 摘要: {content}")
            lines.append("")

        result = "\n".join(lines)
        logger.info(f"✅ 获取 A 股新闻 {s}: {len(df)} 条")
        return result

    except Exception as e:
        logger.error(f"❌ 获取 A 股新闻失败 {symbol}: {e}")
        return f"获取 {symbol} 新闻时出错: {e}"


@tool
def get_ashare_news(
    ticker: Annotated[str, "A 股股票代码，如 000001、600519"],
    limit: Annotated[int, "返回新闻条数"] = 10,
) -> str:
    """
    获取 A 股个股的中文新闻资讯。
    数据来源：东方财富网（通过 AkShare）。

    Args:
        ticker (str): A 股股票代码，如 "000001"、"600519"
        limit (int): 最大返回条数，默认 10
    Returns:
        str: 格式化的新闻内容，包含标题、来源、时间和摘要
    """
    return _fetch_ashare_news(ticker, limit)


# A 股系统提示词（中文）
_ASHARE_SYSTEM_MESSAGE = (
    "你是一名新闻研究员，负责分析中国 A 股市场的最新新闻和市场趋势。"
    "请撰写一份全面的中文报告，涵盖过去一周内与目标股票相关的新闻和市场动态。"
    "请使用可用工具："
    "get_ashare_news(ticker, limit) 用于获取 A 股个股的中文新闻，"
    "get_news(ticker, start_date, end_date) 用于补充搜索，"
    "get_global_news(curr_date, look_back_days, limit) 用于获取宏观经济和全球市场新闻。"
    "请提供具体、可操作的见解和支撑证据，帮助交易者做出明智的决策。"
    "请用中文撰写报告。"
    + " 报告末尾请附上 Markdown 表格，整理报告中的关键要点，清晰易读。"
)


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        symbol = state["company_of_interest"]
        instrument_context = build_instrument_context(symbol)
        a_share = is_a_share(symbol)

        if a_share:
            tools = [
                get_ashare_news,
                get_news,
                get_global_news,
            ]
            system_message = _ASHARE_SYSTEM_MESSAGE
        else:
            tools = [
                get_news,
                get_global_news,
            ]
            system_message = (
                "You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(query, start_date, end_date) for company-specific or targeted news searches, and get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
                + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
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
            "news_report": report,
        }

    return news_analyst_node
