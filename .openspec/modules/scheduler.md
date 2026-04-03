# 定时任务调度 (Scheduler)

> 类型: 全新 | 层级: 基础设施 | 上游对应: 无

## 概述

定时任务调度模块基于APScheduler构建，提供自动化分析任务的调度与执行能力。上游TradingAgents库为手动触发式分析，本模块新增完整的定时任务基础设施，支持定时全量分析、交易时段快速分析、以及批量任务处理。

调度策略针对A股市场交易时间设计：全量分析安排在盘后凌晨，快速分析覆盖交易时段，批量处理器定期轮询待处理任务队列。

## 架构

### 组件结构

```
[待补充 — 需确认scheduler具体实现位置]

可能的实现位置：
webapi/
├── scheduler.py                 # APScheduler配置与任务定义
├── jobs/                        # 任务实现目录
│   ├── __init__.py
│   ├── daily_analysis.py        # 每日全量分析任务
│   ├── market_hours_quick.py    # 交易时段快速分析
│   └── batch_processor.py       # 批量任务处理器
└── main.py                      # 调度器启动入口（集成FastAPI）
```

**备选结构**（如为独立模块）：

```
scheduler/                       # 独立调度模块
├── __init__.py
├── config.py                    # 调度配置
├── scheduler.py                 # APScheduler实例
├── jobs/                        # 任务定义
│   ├── __init__.py
│   ├── daily_full_analysis.py
│   ├── market_quick_analysis.py
│   └── batch_task_processor.py
└── main.py                      # 独立启动入口
```

### 核心类/函数

| 符号 | 类型 | 位置 | 功能描述 |
|------|------|------|----------|
| `SchedulerManager` | 类 | `[待补充]` | APScheduler实例管理 |
| `schedule_daily_analysis()` | 函数 | `[待补充]` | 注册每日全量分析任务 |
| `schedule_market_hours()` | 函数 | `[待补充]` | 注册交易时段任务 |
| `run_batch_processor()` | 函数 | `[待补充]` | 执行批量任务处理 |
| `is_market_open()` | 函数 | `[待补充]` | 判断当前是否交易时段 |

### 数据流

```
APScheduler触发 → 任务函数执行
                        ↓
            ┌───────────────────────┐
            ↓                       ↓
    定时分析任务              批量处理器
            ↓                       ↓
    AnalysisService       查询待处理队列
            ↓                       ↓
    执行分析 → 存储结果    依次执行队列任务
```

## 与上游的关系

| 方面 | 说明 |
|------|------|
| 继承 | 无直接继承 |
| 新增 | 完整的定时调度能力、交易时间感知、批量处理逻辑 |
| 修改 | 无 |
| 集成 | 通过`AnalysisService`调用分析功能 |

**调度策略**:

| 任务类型 | 触发时间 | 用途 |
|----------|----------|------|
| 全量分析 | 每日02:00 CST | 盘后深度分析所有关注股票 |
| 快速分析 | 9:30-15:00 CST | 交易时段实时监控 |
| 批量处理 | 每2分钟 | 处理队列中的待分析任务 |

## 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 启用调度器 | `ENABLE_SCHEDULER` | true | 是否启动定时任务 |
| 全量分析时间 | `DAILY_ANALYSIS_TIME` | 02:00 | 每日全量分析执行时间 |
| 快速分析间隔 | `QUICK_ANALYSIS_INTERVAL` | 30 | 交易时段快速分析间隔（分钟） |
| 批量处理间隔 | `BATCH_INTERVAL` | 120 | 批量处理器轮询间隔（秒） |
| 时区 | `SCHEDULER_TIMEZONE` | Asia/Shanghai | 调度器时区设置 |

### 交易时间定义

| 市场 | 开市时间 | 收市时间 | 午休 |
|------|----------|----------|------|
| A股 | 09:30 | 15:00 | 11:30-13:00 |

## 接口

### 调度任务

| 任务ID | 触发器 | 函数 |
|--------|--------|------|
| `daily_full_analysis` | Cron(0 2 * * *) | `jobs.daily_full_analysis.run()` |
| `market_hours_quick` | Interval(30min), 9:30-15:00 | `jobs.market_quick_analysis.run()` |
| `batch_processor` | Interval(2min) | `jobs.batch_processor.run()` |

### 管理API

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/scheduler/jobs` | 列出所有调度任务 |
| POST | `/api/v1/scheduler/jobs/{id}/pause` | 暂停指定任务 |
| POST | `/api/v1/scheduler/jobs/{id}/resume` | 恢复指定任务 |
| POST | `/api/v1/scheduler/trigger/{id}` | 立即触发任务 |

### 命令行

```bash
# 启动调度器（集成模式）
python start_api.py  # 调度器随API服务启动

# 独立启动调度器（如适用）
python -m scheduler.main

# 手动触发任务
python -m scheduler.trigger daily_full_analysis
```

## 依赖

### 外部依赖

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| apscheduler | >=3.10.0 | 任务调度框架 |
| pytz | >=2023.3 | 时区处理 |
| tzlocal | >=5.0 | 本地时区检测 |

### 内部依赖

- `webapi/services/analysis_service.py` — 分析任务服务
- `tradingagents/default_config.py` — 默认配置

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| 任务持久化 | 待补充 | [待确认]是否配置任务持久化存储 |
| 分布式调度 | 已知限制 | 当前为单节点调度器，不支持多实例 |
| 节假日处理 | 待优化 | 需手动配置A股休市日期 |
| 任务执行超时 | 已知 | 长分析任务可能跨越下个调度周期 |
| 调度器具体位置 | 待确认 | 实现文件的具体路径需核实 |

## 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| [待补充] | [待补充] | [待补充] |

