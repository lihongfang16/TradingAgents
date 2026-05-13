# 定时任务调度 (Scheduler)

> 类型: 全新 | 层级: 基础设施 | 上游对应: 无

## 概述

定时任务调度模块基于 APScheduler `BackgroundScheduler` 构建，提供自选股自动化分析的调度与执行能力。上游 TradingAgents 库为手动触发式分析，本模块新增完整的定时任务基础设施，支持定时全量分析、交易时段快速分析、高频转折确认、以及多层对账。

调度策略针对 A 股市场交易时间设计：全量分析安排在盘后凌晨，快速分析覆盖交易时段（09:20-15:00），高频转折确认每 2 分钟执行，对账 Job 每 5 分钟补偿遗漏。

**管理规约**: 本模块的所有开发必须遵守 `.openspec/conventions-watchlist.md`。

## 架构

### 组件结构

```
webapi/services/
└── scheduler_service.py          # 单文件实现 (923行)
    ├── SchedulerService 类       # APScheduler 封装 (692-917行)
    ├── 转折检测函数组             # detect_turning_point + 辅助 (30-229行)
    ├── Job 函数组                 # 各调度任务实现 (564-689行)
    ├── 对账函数组                 # reconciliation + 辅助 (299-561行)
    └── 回写函数组                 # _finalize + process (388-524行)
```

### 核心类/函数

| 符号 | 类型 | 位置 | 功能描述 |
|------|------|------|----------|
| `SchedulerService` | 类 | `scheduler_service.py:692` | APScheduler 生命周期管理 + Job 注册 |
| `WatchlistScheduler` | 类 | `scheduler_service.py:919` | `SchedulerService` 的向后兼容别名 |
| `scheduler_service` | 单例 | `scheduler_service.py:923` | 模块级全局实例 |
| `detect_turning_point()` | 函数 | `scheduler_service.py:185` | 转折点检测（信号反转 + 置信度 + 风险 + 警报） |
| `_finalize_watchlist_analysis()` | 函数 | `scheduler_service.py:388` | 分析结果回写 + 转折检测 + HF 激活 + 通知 |
| `process_watchlist_analysis_completion()` | 函数 | `scheduler_service.py:485` | 公开的回写入口（自建 DB session） |
| `reconciliation_job()` | 函数 | `scheduler_service.py:527` | 三层对账：Queue + Task + WatchlistAnalysis |
| `high_frequency_batch_job()` | 函数 | `scheduler_service.py:564` | HF 模式批量分析 + 稳定性评估降频 |
| `full_analysis_job()` | 函数 | `scheduler_service.py:637` | ⚠️ Placeholder — 盘后全量分析 |
| `quick_analysis_job()` | 函数 | `scheduler_service.py:650` | ⚠️ Placeholder — 交易时段快速分析 |
| `_run_watchlist_job_batch()` | 函数 | `scheduler_service.py:663` | ⚠️ Placeholder — 批量执行入口 |
| `should_use_high_frequency()` | 函数 | `scheduler_service.py:232` | 评估是否需要继续高频监控 |
| `_normalize_signal()` | 函数 | `scheduler_service.py:40` | 信号标准化（中英文 → 5-tier） |
| `_extract_analysis_payload()` | 函数 | `scheduler_service.py:136` | 从 AnalysisResponse 提取结构化结果 |

### 数据流

```
APScheduler 触发
    │
    ├─ Cron(02:00) ──────── full_analysis_job() ─────── [Placeholder]
    │
    ├─ Cron(09:20-15:00/5min) quick_analysis_job() ── [Placeholder]
    │
    ├─ Interval(2min) ───── high_frequency_batch_job()
    │                           │
    │                           ▼
    │                   查询 is_high_frequency='Y' 的 watchlist
    │                           │
    │                           ▼
    │                   _run_watchlist_job_batch() [Placeholder]
    │                           │
    │                           ▼
    │                   should_use_high_frequency() → 决定是否降频
    │
    └─ Interval(5min) ───── reconciliation_job()
                                │
                                ├── reconcile_stale_queue_rows()
                                ├── reconcile_orphaned_task_states()
                                ├── reconcile_pending_orphans()
                                ├── reconcile_unfinalized_watchlist_analyses()
                                └── reconcile_expired_hf_flags()
```

## 与上游的关系

| 方面 | 说明 |
|------|------|
| 继承 | 无直接继承 |
| 新增 | 完整的定时调度能力、转折检测算法、HF 升降频机制、多层对账 |
| 修改 | 无。通过 AnalysisService → AnalysisRunner 桥接 |
| 集成 | 通过 `AnalysisService` 调用分析功能 |

**调度策略**:

| 任务类型 | 触发时间 | 用途 | 状态 |
|----------|----------|------|------|
| 全量分析 | 每日 02:00 CST | 盘后深度分析 | ⚠️ Placeholder |
| 早盘快速 | 周一至五 09:20-09:55 /5min | 早盘监控 | ⚠️ Placeholder |
| 上午快速 | 周一至五 10:00-10:55 /5min | 上午监控 | ⚠️ Placeholder |
| 午盘前快速 | 周一至五 11:00-11:30 /5min | 午盘监控 | ⚠️ Placeholder |
| 午后快速 | 周一至五 13:00-14:55 /5min | 午后监控 | ⚠️ Placeholder |
| 收盘快速 | 周一至五 15:00 | 收盘分析 | ⚠️ Placeholder |
| HF 批次 | 每 2 分钟 | 高频转折确认 | ✅ 已实现 |
| 对账 | 每 5 分钟 | 状态补偿 | ✅ 已实现 |

## 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 启用调度器 | `ENABLE_SCHEDULER` | true | 是否随 API 启动调度器 |
| 全量分析时间 | `DAILY_ANALYSIS_TIME` | 02:00 | 每日全量分析执行时间 |
| 调度间隔 | `SCHEDULER_INTERVAL_MINUTES` | 5 | 测试模式下的基础间隔 |
| HF 间隔 | `SCHEDULER_HIGH_FREQUENCY_INTERVAL_MINUTES` | 2 | 测试模式下的 HF 间隔 |
| 测试模式 | `SCHEDULER_TEST_MODE` | false | 所有 Job 降为 1-2 分钟间隔 |
| 时区 | — | Asia/Shanghai | 调度器时区（硬编码） |
| HF 窗口 | `HIGH_FREQUENCY_DURATION_MINUTES` | 10 | 转折后高频持续时间（分钟） |
| 置信度跳变 | `DEFAULT_CONFIDENCE_JUMP` | 0.15 | 转折检测阈值 |
| 稳定窗口 | `DEFAULT_STABLE_THRESHOLD` | 3 | 连续稳定次数后降频 |
| 稳定置信度 | `DEFAULT_CONFIDENCE_STABILITY_WINDOW` | 0.10 | 置信度波动阈值 |

### 交易时间定义

| 市场 | 开市时间 | 收市时间 | 午休 |
|------|----------|----------|------|
| A 股 | 09:30 | 15:00 | 11:30-13:00 |

## 接口

### 调度任务

| 任务 ID | 触发器 | 函数 | max_instances |
|---------|--------|------|---------------|
| `watchlist_full_analysis` | Cron(0 2 * * *) | `full_analysis_job()` | 1 |
| `watchlist_morning_quick` | Cron(9:20-55/5 mon-fri) | `quick_analysis_job()` | 1 |
| `watchlist_morning_quick_10` | Cron(10 */5 mon-fri) | `quick_analysis_job()` | 1 |
| `watchlist_morning_quick_11` | Cron(11:0-30/5 mon-fri) | `quick_analysis_job()` | 1 |
| `watchlist_afternoon_quick` | Cron(13-14 */5 mon-fri) | `quick_analysis_job()` | 1 |
| `watchlist_afternoon_quick_close` | Cron(15:0 mon-fri) | `quick_analysis_job()` | 1 |
| `watchlist_high_freq_batch` | Interval(2min) | `high_frequency_batch_job()` | 1 |
| `watchlist_reconciliation` | Interval(5min) | `reconciliation_job()` | 1 |

### SchedulerService 公开方法

| 方法 | 用途 |
|------|------|
| `start(persist=True)` | 启动调度器 + 持久化状态 |
| `stop(persist=True)` | 停止调度器 |
| `restore_state()` | 启动时恢复持久化的监控状态 |
| `get_jobs()` | 列出所有 Job 元数据 |
| `trigger_job(job_id)` | 手动触发指定 Job |
| `is_running` (property) | 调度器是否运行中 |

### 管理端点

调度器管理通过 Watchlist Router 暴露（非独立 scheduler router）。

### 命令行

```bash
# 启动调度器（集成模式，随 API 启动）
python start_api.py

# 手动触发 Job（通过 API）
curl -X POST http://localhost:8000/api/v1/watchlist/trigger-job/{job_id}
```

## 依赖

### 外部依赖

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| apscheduler | >=3.10.0 | BackgroundScheduler 任务调度 |
| pytz | >=2023.3 | 时区处理 |

### 内部依赖

- `webapi/services/queue_service.py` — AnalysisQueueService（入队/对账）
- `webapi/services/analysis_service.py` — AnalysisService（任务执行）
- `webapi/services/notification_service.py` — NotificationService（转折通知）
- `webapi/models/database.py` — Watchlist, WatchlistAnalysis, WatchlistConfig, AnalysisTask
- `tradingagents/default_config.py` — 默认配置

## 转折检测算法

详见 `.openspec/conventions-watchlist.md` 第 4.3 节"转折检测规则"。

核心逻辑：计算 importance 评分（信号反转 0.9 + 置信度突破 0.6 + 风险变化 0.3~0.4 + 市场警报 0.95），达到 0.5 或触发 2+ 维度即为转折点。

## 对账机制

`reconciliation_job()` 每 5 分钟执行四层对账：

1. **Queue 层**: `analysis_queue` 中 PROCESSING 超时 → 重置为 QUEUED
2. **Task 层**: `analysis_tasks` 中 RUNNING 超时 → 标记 FAILED
3. **Watchlist 层**: `watchlist_analyses` 未完成但关联 Task 已完成 → 补完（使用 `FOR UPDATE SKIP LOCKED`）
4. **HF 标记**: 过期的 `is_high_frequency='Y'` → 重置为 'N'

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| `full_analysis_job` 未实现 | Placeholder | 函数体只有 `pass` |
| `quick_analysis_job` 未实现 | Placeholder | 函数体只有 `pass` |
| `_run_watchlist_job_batch` 未实现 | Placeholder | 只返回 `[]` |
| 任务取消 | 待实现 | 无中途取消运行中任务的机制 |
| 任务持久化 | 无 | APScheduler 内存状态，重启后 Job 从头注册 |
| 分布式调度 | 已知限制 | 单进程 BackgroundScheduler，不支持多实例 |
| 节假日处理 | 待优化 | 非交易日仍触发 Job，需接入交易日历 |
| 任务执行超时 | 已知 | 长 analysis 可能跨越下一个调度周期（已设 max_instances=1 防止重叠） |

## 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-05-13 | 1.1.0 | 补全所有"待补充"字段：实际函数签名、行号、数据流、Job 注册表、对账机制、已知问题 |
| 2026-03-28 | 1.0.0 | 初始版本（多个"待补充"占位符） |
