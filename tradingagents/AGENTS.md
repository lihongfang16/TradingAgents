# tradingagents/ — Core Library

## OVERVIEW

Multi-agent LLM trading engine: agents, LangGraph orchestration, A-share data sources, and LLM client abstraction layer.

## STRUCTURE

```
tradingagents/
├── agents/           # 11 agent implementations in 6 sub-packages
├── graph/            # LangGraph StateGraph — nodes, edges, conditional routing
├── dataflows/        # Data provider abstraction with A-share failover chain
├── llm_clients/      # Multi-LLM factory (OpenAI/Anthropic/Google/xAI/Ollama/OpenRouter)
├── core/             # AnalysisRunner — wraps graph for API/CLI consumption
└── default_config.py # DEFAULT_CONFIG dict: LLM provider, debate rounds, data vendors
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add agent | `agents/<role>/new_agent.py` → register in `agents/__init__.py` |
| Change graph flow | `graph/setup.py` (nodes/edges), `graph/conditional_logic.py` (routing) |
| Add data source | `dataflows/new_provider.py` → register in `china_data_manager.py` |
| Add LLM provider | `llm_clients/new_client.py` → register in `factory.py` |
| Configure defaults | `default_config.py` — llm_provider, deep/quick models, data vendors |
| Wrap for API/CLI | `core/analysis_runner.py` — fast_mode, progress callbacks |

## KEY INTERFACES

- `TradingAgentsGraph.propagate(symbol, date)` → `(state, signal)` — main entry point
- `route_to_vendor(symbol, tool_category)` → auto-routes A-share vs global
- `create_llm_client(provider, model, base_url)` → `BaseLLMClient` subclass
- `DEFAULT_CONFIG` dict — copy and override for custom configurations

## CONVENTIONS

- `__init__.py` sets `PYTHONUTF8=1` on import
- Agent factories: `create_<role>(llm, memory=None)` returning a LangGraph node function
- Tools defined via `@tool` decorators in `agents/utils/` (not in a separate tools/ dir)
- Data vendors configured in `DEFAULT_CONFIG["data_vendors"]` and `"tool_vendors"`

## UPSTREAM ISOLATION

This project forks from [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) and regularly merges upstream changes. Follow these principles to minimize merge conflicts:

1. **Custom code lives in separate files/modules** — never merge A-share adaptations into upstream source files
2. **Extending, not modifying** — add new files/sub-packages; don't rewrite upstream files (except `graph/setup.py` which needs node registration)
3. **Hot spots for `graph/setup.py`** — only file where custom agents must nodes must conflict. Minimize changes to this file. Use `add_node()` + `add_edge()` only.
4. **`graph/conditional_logic.py`** — add new `should_continue_*()` routing methods for this file. Don't modify existing routing methods.

