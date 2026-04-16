from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )


def build_full_context(ticker: str, state: dict[str, object]) -> str:
    """Build instrument context enriched with the Market Index Analyst macro report.

    Wraps :func:`build_instrument_context` and, when available, appends the
    ``market_index_report`` produced by the Market Index Analyst so downstream
    analysts can reference macro environment context.

    Args:
        ticker: The stock ticker / instrument identifier.
        state:  The current :class:`AgentState` dict.

    Returns:
        The base instrument context string, optionally suffixed with the macro
        environment summary.
    """
    context = build_instrument_context(ticker)
    macro_report = state.get("market_index_report")
    if macro_report:
        context += (
            "\n\n## 大盘与板块环境概要\n"
            "以下是 Market Index Analyst 提供的宏观环境分析，"
            "请在你的分析中参考这些宏观背景：\n\n"
            f"{macro_report}"
        )
    return context

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
