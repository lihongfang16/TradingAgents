from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool

from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.dataflows.interface import is_a_share
from tradingagents.dataflows.index_sector_tools import (
    get_index_kline,
    get_sector_kline,
)


_CHINESE_SYSTEM_MESSAGE = """你是一位大盘与板块分析师，负责分析宏观市场环境。你的任务如下：

1. **所属大盘分析（高权重）**：
   - 使用 get_stock_market_and_sector 确定该股票所属大盘
   - 使用 get_index_kline 获取该大盘指数的近 60 日 K 线数据
   - 分析趋势方向、支撑位、压力位
   - 评估大盘环境对该股票的直接影响（顺风/逆风）

2. **其他大盘对比（低权重）**：
   - 使用 get_index_kline 获取其他主要指数（上证指数、创业板指、科创50）近 60 日数据
   - 简要对比走势，指出是否存在背离或共振信号
   - 控制在 200 字以内

3. **所属行业板块分析（高权重）**：
   - 使用 get_stock_market_and_sector 获取所属行业
   - 使用 get_sector_kline 获取该行业板块近 60 日数据
   - 分析板块资金流向、整体强弱
   - 评估该板块内个股的机会和风险

4. **关联板块提及（低权重）**：
   - 根据行业特征，提及 1-2 个上下游或概念板块的近期表现
   - 控制在 150 字以内

请在报告末尾以 Markdown 表格总结：大盘状态（牛市/熊市/震荡）、板块强度（强势/弱势/中性）、对目标股票的影响评估（正面/负面/中性）。

注意：请确保先调用 get_stock_market_and_sector 确定股票所属大盘和行业，再调用 get_index_kline 和 get_sector_kline 获取数据。"""


def create_market_index_analyst(llm):

    def market_index_analyst_node(state):
        # Skip if market index report already exists (from cache)
        if state.get("market_index_report"):
            return {
                "messages": [],
                "market_index_report": state["market_index_report"],
            }

        current_date = state["trade_date"]
        symbol = state["company_of_interest"]
        instrument_context = build_instrument_context(symbol)

        # Call get_stock_market_and_sector directly to build context for the prompt
        from tradingagents.dataflows.index_sector_tools import get_stock_market_and_sector
        market_sector_info = ""
        try:
            info = get_stock_market_and_sector(symbol)
            if info:
                market_sector_info = (
                    f"\n\n## 股票所属市场与行业信息\n"
                    f"- 所属大盘: {info.get('market', '未知')}\n"
                    f"- 所属行业: {info.get('sector', '未知')}\n"
                )
        except Exception:
            pass

        tools = [
            get_index_kline,
            get_sector_kline,
        ]

        system_message = _CHINESE_SYSTEM_MESSAGE + market_sector_info

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
                    " IMPORTANT: When analyzing A-share (Chinese) stocks, always respond in Chinese."
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
            "market_index_report": report,
        }

    return market_index_analyst_node
