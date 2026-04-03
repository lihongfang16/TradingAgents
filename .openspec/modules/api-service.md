# API 服务层 (API Service Layer)

> 类型: 全新 | 层级: 接口 | 上游对应: 无

## 概述

API服务层基于FastAPI构建，为TradingAgents分析引擎提供RESTful接口封装。上游库仅提供Python库调用方式，本模块新增完整的HTTP API能力，支持任务创建、进度追踪、结果查询等全生命周期管理。

核心特性包括：PostgreSQL持久化存储、SSE(Server-Sent Events)实时进度推送、异步任务执行、以及Watchlist管理。设计遵循"上游隔离原则"，所有API逻辑位于独立模块，不侵入分析引擎核心代码。

## 架构

### 组件结构

```
webapi/
├── main.py                      # FastAPI应用入口
├── config.py                    # API层配置
├── routers/                     # 路由处理器
│   ├── __init__.py
│   ├── analysis.py              # 分析任务路由
│   └── watchlist.py             # 关注列表路由
├── services/                    # 业务逻辑层
│   ├── __init__.py
│   └── analysis_service.py      # 分析任务服务
├── models/                      # 数据模型
│   ├── __init__.py
│   ├── database.py              # SQLAlchemy模型
│   └── analysis.py              # Pydantic模型
└── dependencies.py              # FastAPI依赖注入
```

### 核心类/函数

| 符号 | 类型 | 位置 | 功能描述 |
|------|------|------|----------|
| `AnalysisService` | 类 | `services/analysis_service.py` | 分析任务CRUD与执行管理 |
| `create_analysis_task()` | 函数 | `services/analysis_service.py` | 创建异步分析任务 |
| `get_task_progress()` | 函数 | `services/analysis_service.py` | 获取任务进度 |
| `AnalysisTask` | 类 | `models/database.py` | SQLAlchemy任务模型 |
| `AnalysisCreate` | 类 | `models/analysis.py` | Pydantic创建请求模型 |

### 数据流

```
客户端请求 → FastAPI路由 → AnalysisService → 数据库
                  ↓              ↓
            SSE连接 ←  AnalysisRunner ←  TradingAgentsGraph
                  ↓
            实时推送进度至客户端
```

## 与上游的关系

| 方面 | 说明 |
|------|------|
| 继承 | 无直接继承，新增层 |
| 新增 | FastAPI应用、数据库模型、SSE进度流、RESTful端点 |
| 修改 | 无 |
| 依赖 | 通过`AnalysisRunner`调用上游`TradingAgentsGraph`，不直接依赖 |

**集成模式**: API层通过`AnalysisRunner`包装器调用分析引擎，保持上游代码零修改。

## 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 数据库URL | `DATABASE_URL` | postgresql://localhost/tradingagents | PostgreSQL连接字符串 |
| API端口 | `API_PORT` | 8000 | FastAPI服务端口 |
| 日志级别 | `API_LOG_LEVEL` | INFO | 日志输出级别 |
| 最大并发任务 | `MAX_CONCURRENT_ANALYSIS` | 3 | 同时执行的最大分析任务数 |
| 任务超时 | `ANALYSIS_TIMEOUT` | 300 | 单任务超时时间（秒） |

## 接口

### RESTful端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/analysis/` | 创建分析任务 |
| GET | `/api/v1/analysis/` | 查询任务列表 |
| GET | `/api/v1/analysis/{task_id}` | 获取任务详情 |
| DELETE | `/api/v1/analysis/{task_id}` | 删除任务（204响应） |
| GET | `/api/v1/analysis/{task_id}/progress` | SSE进度流 |
| GET | `/api/v1/analysis/{task_id}/result` | 获取分析结果 |
| POST | `/api/v1/watchlist/` | 添加关注股票 |
| GET | `/api/v1/watchlist/` | 获取关注列表 |
| DELETE | `/api/v1/watchlist/{symbol}` | 移除关注股票 |

### SSE进度事件

```
event: progress
data: {"task_id": "...", "agent": "researcher", "progress": 45, "status": "running"}

event: complete
data: {"task_id": "...", "status": "completed", "result_url": "/api/v1/analysis/.../result"}
```

### 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `running` | 执行中 |
| `completed` | 已完成 |
| `failed` | 执行失败 |
| `cancelled` | 已取消 |

## 依赖

### 外部依赖

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| fastapi | >=0.104.0 | Web框架 |
| uvicorn | >=0.24.0 | ASGI服务器 |
| sqlalchemy | >=2.0.0 | ORM |
| alembic | >=1.12.0 | 数据库迁移 |
| asyncpg | >=0.29.0 | 异步PostgreSQL驱动 |
| pydantic | >=2.0.0 | 数据验证 |

### 内部依赖

- `tradingagents/core/analysis_runner.py` — 分析执行器
- `tradingagents/default_config.py` — 默认配置

### 数据库表

| 表名 | 说明 |
|------|------|
| `analysis_tasks` | 分析任务主表 |
| `watchlist` | 用户关注列表 |
| `alembic_version` | 迁移版本记录 |

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| 懒加载警告 | 已知 | analysis_service采用首次请求时加载，可能产生首次延迟 |
| SSE连接池 | 已知 | 高并发SSE连接需调优uvicorn worker配置 |
| 进度报告间隔 | 已知 | `analysis_runner.py`仅报告一次60%进度，之后静默直至完成 |
| 任务取消 | 待实现 | 当前不支持中途取消运行中的任务 |

## 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-10 | 1.0.0 | FastAPI基础框架搭建 |
| 2026-03-18 | 1.1.0 | 新增SSE实时进度推送 |
| 2026-03-22 | 1.2.0 | Watchlist功能实现 |
| 2026-03-26 | 1.3.0 | 数据库迁移系统（Alembic） |

