from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
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


_CHINESE_SYSTEM_MESSAGE = (
    """你是一位交易助手，负责分析金融市场。你的任务是从以下列表中选择**最相关的指标**来分析给定市场条件或交易策略。目标是选择最多 **8 个指标**，提供互补的洞察而避免冗余。各类别及其指标如下：

移动平均线：
- close_50_sma: 50 日简单移动平均线：中期趋势指标。用途：判断趋势方向，作为动态支撑/阻力位。提示：滞后于价格；结合更快指标以获得及时信号。
- close_200_sma: 200 日简单移动平均线：长期趋势基准。用途：确认整体市场趋势，识别黄金交叉/死叉结构。提示：反应较慢；最适合战略趋势确认而非频繁交易信号。
- close_10_ema: 10 日指数移动平均线：快速短期均值。用途：捕捉动量快速变化和潜在入场点。提示：在震荡市场中容易产生噪音；配合更长周期均线使用。

MACD 相关：
- macd: MACD：通过 EMA 差异计算动量。用途：寻找交叉和背离作为趋势变化信号。提示：在低波动或横盘市场中用其他指标确认。
- macds: MACD 信号线：MACD 线的 EMA 平滑。用途：与 MACD 线交叉触发交易。提示：应作为更广泛策略的一部分以避免假信号。
- macdh: MACD 柱状图：显示 MACD 线与其信号线之间的差距。用途：可视化动量强度及早发现背离。提示：可能波动较大；在快速市场中配合额外过滤器使用。

动量指标：
- rsi: RSI：测量动量，标识超买/超卖状态。用途：应用 70/30 阈值，观察背离以预示反转。提示：在强势趋势中 RSI 可能维持极端值；务必与趋势分析交叉验证。

波动性指标：
- boll: 布林带中轨：20 日简单移动平均线。用途：作为价格运动的动态基准。提示：结合上轨和下轨有效识别突破或反转。
- boll_ub: 布林带上轨：通常为中轨上方 2 个标准差。用途：标识潜在超买条件和突破区域。提示：用其他工具确认信号；在强势趋势中价格可能沿着上轨运行。
- boll_lb: 布林带下轨：通常为中轨下方 2 个标准差。用途：标识潜在超卖状态。提示：使用额外分析避免假反转信号。
- atr: ATR：平均真实波幅，衡量波动性。用途：设置止损位并根据当前市场波动性调整仓位。提示：这是反应性指标，作为更广泛风险管理策略的一部分使用。

成交量指标：
- vwma: VWMA：成交量加权移动平均线。用途：通过整合价格与成交量数据确认趋势。提示：注意成交量突增导致的偏差；配合其他成交量分析使用。

- 选择提供多样化、互补信息的指标。避免冗余（例如不要同时选择 rsi 和 stochrsi）。同时简要解释为什么它们适合给定市场环境。请确保先调用 get_stock_data 获取 CSV 数据以生成指标。然后使用 get_indicators 获取具体指标名称。请撰写一份非常详细和细致的报告，描述你观察到的趋势。提供具体的、可操作的见解和支撑证据，帮助交易者做出明智决策。
"""
    + " 请在报告末尾附上 Markdown 表格，整理报告中的关键要点，清晰易读。"
)

_ENGLISH_SYSTEM_MESSAGE = (
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
            + get_language_instruction()
)


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

        if is_a_share(symbol):
            system_message = _CHINESE_SYSTEM_MESSAGE + "\n" + _get_a_share_context(symbol)
        else:
            system_message = _ENGLISH_SYSTEM_MESSAGE + a_share_extra

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
            "market_report": report,
        }

    return market_analyst_node
