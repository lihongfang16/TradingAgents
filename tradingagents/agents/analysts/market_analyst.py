from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_stock_data,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.interface import is_a_share, china_manager


def _get_price_limit(symbol: str) -> float:
    """Get price limit percentage for A-share.

    创业板 (301xxx, 303xxx) and 科创板 (688xxx): ±20%
    主板 and others: ±10%
    """
    code = symbol
    # Strip exchange prefixes
    for prefix in ("SZ", "SH", "BJ"):
        if code.upper().startswith(prefix):
            code = code[2:]
            break
    if code.startswith(("301", "303", "688")):
        return 0.20
    return 0.10


def _get_a_share_context(symbol: str) -> str:
    """Build A-share specific market context for the system prompt.

    Uses ChinaDataManager to fetch real-time quote for 涨跌停 detection
    and enriches the prompt with A-share specific analysis guidance.
    """
    try:
        quote = china_manager.get_realtime_quote(symbol)
    except Exception:
        quote = None

    price_limit = _get_price_limit(symbol)
    limit_pct = f"{price_limit * 100:.0f}%"

    context_parts = [
        f"## A 股特殊分析规则",
        f"- 当前股票为 **A 股**，涨跌停限制为 **±{limit_pct}**",
        f"- 涨停判断: 当日涨跌幅 >= {price_limit * 100 - 0.5:.1f}% 视为涨停",
        f"- 跌停判断: 当日涨跌幅 <= -{price_limit * 100 - 0.5:.1f}% 视为跌停",
        f"- A 股 T+1 制度: 当日买入的股票次日才能卖出",
        f"- A 股无盘前盘后交易，交易时间为 9:30-11:30, 13:00-15:00",
    ]

    if quote:
        change_pct = quote.get("change_percent") or quote.get("pct_chg") or quote.get("涨跌幅")
        if change_pct is not None:
            try:
                change_pct = float(change_pct)
                threshold = price_limit * 100 - 0.5
                if change_pct >= threshold:
                    context_parts.append(f"- ⚠️ **涨停预警**: 当前涨跌幅 {change_pct:.2f}%，接近或触及涨停！")
                elif change_pct <= -threshold:
                    context_parts.append(f"- ⚠️ **跌停预警**: 当前涨跌幅 {change_pct:.2f}%，接近或触及跌停！")
                else:
                    context_parts.append(f"- 当前涨跌幅: {change_pct:.2f}%，距离涨停 {price_limit * 100 - change_pct:.2f}%，距离跌停 {-price_limit * 100 - change_pct:.2f}%")
            except (ValueError, TypeError):
                pass

    context_parts.extend([
        "",
        "### A 股技术分析注意事项",
        "- A 股 K 线数据已通过 ChinaDataManager 获取，包含完整的 OHLCV 数据",
        "- 使用 stockstats 计算技术指标（MACD、RSI、布林带等）",
        "- A 股涨跌停板会导致量能异常放大，分析量价关系时注意区分",
        "- A 股存在板块联动效应，注意同板块个股走势",
    ])

    return "\n".join(context_parts)


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        # Detect A-share and build additional context
        symbol = state["company_of_interest"]
        a_share_extra = ""
        if is_a_share(symbol):
            a_share_extra = "\n" + _get_a_share_context(symbol)

        tools = [
            get_stock_data,
            get_indicators,
        ]

        base_system_message = (
            """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context. When you tool call, please use the exact name of the indicators provided above as they are defined parameters, otherwise your call will fail. Please make sure to call get_stock_data first to retrieve the CSV that is needed to generate indicators. Then use get_indicators with the specific indicator names. Write a very detailed and nuanced report of the trends you observe. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
        )

        system_message = base_system_message + a_share_extra

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
            "market_report": report,
        }

    return market_analyst_node
