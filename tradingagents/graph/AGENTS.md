# tradingagents/graph/ — LangGraph Orchestration

## OVERVIEW

Builds and executes the LangGraph StateGraph that orchestrates all 11 agents through analyst chain → bull/bear debate → trader → risk debate → portfolio manager.

## STRUCTURE

```
graph/
├── trading_graph.py      # TradingAgentsGraph — main class, init LLMs/memories, propagate(), reflect()
├── setup.py              # GraphSetup — builds StateGraph with nodes and edges
├── conditional_logic.py  # ConditionalLogic — debate continuation, tool routing
├── propagation.py        # Propagator — creates initial AgentState, configures recursion limits
├── reflection.py         # Reflector — post-trade P&L reflection for each agent role
└── signal_processing.py  # SignalProcessor — extracts 5-tier rating from signal text
```

## GRAPH FLOW

```
[Market Analyst] → [Social Analyst] → [News Analyst] → [Fundamentals Analyst]
    ↓ (sequential; each has tool-use conditional edge)
[Bull Researcher] ←→ [Bear Researcher]
    ↓ (debate loop: 2 × max_debate_rounds turns)
[Research Manager] → produces investment_plan
    ↓
[Trader] → produces trader_investment_plan
    ↓
[Aggressive] ←→ [Conservative] ←→ [Neutral]
    ↓ (3-way rotation: 3 × max_risk_discuss_rounds turns)
[Portfolio Manager] → produces final_trade_decision → END
```

## KEY SYMBOLS

| Symbol | Role |
|--------|------|
| `TradingAgentsGraph` | Orchestrator — `propagate()` streams graph, `reflect_and_remember()` updates BM25 memory |
| `GraphSetup` | Wires nodes to StateGraph: `add_node()` for each agent, `add_conditional_edges()` for debates/tools |
| `ConditionalLogic` | `should_continue_debate()` cycles bull↔bear; `should_continue_risk_analysis()` cycles aggressive→conservative→neutral |
| `Propagator` | Initializes `AgentState`, `InvestDebateState`, `RiskDebateState`; sets `max_recur_limit=300` |
| `Reflector` | Per-role reflection methods that extract situation → LLM reflection → update `FinancialSituationMemory` |
| `SignalProcessor` | `process_signal()` uses `quick_think_llm` to extract BUY/OVERWEIGHT/HOLD/UNDERWEIGHT/SELL |

## CONVENTIONS

- Dual-LLM: `deep_think_llm` for Research Manager + Portfolio Manager; `quick_think_llm` for all others
- Agent state flows through `AgentState` (MessagesState subclass) with typed debate sub-states
- After each analyst node, `create_msg_delete()` clears messages (Anthropic compatibility)
51: - Recursion limit configurable via `DEFAULT_CONFIG["max_recur_limit"]`
52: 
53: ## NOTES
54: 
55: - Debate round counts: `2 × max_debate_rounds` for bull/bear, `3 × max_risk_discuss_rounds` for risk
56: - `reflection.py` is called separately via `reflect_and_remember()`, not part of the graph itself
57: - `signal_processing.py` runs outside the graph after `propagate()` completes
58: - **UPSTREAM MERGE NOTE**: `setup.py` and `conditional_logic.py` are the most merge-sensitive files. Custom agents should minimize changes here — add nodes/edges only, don't restructure.
