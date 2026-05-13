# 自选股分析管线 (Watchlist Analysis Pipeline)

> 类型: 全新 | 层级: 业务逻辑 | 上游对应: 无
> ⚠️ 上游隔离: 本管线全部位于 `webapi/` 层。通过 `AnalysisRunner` 单一接口桥接 `tradingagents/`。
> 不修改上游代码。详见 `.openspec/conventions-watchlist.md` §0。

## 概述

自选股分析管线是连接"调度触发"和"分析执行"的核心数据流。它管理从 SchedulerService 触发 → 任务入队 → 分析执行 → 结果回写 → 转折检测 → 通知推送的完整生命周期。

管线设计遵循"最终一致性"原则：调度器触发是 fire-and-forget 的，结果通过 `_finalize_watchlist_analysis()` 异步回写，对账 Job 补偿遗漏。

## 架构

### 组件结构

```
webapi/
├── services/
│   ├── scheduler_service.py      # 触发器 + 转折检测 + 对账 (923行)
│   ├── queue_service.py          # PG-based 任务队列
│   ├── analysis_service.py       # 任务 CRUD + 异步执行
│   ├── analysis_cache_service.py # Analyst 报告缓存
│   └── notification_service.py   # 桌面通知推送
├── models/
│   └── database.py               # 6 张表的 ORM 定义 (639行)
├── routers/
│   ├── watchlist.py              # 自选股 CRUD + 手动触发
│   ├── queue.py                  # 队列管理 API
│   └── analysis.py               # 分析任务 API + SSE
└── subprocess_runner.py          # 子进程隔离执行器
```

### 核心类/函数

| 符号 | 类型 | 位置 | 功能描述 |
|------|------|------|----------|
| `SchedulerService` | 类 | `scheduler_service.py:692` | APScheduler 封装，Job 注册/触发/恢复 |
| `detect_turning_point()` | 函数 | `scheduler_service.py:185` | 转折点检测算法（信号反转+置信度+风险+警报） |
| `_finalize_watchlist_analysis()` | 函数 | `scheduler_service.py:388` | 分析完成后的核心回写逻辑 |
| `reconciliation_job()` | 函数 | `scheduler_service.py:527` | 三层对账：Queue → Task → WatchlistAnalysis |
| `high_frequency_batch_job()` | 函数 | `scheduler_service.py:564` | HF 模式批量分析 + 自动降频评估 |
| `_run_watchlist_job_batch()` | 函数 | `scheduler_service.py:663` | 批量执行入口 (⚠️ Placeholder) |
| `AnalysisQueueService` | 类 | `queue_service.py` | PG-based 队列管理（入队/出队/重试/对账） |
| `AnalysisTask` | 类 | `models/database.py:15` | 分析任务 ORM |
| `AnalysisQueue` | 类 | `models/database.py:206` | 任务队列 ORM |
| `Watchlist` | 类 | `models/database.py:271` | 自选股 ORM（含 position 数据） |
| `WatchlistAnalysis` | 类 | `models/database.py:366` | 分析历史 + 转折点 ORM |
| `WatchlistConfig` | 类 | `models/database.py:484` | 全局配置 KV ORM |
| `AnalystReportCache` | 类 | `models/database.py:539` | Analyst 报告缓存 ORM（TTL per type） |

### 数据流

```
                    ┌──────────────────────────────────────────┐
                    │           触发源                          │
                    ├────────────┬─────────────┬───────────────┤
                    │ APScheduler│ Router 手动  │ HF Batch Job  │
                    └─────┬──────┴──────┬──────┴───────┬───────┘
                          │             │              │
                          ▼             ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: 创建任务                                             │
│   AnalysisService.create_task(symbol, analysis_type)         │
│   → INSERT analysis_tasks (PENDING)                         │
│   → INSERT analysis_queue (QUEUED, priority=0)              │
│   → INSERT watchlist_analyses (analysis_type, triggered_by) │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: 执行分析                                             │
│   QueueService.claim_next() → 设置 PROCESSING               │
│   AnalysisRunner.run() → TradingAgentsGraph.propagate()     │
│   → UPDATE analysis_tasks (RUNNING → COMPLETED/FAILED)      │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: 结果回写                                             │
│   _finalize_watchlist_analysis(db, wa, result)              │
│   ├── 提取 signal/confidence/risk_level/price               │
│   ├── detect_turning_point() vs 前一次结果                    │
│   ├── UPDATE watchlist_analyses (signal, is_turning_point)   │
│   ├── UPDATE watchlist (last_signal, last_price, ...)        │
│   ├── if turning → _schedule_high_frequency_window()        │
│   └── if turning → notification_service.send_turning_alert()│
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: 异步补偿 (每 5 分钟)                                 │
│   reconciliation_job()                                       │
│   ├── reconcile_stale_queue_rows() → 重置超时 Queue 行       │
│   ├── reconcile_orphaned_task_states() → 清理孤立 Task       │
│   ├── reconcile_unfinalized_watchlist_analyses() → 补完 WA   │
│   └── reconcile_expired_hf_flags() → 清理过期 HF 标记       │
└─────────────────────────────────────────────────────────────┘
```

## 与上游的关系

| 方面 | 说明 |
|------|------|
| 继承 | 无。上游 TradingAgents 无调度/队列/watchlist 概念 |
| 新增 | 完整的调度→队列→执行→回写→对账管线 |
| 修改 | 不修改上游代码。仅通过 AnalysisRunner 调用 |
| 隔离 | webapi 层独立于 tradingagents 层，通过 AnalysisRunner 单一接口桥接 |

## 数据库表关系

```
┌──────────────┐         ┌──────────────────┐
│  watchlist    │──1:N──▶│ watchlist_analyses │
│  (自选股)     │         │ (分析记录)        │
└──────────────┘         └────────┬──────────┘
                                  │ analysis_id (nullable FK)
                                  ▼
                         ┌──────────────────┐
                         │ analysis_tasks    │
                         │ (分析任务)        │
                         └────────┬──────────┘
                                  │ task_id (FK)
                                  ▼
                         ┌──────────────────┐
                         │ analysis_queue    │
                         │ (任务队列)        │
                         └──────────────────┘

┌──────────────┐         ┌──────────────────┐
│ watchlist     │──1:N──▶│ analyst_report    │
│ config (KV)   │         │ cache (TTL)       │
└──────────────┘         └──────────────────┘

┌──────────────┐
│ analysis      │ (批量任务元数据)
│ batches       │
└──────────────┘
```

## 接口

### 内部函数接口 (Service → Service)

| 调用方 | 被调用方 | 函数 | 用途 |
|--------|----------|------|------|
| Scheduler Job | QueueService | `enqueue()` | 将分析任务入队 |
| Queue Worker | AnalysisService | `execute_task()` | 执行分析 |
| AnalysisService | `_finalize_watchlist_analysis()` | 回写结果到 watchlist 层 |
| reconciliation_job | QueueService | `reconcile_stale_queue_rows()` | 对账队列 |
| reconciliation_job | QueueService | `reconcile_orphaned_task_states()` | 对账任务 |
| `_finalize_watchlist_analysis` | NotificationService | `send_turning_alert()` | 推送通知 |

### 外部 API 接口

| 方法 | 路径 | 触发管线步骤 |
|------|------|--------------|
| POST | `/api/v1/watchlist/` | 创建自选股（不影响管线） |
| POST | `/api/v1/watchlist/{id}/quick-analyze` | Step 1 (manual trigger) |
| POST | `/api/v1/watchlist/detect-turning` | Step 3 中的转折检测 |
| POST | `/api/v1/analysis/batch` | Step 1 (batch) |
| GET | `/api/v1/analysis/{id}/progress` | SSE 实时进度 |

## 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 调度器开关 | `ENABLE_SCHEDULER` | true | 是否启动调度器 |
| 全量分析时间 | `DAILY_ANALYSIS_TIME` | 02:00 | 盘后深度分析 |
| 交易时段频率 | — | 5 min | 快速分析间隔 |
| HF 批次间隔 | — | 2 min | 高频监控间隔 |
| 对账间隔 | — | 5 min | reconciliation_job |
| HF 窗口时长 | `HIGH_FREQUENCY_DURATION_MINUTES` | 10 min | 转折后高频持续时间 |
| 置信度跳变阈值 | `DEFAULT_CONFIDENCE_JUMP` | 0.15 | 转折检测参数 |
| 稳定窗口阈值 | `DEFAULT_STABLE_THRESHOLD` | 3 | 连续稳定次数后降频 |
| 稳定置信度窗口 | `DEFAULT_CONFIDENCE_STABILITY_WINDOW` | 0.10 | 置信度波动阈值 |
| 测试模式 | `SCHEDULER_TEST_MODE` | false | 所有 Job 降为 1-2 分钟 |
| 分析超时 | `ANALYSIS_TIMEOUT` | 1800s | 单任务超时 |

## 依赖

### 外部依赖

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| apscheduler | >=3.10.0 | 任务调度框架 |
| sqlalchemy | >=2.0.0 | ORM |
| fastapi | >=0.104.0 | Web 框架 |
| uvicorn | >=0.24.0 | ASGI 服务器 |

### 内部依赖

- `tradingagents/core/analysis_runner.py` — 分析执行器（唯一桥接点）
- `tradingagents/default_config.py` — 默认配置

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| full_analysis_job 未实现 | Placeholder | 只有 pass，需通过 QueueService 入队实现 |
| quick_analysis_job 未实现 | Placeholder | 同上 |
| _run_watchlist_job_batch 未实现 | Placeholder | 只有 return []，需实现批量执行+超时控制 |
| 任务取消 | 待实现 | 无中途取消运行中任务的机制 |
| 进度报告不完整 | Bug | Runner 只报一次 60%，之后静默至完成 |
| 节假日未处理 | 待优化 | 非交易日仍会触发调度 Job |
| 分布式不支持 | 已知限制 | 单进程 APScheduler，无法多实例部署 |

## 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-05-13 | 1.0.0 | 初始版本：完整管线规格、数据流、表关系、已知问题 |
