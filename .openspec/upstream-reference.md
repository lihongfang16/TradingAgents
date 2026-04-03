# 上游 TradingAgents 库参考手册

> 本文档详细列出 TauricResearch/TradingAgents (v0.2.2) 的全部功能、架构和扩展点，帮助开发者理解哪些属于上游继承、哪些属于下游定制。

---

## 1. 上游库概述

| 项目 | 详情 |
|------|------|
| **仓库地址** | https://github.com/TauricResearch/TradingAgents |
| **版本** | v0.2.2 (2026-03-22) |
| **论文** | https://arxiv.org/abs/2412.20138 |
| **许可证** | MIT |
| **定位** | 多智能体 LLM 金融交易框架 |
| **开发语言** | Python 3.10+ |
| **核心依赖** | LangGraph, LangChain, Pydantic |

上游 TradingAgents 是一个基于大语言模型的多智能体协同交易决策框架，通过模拟人类投资团队的工作流程，实现对金融资产的深度分析和交易决策。

---

## 2. 智能体架构

上游共包含 12 个智能体，分为 5 个职能团队：

### 2.1 分析团队 (4 个)

| 智能体 | 角色 | LLM | 输入 | 输出 |
|--------|------|-----|------|------|
| **Fundamentals Analyst** | 基本面分析 | quick_think_llm | 股票代码、财务数据 | 基本面分析报告 |
| **Sentiment Analyst** | 情绪分析 | quick_think_llm | 市场数据、社交媒体 | 情绪分析报告 |
| **News Analyst** | 新闻分析 | quick_think_llm | 新闻源、公告 | 新闻分析报告 |
| **Technical Analyst** | 技术分析 | quick_think_llm | 价格数据、技术指标 | 技术分析报告 |

特点：
- 系统提示词语言：仅英文
- 并行执行，各自独立分析
- 输出结构化报告供后续阶段使用

### 2.2 研究团队 (2 个)

| 智能体 | 角色 | LLM | 输入 | 输出 |
|--------|------|-----|------|------|
| **Bullish Researcher** | 看多研究员 | deep_think_llm | 4 份分析师报告 | 看多论证报告 |
| **Bearish Researcher** | 看空研究员 | deep_think_llm | 4 份分析师报告 | 看空论证报告 |

特点：
- 采用结构化辩论机制 (structured debate)
- 研究员之间进行观点交锋
- 模拟多空双方的投资逻辑
- 输出带有论据和置信度的研究报告

### 2.3 交易员 (1 个)

| 智能体 | 角色 | LLM | 输入 | 输出 |
|--------|------|-----|------|------|
| **Trader Agent** | 交易执行 | quick_think_llm | 多空研究报告 | 交易决策草案 |

特点：
- 综合多空观点形成交易决策
- 输出包含：建议操作、目标价位、止损价位、仓位比例

### 2.4 风险管理团队 (3 个)

| 智能体 | 角色 | LLM | 输入 | 输出 |
|--------|------|-----|------|------|
| **Risky Debater** | 激进风险官 | quick_think_llm | 交易决策草案 | 风险激进的论证 |
| **Safe Debater** | 保守风险官 | quick_think_llm | 交易决策草案 | 风险保守的论证 |
| **Neutral Debater** | 中立风险官 | quick_think_llm | 交易决策草案 | 风险评估报告 |

特点：
- 三向辩论机制
- 从不同风险偏好角度审视交易决策
- 输出风险评级和调整建议

### 2.5 管理团队 (2 个)

| 智能体 | 角色 | LLM | 输入 | 输出 |
|--------|------|-----|------|------|
| **Portfolio Manager** | 组合经理 | deep_think_llm | 交易决策 + 风险评估 | 最终交易指令 |
| **(implied)** | 隐含管理角色 | - | - | - |

特点：
- Portfolio Manager 拥有最终决策权
- 综合考虑交易机会和风险约束
- 输出五级评级交易信号

### 2.6 LLM 使用策略

```
depth_think_llm (深度思考模型)
├── Bullish Researcher
├── Bearish Researcher
└── Portfolio Manager

quick_think_llm (快速响应模型)
├── Fundamentals Analyst
├── Sentiment Analyst
├── News Analyst
├── Technical Analyst
├── Trader Agent
├── Risky Debater
├── Safe Debater
└── Neutral Debater
```

---

## 3. 图流程 (Graph Flow)

### 3.1 五阶段流水线

```
[Analyst Phase] → [Researcher Phase] → [Trader Phase] → [Risk Management Phase] → [Portfolio Manager Phase]
      ↓                  ↓                  ↓                    ↓                        ↓
   并行分析          多空辩论          交易决策            风险评估               最终指令
```

### 3.2 核心文件

| 文件 | 职责 |
|------|------|
| `tradingagents/graph/trading_graph.py` | `TradingAgentsGraph` 主类，初始化 LLM、构建图、执行传播和反思 |
| `tradingagents/graph/setup.py` | `GraphSetup` 类，构建 LangGraph StateGraph，定义节点和边 |
| `tradingagents/agents/utils/agent_states.py` | `AgentState` 类，定义 LangGraph 状态结构 |

### 3.3 状态管理

`AgentState` 类持有以下关键数据：
- 所有分析师报告 (fundamentals_report, sentiment_report, etc.)
- 多空研究报告 (bullish_report, bearish_report)
- 交易决策草案 (trader_decision)
- 风险辩论状态 (risky_argument, safe_argument, neutral_argument)
- 最终组合决策 (portfolio_decision)
- 任务元数据 (symbol, timestamp, etc.)

### 3.4 核心方法

| 方法 | 位置 | 功能 |
|------|------|------|
| `propagate()` | `TradingAgentsGraph` | 正向分析流程，驱动五阶段流水线 |
| `reflect()` | `TradingAgentsGraph` | 事后反思，分析交易决策的得失 |

---

## 4. 数据源

### 4.1 支持的数据提供商

| 提供商 | 类型 | 覆盖范围 | 功能 |
|--------|------|----------|------|
| **yfinance** | 主要 | 美股 | 股价、基本面、新闻、内幕交易 |
| **Alpha Vantage** | 补充 | 美股 | 基本面、技术指标 |

### 4.2 数据类型

- 历史价格数据 (OHLCV)
- 财务报表数据
- 公司基本面信息
- 新闻和公告
- 技术指标计算
- 内幕交易数据

### 4.3 数据流架构

```
tradingagents/dataflows/interface.py
    ↓
路由到不同 vendor 模块
    ↓
yfinance.py / alpha_vantage.py
```

### 4.4 重要说明

- 上游仅支持美股市场
- 不支持 A 股数据
- 数据获取为同步调用
- 无本地数据缓存机制

---

## 5. LLM 客户端

### 5.1 工厂模式

位置：`tradingagents/llm_clients/factory.py`

```python
create_llm_client(provider: str, model: str, api_key: str, ...)
```

### 5.2 支持的提供商 (6 个)

| 提供商 | 类名 | 状态 |
|--------|------|------|
| OpenAI | `OpenAIClient` | 完整支持 |
| Google (Gemini) | `GoogleClient` | 完整支持 |
| Anthropic (Claude) | `AnthropicClient` | 完整支持 |
| xAI (Grok) | `xAIClient` | 完整支持 |
| OpenRouter | `OpenRouterClient` | 完整支持 |
| Ollama | `OllamaClient` | 完整支持 (本地) |

### 5.3 双模型策略

| 模型类型 | 用途 | 典型模型 |
|----------|------|----------|
| `deep_think_llm` | 复杂推理、决策 | GPT-5.4, Claude 4.6, Gemini 3.1 |
| `quick_think_llm` | 快速分析、响应 | GPT-4.1-mini, Claude 3.5-Haiku |

### 5.4 已知问题

根据 AGENTS.md 文档，上游存在以下已知限制：

1. `validate_model()` 方法从未被调用
2. `AnthropicClient` 和 `GoogleClient` 接受 `base_url` 参数但忽略它

---

## 6. 扩展点

### 6.1 显式扩展点

上游代码中明确设计的扩展机制：

| 扩展点 | 位置 | 说明 |
|--------|------|------|
| `DEFAULT_CONFIG` | `tradingagents/default_config.py` | 全局配置字典，可覆盖默认参数 |
| Agent 系统提示词 | `tradingagents/agents/*/prompts.py` | 每个智能体的提示词可自定义 |
| 数据供应商路由 | `tradingagents/dataflows/interface.py` | 可添加新的数据提供商 |
| 工具定义 | `tradingagents/agents/utils/tools.py` | 可添加新的工具函数 |
| 记忆系统 | `FinancialSituationMemory` | BM25 基于的离线记忆，用于交易反思 |

### 6.2 隐式扩展机会

虽然上游未明确设计，但下游可安全扩展的位置：

- **新增数据提供商**：在 vendor 链中添加新的数据源模块
- **提示词覆盖**：按标的类型覆盖默认提示词
- **新增智能体类型**：在 Graph 中注册新的节点
- **自定义工具**：向智能体工具箱添加新工具

---

## 7. 上游接口

### 7.1 命令行接口 (CLI)

- 入口：`tradingagents` 命令
- 框架：Typer + Rich
- 功能：运行分析、查看结果、配置参数
- 状态管理：`MessageBuffer` 类

### 7.2 Python API

```python
from tradingagents import TradingAgentsGraph

# 初始化
graph = TradingAgentsGraph(
    symbol="AAPL",
    deep_think_llm=deep_llm,
    quick_think_llm=quick_llm
)

# 执行分析
result = graph.propagate()

# 事后反思
reflection = graph.reflect()
```

### 7.3 上游不提供的内容

| 功能 | 状态 |
|------|------|
| REST API | 不存在 |
| Web UI | 不存在 |
| 数据库持久化 | 不存在 |
| 定时任务/调度 | 不存在 |
| 用户认证 | 不存在 |
| 多用户支持 | 不存在 |

---

## 8. 版本历史

| 版本 | 日期 | 主要更新 |
|------|------|----------|
| **v0.2.2** | 2026-03 | GPT-5.4 / Gemini 3.1 / Claude 4.6 支持；五级评级体系；OpenAI Responses API 适配 |
| **v0.2.0** | 2026-02 | 多提供商 LLM 支持；架构优化；新增 xAI/OpenRouter/Ollama 支持 |
| **v0.1.x** | 2025-12 | 初始发布；基础四分析师架构；yfinance 数据源 |

---

## 9. 与下游的边界

下表清晰区分上游继承内容和下游定制内容：

| 组件 | 上游 | 下游 | 说明 |
|------|:--:|:--:|------|
| `tradingagents/graph/` | ✅ | 🔧 | 核心图流程继承，小幅修改适配 A 股 |
| `tradingagents/agents/` | ✅ | 🔧 | 核心智能体继承，系统提示词中文化 |
| `tradingagents/dataflows/` | ✅ | ➕ | 美股数据源继承，新增 A 股数据层 |
| `tradingagents/llm_clients/` | ✅ | ✅ | 原样继承，不做修改 |
| `tradingagents/core/` | ✅ | ➕ | 基础架构继承，新增 `AnalysisRunner` |
| `cli/` | ✅ | 🔧 | CLI 核心继承，增加 A 股相关命令 |
| `webapi/` | ❌ | ➕ | 上游不存在，下游全新开发 FastAPI |
| `web/` | ❌ | ➕ | 上游不存在，下游全新开发 Streamlit |
| `alembic/` | ❌ | ➕ | 上游不存在，下游新增数据库迁移 |
| `scripts/` | ❌ | ➕ | 上游不存在，下游新增工具脚本 |

**图例说明：**
- ✅ 原样继承：不做修改直接使用
- 🔧 修改扩展：基于上游代码进行定制
- ➕ 全新开发：上游不存在的功能
- ❌ 不存在：上游没有此组件

### 9.1 合并策略

- 上游更新通过 `git merge` 引入
- 下游扩展保持隔离，不污染上游代码
- 冲突解决时优先保留下游定制
- 架构变更需在 `.openspec/decisions/` 中记录 ADR

---

## 参考链接

- 上游仓库：https://github.com/TauricResearch/TradingAgents
- 论文地址：https://arxiv.org/abs/2412.20138
- 下游 SPEC.md：见 `.openspec/SPEC.md`
- 下游架构决策：见 `.openspec/decisions/`

---

*本文档最后更新：2026-03-28*
