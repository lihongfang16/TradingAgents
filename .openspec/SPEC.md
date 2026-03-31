# OpenSpec: TradingAgents A-share Fork 规约总览

## 项目概述

**项目名称**: TradingAgents A-share Fork  
**项目类型**: 多智能体金融交易系统 (A股增强版)  
**技术栈**: Python 3.10+ | LangGraph | FastAPI | PostgreSQL | Streamlit

本项目是基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (v0.2.2) 的下游分叉，专为中文 A 股市场进行增强适配。采用双层架构设计：上层完整继承上游多智能体分析引擎，下层构建 A 股数据层、持久化服务和多接口层。

### 架构设计理念

```
┌─────────────────────────────────────────────────────────────────┐
│                          下游扩展层                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐  │
│  │  Streamlit  │  │   FastAPI   │  │     CLI     │  │  定时    │  │
│  │   前端界面   │  │  REST接口   │  │  命令行界面  │  │  调度器  │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────┬────┘  │
│         └─────────────────┴─────────────────┴─────────────┘      │
│                               │                                  │
│  ┌────────────────────────────┴────────────────────────────┐     │
│  │              A股数据层 (ChinaDataManager)                │     │
│  │       迈瑞 → Ashare → AkShare → BaoStock 降级链          │     │
│  └─────────────────────────────────────────────────────────┘     │
├─────────────────────────────────────────────────────────────────┤
│                          上游核心层                               │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │            TradingAgents 多智能体分析引擎                 │     │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────────────┐  │     │
│  │  │ 分析师  │ │ 研究员  │ │  交易员  │ │ 投资组合经理   │  │     │
│  │  │  团队   │ │  辩论   │ │  智能体  │ │  + 风险管理    │  │     │
│  │  └─────────┘ └─────────┘ └─────────┘ └───────────────┘  │     │
│  └─────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### 上游与下游边界

| 维度 | 上游 (TradingAgents) | 下游扩展 (A-share Fork) |
|------|---------------------|----------------------|
| 市场 | 仅美股 (yfinance/AlphaVantage) | +A股 (Mairui→Ashare→AkShare→BaoStock) |
| 数据源 | 2个 (yfinance, alpha_vantage) | +4个A股数据源 via ChinaDataManager |
| 智能体 | 12个智能体, 英文提示词 | 相同 + A股中文提示词 |
| LLM客户端 | 6个提供商, 有已知问题 | 相同 (继承) |
| 持久化 | JSON文件 | PostgreSQL + SQLAlchemy + Alembic |
| 接口 | CLI + Python API | +Streamlit UI + FastAPI REST API |
| 调度 | 无 | APScheduler 定时任务 |
| 图模式 | 单一完整图 | +快速模式 via AnalysisRunner |
| 股票代码 | 美股ticker | +A股代码标准化 |
| 涨跌停 | 不处理 | 自动检测 ±10%/±20% |

## 规约文件结构

```
.openspec/
├── SPEC.md                    # 本文件：规约总览和索引
├── upstream-reference.md      # 上游库功能清单
├── conventions.md             # 编码规约
├── modules/                   # 下游扩展模块规约
│   ├── a-share-data-layer.md  # A股数据层
│   ├── api-service.md         # FastAPI 服务层
│   ├── cli-interface.md       # CLI 交互层
│   ├── web-ui.md              # Streamlit 前端
│   ├── scheduler.md           # 定时任务调度
│   └── custom-agents.md       # 自定义角色代理
├── decisions/                 # 架构决策记录 (ADRs)
├── rfcs/                      # 请求评议文档
└── archived/                  # 已归档规约
```

## 模块规约索引

下游扩展模块的详细规约文档位于 `modules/` 目录：

| 模块文档 | 说明 | 路径 |
|---------|------|------|
| A股数据层 | ChinaDataManager 四源故障转移、股票代码标准化、涨跌停检测 | `modules/a-share-data-layer.md` |
| API服务层 | FastAPI REST API 设计、SSE 进度流、异步任务执行 | `modules/api-service.md` |
| CLI交互层 | Typer+Rich 命令行界面、交互式配置、实时进度展示 | `modules/cli-interface.md` |
| Web前端 | Streamlit 可视化界面、分析结果展示、历史记录管理 | `modules/web-ui.md` |
| 任务调度 | APScheduler 定时分析、市场时间感知、批处理队列 | `modules/scheduler.md` |
| 自定义代理 | 智能体角色扩展、双语提示词、A股专用分析逻辑 | `modules/custom-agents.md` |

## 上游隔离原则 (UPSTREAM ISOLATION PRINCIPLE)

维护分叉与上游的清晰边界，确保可持续升级：

- **NEVER** 在添加持久化层时修改分析引擎核心代码
- **NEVER** 删除 JSON 备份文件
- **NEVER** 引入 Redis/MongoDB
- **NEVER** 为快速模式创建新的 LangGraph Graph
- 架构变更需要 ADR
- 重大功能需要 RFC

## 决策与治理流程

### 架构决策记录 (ADR)

所有架构层面的决策必须通过 ADR 文档记录：

1. 复制 `decisions/template.md` 创建新的 ADR
2. 使用下一个可用的编号（如 `003-xxx.md`）
3. 填写标题、状态、背景、决策内容、备选方案和影响
4. 提交 PR 进行团队评审

当前 ADR 列表：
- [ADR-001: 使用 PostgreSQL 作为数据库](./decisions/001-use-postgresql.md)
- [ADR-002: WSL2 用于 Windows 开发环境](./decisions/002-wsl2-for-windows-dev.md)

### 请求评议文档 (RFC)

重大功能变更需要通过 RFC 流程：

1. 在 `rfcs/` 目录创建 RFC 文档
2. 状态标记为 `Proposed`
3. 经过评审后标记为 `Accepted` 或 `Rejected`
4. 实施完成后更新 RFC，添加实施总结

当前 RFC 列表：
- [RFC-001: 数据库迁移方案](./rfcs/001-database-migration.md) (状态: Implemented)

### 状态定义

| 状态 | 含义 |
|------|------|
| Proposed | 已提出，待评审 |
| Accepted | 已接受，准备实施 |
| Implemented | 已实施完成 |
| Rejected | 被拒绝 |
| Deprecated | 已废弃，不再适用 |

## 核心规约

### 技术架构规约

- **后端框架**: FastAPI + SQLAlchemy 2.0
- **数据库**: PostgreSQL (开发: WSL2, 生产: Linux)
- **迁移工具**: Alembic
- **前端**: Streamlit (独立应用，无 `__init__.py`)
- **任务调度**: APScheduler

### 数据存储规约

- 分析任务使用 PostgreSQL 持久化存储
- JSON 文件仅作为备份，不作为主要数据源
- 数据库连接通过环境变量 `DATABASE_URL` 配置
- 敏感信息（密码、API Key）不硬编码

### API 设计规约

- RESTful API 设计
- 统一响应格式
- 状态码遵循 HTTP 规范
- 删除操作返回 204 No Content
- SSE 端点用于实时进度流 (`/api/v1/analysis/{task_id}/progress`)

### 代码规约

详见 [编码规约](./conventions.md)，要点如下：

- **命名**: 类用大驼峰，函数用蛇形命名，常量全大写
- **导入**: 标准库 → 第三方 → 本地模块
- **类型**: 函数参数和返回值必须添加类型注解
- **文档**: 公共模块、类、方法必须包含文档字符串
- **数据库**: 表名用复数小写，索引命名 `ix_<table>_<column>`
- **Git**: 提交格式 `<type>(<scope>): <subject>`

## 上游参考

上游 TradingAgents 功能清单和继承关系详见 [上游参考文档](./upstream-reference.md)。

## 快速参考

### 常用链接

- [编码规约](./conventions.md)
- [ADR 模板](./decisions/template.md)
- [上游功能清单](./upstream-reference.md)

### 最新变更

| 日期 | 变更 | 文档 |
|------|------|------|
| 2026-03-28 | OpenSpec 重构：添加模块索引、上游隔离原则 | SPEC.md |
| 2026-03-26 | 初始化 OpenSpec 规约 | SPEC.md |
| 2026-03-26 | 添加 PostgreSQL 选型决策 | decisions/001-use-postgresql.md |
| 2026-03-26 | 添加 WSL2 开发环境决策 | decisions/002-wsl2-for-windows-dev.md |
| 2026-03-26 | 添加数据库迁移 RFC | rfcs/001-database-migration.md |
| 2026-03-26 | RFC-001 已接受并实施完成 | rfcs/001-database-migration.md |

## 贡献指南

1. 所有架构变更都需要 ADR
2. 重大功能变更需要 RFC
3. 保持文档更新，与实际代码一致
4. 使用清晰的标题和结构化内容
5. 遵循上游隔离原则，不侵入核心分析引擎

## 相关资源

- **上游仓库**: https://github.com/TauricResearch/TradingAgents
- **上游版本**: v0.2.2
- **社区**: [Tauric Research](https://tauric.ai/)
- **论文**: arXiv:2412.20138
