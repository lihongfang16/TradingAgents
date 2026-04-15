# ADR-003: Market Index Analyst — 上游代码修改记录

## 标题

新增大盘分析师时对上游代码的修改记录，便于上游更新后恢复

## 状态

- [x] Implemented

## 背景

项目 fork 自 TauricResearch/TradingAgents，需要在上游代码文件中做增量修改来注册新的 Market Index Analyst 智能体。这些修改遵循 AGENTS.md 中的上游隔离原则：只做增量（add），不改现有逻辑（modify）。

## 涉及的上游文件

共 5 个上游文件被修改，全部为纯增量改动（+行），无现有逻辑被删除或修改。

## 修改记录

### 1. `tradingagents/agents/utils/agent_states.py`

**改动类型**: 新增字段 (+3 行)

**位置**: `AgentState` 类，`fundamentals_report` 字段之后

```diff
     fundamentals_report: Annotated[str, "Report from the Fundamentals Researcher"]
 
+    # market index analysis step
+    market_index_report: Annotated[str, "Report from the Market Index Analyst"]
+
     # researcher team discussion step
```

**说明**: 新增 `market_index_report` 状态字段，用于存储大盘分析师的输出报告。所有分析师的 report 都遵循 `xxx_report` 命名规范。

---

### 2. `tradingagents/agents/__init__.py`

**改动类型**: 新增 import 和 export (+2 行)

**位置**: 在 `from .analysts.market_analyst import` 之后添加 import，在 `__all__` 列表中添加 export

```diff
 from .analysts.fundamentals_analyst import create_fundamentals_analyst
 from .analysts.market_analyst import create_market_analyst
+from .analysts.market_index_analyst import_market_index_analyst
 from .analysts.news_analyst import create_news_analyst

 __all__ = [
     ...
     "create_fundamentals_analyst",
     "create_market_analyst",
+    "create_market_index_analyst",
     "create_neutral_debator",
```

---

### 3. `tradingagents/graph/conditional_logic.py`

**改动类型**: 新增方法 (+8 行)

**位置**: `should_continue_fundamentals` 方法之后，`should_continue_debate` 方法之前

```diff
             return "Msg Clear Fundamentals"
 
+    def should_continue_market_index(self, state: AgentState):
+        """Determine if market index analysis should continue."""
+        messages = state["messages"]
+        last_message = messages[-1]
+        if last_message.tool_calls:
+            return "tools_market_index"
+        return "Msg Clear Market Index"
+
     def should_continue_debate(self, state: AgentState) -> str:
```

**说明**: 新增条件路由方法。模式与 `should_continue_market`、`should_continue_social` 等完全一致。返回 `"tools_market_index"` 或 `"Msg Clear Market Index"`。

---

### 4. `tradingagents/graph/setup.py`

**改动类型**: 3 处增量修改 (+39 行)

#### 4a. 默认参数修改 (第 44 行)

```diff
-        selected_analysts=["market", "social", "news", "fundamentals"],
+        selected_analysts=["market_index", "market", "social", "news", "fundamentals"],
```

#### 4b. 新增 analyst 注册块 (第 64-72 行)

在 `if "market" in selected_analysts:` 之前插入：

```python
        # Market Index Analyst — registered with explicit names (not via dynamic loop
        # because "market_index".capitalize() would produce "Market_index" not "Market Index")
        if "market_index" in selected_analysts:
            analyst_nodes["market_index"] = create_market_index_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["market_index"] = create_msg_delete()
            tool_nodes["market_index"] = self.tool_nodes["market_index"]
```

#### 4c. 动态循环跳过 market_index (第 127-129 行)

```python
        for analyst_type, node in analyst_nodes.items():
            # market_index uses explicit node names "Market Index Analyst" etc., skip here
            if analyst_type == "market_index":
                continue
```

#### 4d. 显式注册 market_index 节点和边 (第 135-139 行)

在动态循环之后添加：

```python
        # Register Market Index Analyst with explicit names
        if "market_index" in selected_analysts:
            workflow.add_node("Market Index Analyst", analyst_nodes["market_index"])
            workflow.add_node("Msg Clear Market Index", delete_nodes["market_index"])
            workflow.add_node("tools_market_index", tool_nodes["market_index"])
```

#### 4e. START 边处理 (第 159-162 行)

```diff
-        workflow.add_edge(START, f"{first_analyst.capitalize()} Analyst")
+        if first_analyst == "market_index":
+            workflow.add_edge(START, "Market Index Analyst")
+        else:
+            workflow.add_edge(START, f"{first_analyst.capitalize()} Analyst")
```

#### 4f. 循环中 node 名称解析 (第 165-178 行)

```diff
         for i, analyst_type in enumerate(selected_analysts):
-            current_analyst = f"{analyst_type.capitalize()} Analyst"
-            current_tools = f"tools_{analyst_type}"
-            current_clear = f"Msg Clear {analyst_type.capitalize()}"
+            # market_index uses explicit node names
+            if analyst_type == "market_index":
+                current_analyst = "Market Index Analyst"
+                current_tools = "tools_market_index"
+                current_clear = "Msg Clear Market Index"
+                should_continue = "should_continue_market_index"
+            else:
+                current_analyst = f"{analyst_type.capitalize()} Analyst"
+                current_tools = f"tools_{analyst_type}"
+                current_clear = f"Msg Clear {analyst_type.capitalize()}"
+                should_continue = f"should_continue_{analyst_type}"
 
             workflow.add_conditional_edges(
                 current_analyst,
-                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
+                getattr(self.conditional_logic, should_continue),
```

#### 4g. next_analyst 名称解析 (第 177-178 行)

```diff
-                next_analyst = f"{selected_analysts[i+1].capitalize()} Analyst"
+                next_type = selected_analysts[i + 1]
+                next_analyst = "Market Index Analyst" if next_type == "market_index" else f"{next_type.capitalize()} Analyst"
```

**说明**: 为什么不把 `market_index` 放进动态循环？因为 `"market_index".capitalize()` 会返回 `"Market_index"`（Python 只首字母大写），与预期的 `"Market Index"` 不匹配。解决方式是将 `market_index` 显式处理，在动态循环中 `continue` 跳过。

---

### 5. `tradingagents/graph/trading_graph.py`

**改动类型**: 新增 import (+6 行) 和 ToolNode (+8 行)

#### 5a. 新增 import (第 15-20 行)

```diff
 from tradingagents.agents import *
+
+from tradingagents.dataflows.index_sector_tools import (
+    get_stock_market_and_sector,
+    get_index_kline,
+    get_sector_kline,
+)
```

#### 5b. 新增 ToolNode (在 `_create_tool_nodes` 方法的 return dict 中)

```diff
             "fundamentals": ToolNode([...]),
+            "market_index": ToolNode(
+                [
+                    get_stock_market_and_sector,
+                    get_index_kline,
+                    get_sector_kline,
+                ]
+            ),
         }
```

---

## 合并恢复清单

当从上游 `TauricResearch/TradingAgents` 合并更新后，按以下步骤恢复：

1. **确认新文件仍存在**: `tradingagents/dataflows/index_sector_tools.py` 和 `tradingagents/agents/analysts/market_index_analyst.py`
2. **检查上游是否改动了上述 5 个文件**: `git diff upstream/main` 查看是否有冲突
3. **逐个文件恢复**: 按上述 diff 补丁重新应用增量修改
4. **特别注意 `setup.py`**: 这是冲突热点，上游可能也改了这个文件的动态循环结构

## 相关提交

| Commit | 描述 |
|-------|------|
| `971dfe8` | feat(agents): add Market Index Analyst for macro environment analysis |
| `95c8e26` | feat(config): add market_index to default analyst selection |

## 新增文件（非上游，不受上游合并影响）

| 文件 | 说明 |
|------|------|
| `tradingagents/dataflows/index_sector_tools.py` | 3 个数据工具 + BOARD_INDEX_MAP |
| `tradingagents/agents/analysts/market_index_analyst.py` | 大盘分析师智能体 |

---

### 2026-04-14: inject market_index_report into downstream analysts

**目的**: 将 Market Index Analyst 产出的 `market_index_report` 注入到下游 4 个分析师的 prompt 中，使其能在分析中参考宏观环境背景。

**改动类型**: 纯增量（+1 函数，4 文件各改 1 import + 1 调用），无删除，可逆。

#### 5. `tradingagents/agents/utils/agent_utils.py`

**改动类型**: 新增函数 (+29 行)

**位置**: `build_instrument_context` 函数之后

```python
def build_full_context(ticker: str, state: dict) -> str:
    """Build instrument context enriched with the Market Index Analyst macro report."""
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
```

**说明**: `build_instrument_context` 保持不变（向后兼容）。新函数 `build_full_context` 包装它，按需追加宏观报告。

#### 6-9. 下游 4 个分析师文件

每个文件 2 处修改（import + 调用），模式完全一致：

| # | 文件 | import 改动 | 调用改动 |
|---|------|------------|---------|
| 6 | `tradingagents/agents/analysts/market_analyst.py` | `build_instrument_context` → `build_full_context` | `build_instrument_context(state["company_of_interest"])` → `build_full_context(state["company_of_interest"], state)` |
| 7 | `tradingagents/agents/analysts/fundamentals_analyst.py` | 同上 | 同上 |
| 8 | `tradingagents/agents/analysts/news_analyst.py` | 同上 | `build_instrument_context(symbol)` → `build_full_context(symbol, state)` |
| 9 | `tradingagents/agents/analysts/social_media_analyst.py` | 同上 | 同 #6 |

**未改动**: `market_index_analyst.py`（它是生产者，不是消费者）。

**合并恢复**: 此轮改动全部在项目自定义代码中（非上游热点文件），上游合并不受影响。恢复只需将 4 个文件的 import 和调用还原为 `build_instrument_context`。
