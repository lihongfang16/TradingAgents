# OpenSpec: TradingAgents A-share 规约总览

## 项目概述

**项目名称**: TradingAgents A-share  
**项目类型**: 多智能体金融交易系统  
**技术栈**: Python + LangGraph + FastAPI + PostgreSQL

TradingAgents 是一个基于多智能体 LLM 的金融交易框架，模拟真实交易公司的运作方式。系统部署多个专业化的智能体（基本面分析师、情绪分析师、技术分析师、交易员、风险管理团队），协同评估市场条件并做出交易决策。

### 核心组件

- **分析团队**: 基本面、情绪、新闻、技术面分析师
- **研究团队**: 多空研究员通过辩论平衡风险与收益
- **交易员智能体**: 综合分析报告做出交易决策
- **风险管理**: 评估市场波动性和流动性风险
- **投资组合经理**: 审批或拒绝交易提案

## 规约文件结构

```
.openspec/
├── SPEC.md                    # 本文件：规约总览和索引
├── conventions.md             # 编码规约
├── decisions/                 # 架构决策记录 (ADRs)
│   ├── template.md            # ADR 模板
│   ├── 001-use-postgresql.md  # 数据库选型决策
│   └── 002-wsl2-for-windows-dev.md  # 开发环境决策
├── rfcs/                      # 请求评议文档
│   └── 001-database-migration.md    # 数据库迁移 RFC
└── archived/                  # 已归档规约
    └── README.md              # 归档说明
```

## 核心规约

### 1. 技术架构规约

- **后端框架**: FastAPI + SQLAlchemy
- **数据库**: PostgreSQL (开发: WSL2, 生产: Linux)
- **ORM**: SQLAlchemy 2.0+
- **迁移工具**: Alembic
- **前端**: Streamlit

### 2. 数据存储规约

- 分析任务使用 PostgreSQL 持久化存储
- JSON 文件仅作为备份，不作为主要数据源
- 数据库连接通过环境变量 `DATABASE_URL` 配置
- 敏感信息（密码、API Key）不硬编码

### 3. API 设计规约

- RESTful API 设计
- 统一响应格式
- 状态码遵循 HTTP 规范
- 删除操作返回 204 No Content

## 决策流程

### 提出决策

1. 复制 `decisions/template.md` 创建新的 ADR
2. 使用下一个可用的编号（如 003-xxx.md）
3. 填写标题、日期、状态、背景、决策内容
4. 提交 PR 或在相关任务中实现

### RFC 流程

1. 在 `rfcs/` 目录创建 RFC 文档
2. 状态标记为 `Proposed`
3. 经过团队评审后标记为 `Accepted` 或 `Rejected`
4. 实施完成后更新 RFC，添加实施总结

### 状态定义

| 状态 | 含义 |
|------|------|
| Proposed | 已提出，待评审 |
| Accepted | 已接受，准备实施 |
| Implemented | 已实施完成 |
| Rejected | 被拒绝 |
| Deprecated | 已废弃，不再适用 |

## 快速参考

### 常用链接

- [编码规约](./conventions.md)
- [ADR 模板](./decisions/template.md)
- [RFC-001: 数据库迁移](./rfcs/001-database-migration.md)

### 最新变更

| 日期 | 变更 | 文档 |
|------|------|------|
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

## 联系方式

- 项目仓库: https://github.com/TauricResearch/TradingAgents
- 社区: [Tauric Research](https://tauric.ai/)
