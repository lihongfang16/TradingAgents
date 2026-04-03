# tradingagents/agents/ — Agent System

## OVERVIEW

11 specialized LLM-powered agents across 6 sub-packages, each created by factory functions returning LangGraph node functions.

## STRUCTURE

```
agents/
├── analysts/          # 4 analyst types with tool-use capabilities
│   ├── market_analyst.py         # Technical analysis, A-share price limit detection
│   ├── social_media_analyst.py   # Sentiment analysis via get_news
│   ├── news_analyst.py           # News analysis, A-share AkShare news integration
│   └── fundamentals_analyst.py   # Financial statements, balance sheet, cashflow
├── researchers/       # Bull/bear debate team
│   ├── bull_researcher.py        # Bullish thesis from all analyst reports
│   └── bear_researcher.py        # Bearish counter-thesis
├── managers/          # Decision makers
│   ├── research_manager.py       # Judges bull/bear debate → investment_plan
│   └── portfolio_manager.py      # Final 5-tier rating → final_trade_decision
├── trader/            # Investment plan composer
│   └── trader.py                 # Synthesizes all reports → trader_investment_plan
├── risk_mgmt/         # 3-way risk debate
│   ├── aggressive_debator.py     # High-reward advocate
│   ├── conservative_debator.py   # Capital preservation advocate
│   └── neutral_debator.py        # Balanced perspective
└── utils/             # Shared infrastructure
    ├── agent_states.py           # AgentState, InvestDebateState, RiskDebateState
    ├── memory.py                 # FinancialSituationMemory (BM25, offline)
    ├── agent_utils.py            # build_instrument_context(), create_msg_delete()
    ├── core_stock_tools.py       # get_stock_data @tool
    ├── fundamental_data_tools.py # get_fundamentals, balance_sheet, etc.
    ├── news_data_tools.py        # get_news, get_global_news @tools
    └── technical_indicators_tools.py  # get_indicators @tool
```

## FACTORY PATTERN

Every agent is created by a `create_<role>(llm, memory=None)` function that returns a LangGraph node function:
```python
def create_market_analyst(llm) -> Callable:
    # Returns async function compatible with LangGraph StateGraph
```

Register new agents in `agents/__init__.py` exports.

## CUSTOM ROLE AGENTS (EXTENSIBILITY)

Users can define custom agent roles beyond the built-in 11. Steps:

1. **Create agent file**: `agents/<role>/custom_<role>.py` — follow `create_<role>(llm, memory=None)` factory pattern
2. **Register export**: Add to `agents/__init__.py` exports
3. **Add state fields**: Extend `AgentState` in `utils/agent_states.py` as needed
4. **Register tools**: Add `@tool` in `agents/utils/`, update `dataflows/interface.py` routing
5. **Wire into graph**: Add node + edges in `graph/setup.py`, `graph/conditional_logic.py`
6. **Use custom tools**: Register in `dataflows/china_data_manager.py` or `dataflows/interface.py` for A-share data routing

- **Market Analyst**: `_get_price_limit()` detects 创业板/科创板 ±20% vs 主板 ±10%; `_get_a_share_context()` fetches realtime quote for 涨跌停 analysis
- **News Analyst**: Includes `get_ashare_news` tool using AkShare `stock_news_em`
- **Bilingual prompts**: Chinese system prompts when `is_a_share(symbol)` is True, English otherwise
- **Symbol context**: `build_instrument_context()` preserves exchange suffixes (SZ/SH/BJ)

## EXTENSIBILITY

Custom agents should be designed for composability:

- **Agent factory signature**: `create_<role>(llm, memory=None)` → returns LangGraph node function
- **State fields**: Add custom fields to `AgentState` as needed
- **Tool binding**: Register tools in `dataflows/interface.py` via `TOOLS_CATEGORIES`/`VENDOR_METHODS`
- **Graph registration**: Add node in `graph/setup.py`, register conditional edges in `graph/conditional_logic.py`
- **Custom new LLM**: Extend `llm_clients/factory.py`, register new provider class

### Custom Agent Example

```python
# 1. Create file: agents/<role>/custom_analyst.py
def create_custom_analyst(llm, memory=None) -> Callable:
    tools = [...]
  # 2. Return LangGraph node function
    # 3. Handle state read/write
    # 4. Register in agents/__init__.py

from tradingagents.agents.custom_analyst import create_custom_analyst
```

```python
# 5. Add node in graph/setup.py
from tradingagents.graph.setup import GraphSetup
# ...
from tradingagents.agents import create_custom_analyst

# In GraphSetup.__init__():
    self.graph.add_node("custom_analyst", create_custom_analyst(llm))
    self.graph.add_conditional_edges("custom_analyst", ...)
````
```

| Task | Where | Isolation Method |
|------|------|-----------------|
| Add custom agent | `agents/<role>/` | New file, register `agents/__init__.py` exports | Add node in `graph/setup.py` |
| Change graph flow | `graph/setup.py` nodes/edges | Only | Add conditional edge in `graph/conditional_logic.py` |
| Add custom data provider | `dataflows/<provider>.py`, register in `china_data_manager.py` |
| Add custom tool | `agents/utils/<new_file>`, register in `dataflows/interface.py` tool routing |
| Add custom LLM | `llm_clients/<provider>.py`, register in `factory.py` |- All agents access their tools via `@tool` decorators in `utils/`
- Analysts read/write to `AgentState` fields (e.g., `market_report`, `sentiment_report`)
- Researchers and managers use `FinancialSituationMemory` for past-trade learning
- `create_msg_delete()` clears LangGraph messages after each analyst node (Anthropic compat)


