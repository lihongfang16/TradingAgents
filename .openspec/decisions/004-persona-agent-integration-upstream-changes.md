# ADR-004: Persona Agent Integration — 上游代码修改记录

## 标题
集成 6 个投资者人设 agent（Buffett / Burry / Taleb / Druckenmiller / Wood / Munger）时对上游代码的修改记录

## 状态
- [x] Proposed

## 背景
项目 fork 自 TauricResearch/TradingAgents。采用 Helper Method Pattern 封装 persona 注册逻辑到 `_register_persona_nodes()`，`setup_graph()` 仅增加 3 行。

## 涉及的上游文件 (9个, 全部纯增量)
1. `agent_states.py` — +2 行 (persona_signals, persona_report)
2. `agents/__init__.py` — +8 行 (persona imports)
3. `graph/propagation.py` — +2 行 (初始状态)
4. `graph/setup.py` — +3 行 setup_graph() + _register_persona_nodes() helper
5. `graph/trading_graph.py` — +5 行 (enable_personas, log fields)
6. `core/analysis_runner.py` — +25 行 (mappings, progress)
7. `agents/researchers/bull_researcher.py` — +3 行 (prompt)
8. `agents/researchers/bear_researcher.py` — +3 行 (prompt)
9. `default_config.py` — +1 行 (enable_personas)

## 未修改的文件
- `graph/conditional_logic.py` — lambda 路由替代
- `dataflows/akshare_provider.py` — adapter 包装
- `dataflows/china_data_manager.py` — 无需改动
- `dataflows/interface.py` — persona 不使用 tool 路由

## 合并恢复清单
1. 确认新文件存在: `financial_data_adapter.py` + `agents/personas/`
2. 检查 `setup.py` 冲突，恢复 `enable_personas` + helper 调用
3. 恢复其余 8 个文件的增量修改

## 一键回退
`TradingAgentsGraph(..., enable_personas=False)` 即可完全跳过。

## 新增文件 (12个)
- `dataflows/financial_data_adapter.py`
- `agents/personas/__init__.py`
- `agents/personas/base_persona.py`
- `agents/personas/scoring.py`
- `agents/personas/warren_buffett.py`
- `agents/personas/michael_burry.py`
- `agents/personas/nassim_taleb.py`
- `agents/personas/stanley_druckenmiller.py`
- `agents/personas/cathie_wood.py`
- `agents/personas/charlie_munger.py`
- `agents/personas/aggregator.py`
- `.openspec/decisions/004-persona-agent-integration-upstream-changes.md`