# 自选股自动分析子系统 — 管理规约

> 版本: 1.1.0 | 生效范围: `webapi/` 中与 watchlist/scheduler/queue 相关的所有模块
> 目标读者: AI agent + 开发者（后续所有代码变更必须符合本规约）
>
> ⚠️ **最高优先级原则**: 本规约仅管理下游代码 (`webapi/`, `cli/`, `web/`, `alembic/`)。
> 上游代码 (`tradingagents/`) 应尽量不更改。详见 §0。

---

## 0. 上游隔离原则（最高优先级）

本原则优先级高于所有其他规约。任何与之冲突的做法都必须先获得明确批准。

### 0.1 代码分层定义

```
┌─────────────────────────────────────────────────────────┐
│                    上游代码 (UPSTREAM)                    │
│  tradingagents/                                          │
│  ├── agents/        # 11 个 agent 实现                   │
│  ├── graph/         # LangGraph 编排                     │
│  ├── dataflows/     # 数据源 (含 A-share 定制)           │
│  ├── llm_clients/   # LLM 客户端工厂                     │
│  ├── core/          # AnalysisRunner                     │
│  └── default_config.py                                   │
│                                                          │
│  规则: 只做 merge 同步，不做功能性修改                     │
│  例外: 修复 import/兼容性问题时可最小改动                  │
├─────────────────────────────────────────────────────────┤
│                    下游代码 (DOWNSTREAM)                   │
│  webapi/            # FastAPI 后端                       │
│  web/               # Streamlit 前端                     │
│  cli/               # Typer CLI                          │
│  alembic/           # DB 迁移                            │
│  scripts/           # 运维脚本                           │
│                                                          │
│  规则: 本规约完全管辖，所有变更必须符合                    │
└─────────────────────────────────────────────────────────┘
```

### 0.2 上游代码变更规则

| 变更类型 | 是否允许 | 审批要求 | 示例 |
|----------|----------|----------|------|
| 从上游 merge 新版本 | ✅ 允许 | 无需审批 | `git merge upstream/main -X theirs` |
| 修复 import/兼容性 | ✅ 允许 | 需在 commit message 注明原因 | 合并后缺少 `import operator` |
| A-share 数据层扩展 | ⚠️ 谨慎 | 需确认无 webapi 层替代方案 | `china_data_manager.py` 新增 provider |
| Agent 行为修改 | ❌ 禁止 | 除非上游变更导致不兼容 | 不要改 agent 的 system prompt |
| Graph 流程修改 | ❌ 禁止 | 除非上游变更导致不兼容 | 不要新增 LangGraph node |
| LLM client 修改 | ❌ 禁止 | 除非添加新 provider 支持 | — |

### 0.3 下游适配优先策略

当需要新功能时，按以下顺序尝试，**只有前一级行不通才降级到下一级**：

```
Level 1 (首选): 纯 webapi 层实现
  ├── 新增 Service / Router / Model
  └── 例: 新增批量分析 → 在 QueueService 中实现

Level 2 (次选): 通过配置扩展
  ├── 修改 DEFAULT_CONFIG 或 WatchlistConfig
  └── 例: 调整分析频率 → 修改调度器配置

Level 3 (最后): 扩展 tradingagents 层（需审批）
  ├── 新增独立文件/模块（不修改已有文件）
  └── 例: 新增 A-share 数据 provider → 新建 xxx_provider.py

Level 4 (禁止): 修改已有上游文件
  └── 仅 merge 同步时被动接受
```

### 0.4 上游 merge 后的修复流程

每次从上游 merge 后，允许做以下最小修复：

1. **Import 修复**: 添加缺失的 import（如 `import operator`）
2. **兼容性修复**: 调整下游代码以适配上游 API 变更
3. **A-share hook 修复**: 恢复 `build_full_context` 等 A-share 集成点

修复后必须验证 `pip install -e .` 和关键 import 通过。

---

## 1. 架构边界规约

### 1.1 模块职责矩阵

每个模块有且仅有一个职责。严禁跨层调用。

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Scheduler   │───▶│  Queue /     │───▶│  Analysis    │
│  Service     │    │  Analysis    │    │  Runner      │
│  (触发器)    │    │  Service     │    │  (执行器)    │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │  TradingAgents│
                                        │  Graph        │
                                        │  (上游引擎)   │
                                        └──────────────┘
```

| 模块 | 文件位置 | 职责 | 禁止事项 |
|------|----------|------|----------|
| SchedulerService | `webapi/services/scheduler_service.py` | 定时触发、转折检测、HF升降频、对账 | ❌ 禁止直接调用 AnalysisRunner 或 TradingAgentsGraph |
| AnalysisQueueService | `webapi/services/queue_service.py` | 任务入队、优先级排序、重试、状态流转 | ❌ 禁止包含业务逻辑（如转折判断） |
| AnalysisService | `webapi/services/analysis_service.py` | 任务 CRUD、异步执行、进度追踪 | ❌ 禁止直接操作 watchlist 表 |
| Queue Routers | `webapi/routers/queue.py` | HTTP 入口、参数校验、响应格式化 | ❌ 禁止包含调度逻辑 |
| Watchlist Routers | `webapi/routers/watchlist.py` | 自选股 CRUD、手动触发入口 | ❌ 禁止直接执行分析 |
| DB Models | `webapi/models/database.py` | ORM 映射、to_dict/from_dict 序列化 | ❌ 禁止包含业务逻辑方法（except 查询辅助） |

### 1.2 依赖方向规则

```
允许: SchedulerService → QueueService → AnalysisService → AnalysisRunner
允许: Routers → 对应 Service 层
允许: Service 层 → DB Models
允许: _finalize_watchlist_analysis → NotificationService

禁止: AnalysisRunner → webapi/* (上游隔离原则)
禁止: DB Models → Service 层 (反向依赖)
禁止: Router → 其他 Router (跨路由调用)
禁止: SchedulerService → AnalysisRunner (必须经过 Queue)
```

### 1.3 上游隔离（引用）

详见 §0"上游隔离原则"。以下为补充的依赖方向约束：

```
桥接层: AnalysisRunner 是 webapi/ 调用 tradingagents/ 的唯一通道
        ┌─────────────────────────────────┐
        │  webapi/  ──AnalysisRunner──▶ tradingagents/  │
        │  (下游)                        (上游)         │
        └─────────────────────────────────┘

禁止: webapi 中直接 from tradingagents.agents import ...
禁止: webapi 中直接 from tradingagents.graph import ...
允许: from tradingagents.core.analysis_runner import AnalysisRunner
允许: from tradingagents.default_config import DEFAULT_CONFIG
允许: from tradingagents.dataflows.interface import is_a_share  (路由辅助)
```

---

## 2. 状态机规约

### 2.1 AnalysisTask 状态机

```
PENDING ──▶ RUNNING ──┬──▶ COMPLETED
                       └──▶ FAILED
                       └──▶ CANCELLED (待实现)
```

| 状态 | 含义 | 可转换到 | 设置者 |
|------|------|----------|--------|
| PENDING | 任务已创建，等待执行 | RUNNING | AnalysisService.create_task() |
| RUNNING | 分析正在执行 | COMPLETED, FAILED | AnalysisRunner 回调 |
| COMPLETED | 分析成功完成 | 终态 | AnalysisRunner 回调 |
| FAILED | 分析失败 | 终态 | AnalysisRunner 回调 |

**规约**:
- 状态转换必须原子更新：`task.status = new_status; task.updated_at = now; db.commit()`
- RUNNING → COMPLETED/FAILED 时必须同时设置 `completed_at`
- 严禁回退状态（COMPLETED → PENDING 等）

### 2.2 AnalysisQueue 状态机

```
QUEUED ──▶ PROCESSING ──┬──▶ COMPLETED
                         ├──▶ FAILED (retry_count < max_retries → 重新 QUEUED)
                         └──▶ FAILED (永久失败)
```

| 状态 | 含义 | 设置者 |
|------|------|--------|
| QUEUED | 等待 worker 拾取 | QueueService.enqueue() |
| PROCESSING | worker 正在执行 | QueueService.claim_next() |
| COMPLETED | 执行完成 | Worker 回调 |
| FAILED | 执行失败 | Worker 回调 + 重试逻辑 |

**重试规约**:
- 默认 `max_retries = 3`
- 每次重试递增 `retry_count`
- 重试时状态回退到 QUEUED，`worker_id = NULL`
- 超过 max_retries 永久标记 FAILED

### 2.3 Watchlist 高频监控状态

```
Normal ◀── high_freq_until 过期 ── HighFrequency
  │                                     ▲
  └───── detect_turning_point() ────────┘
```

| 状态标志 | 含义 | 触发条件 |
|----------|------|----------|
| `is_high_frequency='N'` | 常规频率监控 | 默认状态 / HF 窗口过期 |
| `is_high_frequency='Y'` | 高频监控（2min/次） | 检测到转折点 |
| `high_freq_until` | HF 窗口截止时间 | 转折检测时设为 `now + 10min` |

**降频规约**:
- 连续 N 次（`DEFAULT_STABLE_THRESHOLD=3`）分析结果稳定（信号不变 + 风险不变 + 置信度波动 < 0.10）→ 退出 HF
- `reconcile_expired_hf_flags()` 每 5 分钟清理过期 HF 标记
- 严禁手动设置 `is_high_frequency='Y'` 而不设置 `high_freq_until`

---

## 3. 数据规约

### 3.1 表所有权

每张表有明确的"写入者"。其他模块只能读取，不能直接写入。

| 表 | 主要写入者 | 读取者 |
|----|-----------|--------|
| `analysis_tasks` | AnalysisService | QueueService, SchedulerService, Router |
| `analysis_queue` | AnalysisQueueService | SchedulerService (reconciliation), Router |
| `watchlist` | Watchlist Router, `_finalize_watchlist_analysis` | SchedulerService, UI |
| `watchlist_analyses` | `_finalize_watchlist_analysis`, SchedulerService jobs | Router, UI |
| `watchlist_config` | SchedulerService._persist_monitoring_state() | SchedulerService |
| `analyst_report_cache` | AnalysisCacheService | AnalysisService |

**写入规约**: `watchlist` 表的 `last_signal/last_confidence/last_risk_level/last_price` 字段**仅**由 `_finalize_watchlist_analysis()` 更新。Router 端的 CRUD 只修改基础字段（symbol, name, position 等）。

### 3.2 字段类型约定

本项目对部分数值字段使用 `String` 类型存储，这是**有意为之**的设计决策，后续变更不得擅自修改：

| 字段 | DB 类型 | 原因 |
|------|---------|------|
| `confidence` | `String(10)` | 存储浮点数字符串，避免 PostgreSQL Float 精度丢失 |
| `last_price` | `String(20)` | 兼容不同精度的价格数据源 |
| `last_change_pct` | `String(10)` | 百分比字符串 |
| `is_active` | `String(1)` Y/N | A-share 惯例，兼容 Oracle 风格 |
| `is_high_frequency` | `String(1)` Y/N | 同上 |

**规约**:
- 新增布尔字段统一使用 `String(1)` + `Y/N`，与现有字段保持一致
- `to_dict()` 负责将 Y/N 转换为 Python bool，`from_dict()` 负责反向转换
- 新增数值字段如果需要精确比较，使用 `String` + `to_float()` 辅助函数

### 3.3 数据生命周期

```
分析数据生命周期:

[创建]  AnalysisTask (PENDING)
           │
           ▼
[执行]  AnalysisTask (RUNNING/COMPLETED) + WatchlistAnalysis (未完成)
           │
           ▼
[完成]  _finalize_watchlist_analysis() → WatchlistAnalysis (已完成)
           │                              + Watchlist (状态更新)
           ▼
[对账]  reconciliation_job() 每5分钟扫描:
        - WatchlistAnalysis.completed_at IS NULL 但 AnalysisTask.COMPLETED → 补完
        - AnalysisQueue 超时未完成 → 重置为 QUEUED
        - HF 标记过期 → 清除
           │
           ▼
[清理]  (待实现) 历史数据归档策略:
        - analysis_tasks: 保留最近 90 天
        - watchlist_analyses: 保留最近 180 天
        - analyst_report_cache: TTL 自动过期
```

### 3.4 缓存 TTL 策略

| Analyst 类型 | TTL | 原因 |
|-------------|-----|------|
| market | 15 分钟 | 盘中价格变化频繁 |
| sentiment | 2 小时 | 情绪数据更新较慢 |
| news | 2 小时 | 新闻时效性中等 |
| fundamentals | 24 小时 | 财务数据日级别更新 |

**新增 analyst 类型的缓存 TTL 必须在 `AnalystReportCache.TTL_CONFIG` 中注册**。

---

## 4. 调度规约

### 4.1 调度策略

| Job ID | 触发器 | 调用函数 | 用途 |
|--------|--------|----------|------|
| `watchlist_full_analysis` | Cron(02:00 daily) | `full_analysis_job()` | 盘后全量深度分析 |
| `watchlist_morning_quick` | Cron(09:20-09:55 /5min, mon-fri) | `quick_analysis_job()` | 早盘快速分析 |
| `watchlist_morning_quick_10` | Cron(10:00-10:55 /5min, mon-fri) | `quick_analysis_job()` | 上午盘快速分析 |
| `watchlist_morning_quick_11` | Cron(11:00-11:30 /5min, mon-fri) | `quick_analysis_job()` | 午盘前快速分析 |
| `watchlist_afternoon_quick` | Cron(13:00-14:55 /5min, mon-fri) | `quick_analysis_job()` | 午后盘快速分析 |
| `watchlist_afternoon_quick_close` | Cron(15:00, mon-fri) | `quick_analysis_job()` | 收盘分析 |
| `watchlist_high_freq_batch` | Interval(2min) | `high_frequency_batch_job()` | 高频监控批次 |
| `watchlist_reconciliation` | Interval(5min) | `reconciliation_job()` | 状态对账 |

**规约**:
- 所有 Job 必须设 `max_instances=1`，防止并发执行导致状态冲突
- 新增 Job 必须注册在 `SchedulerService._setup_jobs()` 和 `trigger_job()` 的 `job_handlers` 字典中
- 调度时区统一使用 `Asia/Shanghai`
- Test mode 通过 `SCHEDULER_TEST_MODE=true` 激活，所有 Job 降为 1-2 分钟间隔

### 4.2 分析类型与触发方式

| analysis_type | 含义 | triggered_by | 执行模式 |
|---------------|------|--------------|----------|
| `full` | 11 agent 全量分析 | `scheduled` | AnalysisRunner(fast_mode=False) |
| `quick` | 仅市场分析师 | `scheduled`, `manual` | AnalysisRunner(fast_mode=True) |
| `turning` | 转折确认（快速） | `turning` | AnalysisRunner(fast_mode=True) |

**新增 analysis_type 必须同时更新**:
1. `WatchlistAnalysis.analysis_type` Column 注释
2. `_run_watchlist_job_batch()` 的参数文档
3. Watchlist Router 中的触发入口

### 4.3 转折检测规则

转折检测算法在 `detect_turning_point()` 中实现。评分规则：

| 检测维度 | 触发条件 | importance 权重 |
|----------|----------|-----------------|
| 信号反转 | BULLISH ↔ BEARISH | +0.9 |
| 置信度突破 | 跳变 ≥ 0.15 且当前 > 0.8 | +0.6 |
| 风险变化 | risk_level 变化 | +0.3~0.4 |
| 市场警报 | 含"异常/紧急/熔断/暴跌/暴涨" | +0.95 |

**判定**: `importance ≥ 0.5` 或 `触发维度 ≥ 2` → 判定为转折点

**规约**: 转折检测逻辑的修改必须同步更新本规约和 `_normalize_signal()` 的映射表。

---

## 5. 错误处理规约

### 5.1 错误分级

| 级别 | 含义 | 处理方式 | 示例 |
|------|------|----------|------|
| 可重试 | 临时性失败 | Queue 重试（max 3 次） | API 超时、数据源临时不可用 |
| 不可重试 | 永久性失败 | 标记 FAILED，记录 error | 无效股票代码、API Key 失效 |
| 部分失败 | 分析完成但部分 agent 失败 | 标记 COMPLETED，result 中记录失败部分 | 某个 analyst 超时 |

### 5.2 超时设置

| 场景 | 超时 | 来源 |
|------|------|------|
| 全量分析 | 1800 秒 (30 min) | `ANALYSIS_TIMEOUT` 环境变量 |
| 快速分析 | 300 秒 (5 min) | QueueService 默认 |
| HF batch 单只 | 180 秒 (3 min) | `high_frequency_batch_job` 参数 |
| 单次 API 调用 | 60 秒 | per-API-call timeout |
| 对账扫描 | 无独立超时 | 依赖 DB 查询超时 |

### 5.3 对账规约

`reconciliation_job()` 每 5 分钟执行，负责三层对账：

1. **Queue 层**: `analysis_queue` 中 PROCESSING 超过 N 分钟的 → 重置为 QUEUED
2. **Task 层**: `analysis_tasks` 中 RUNNING 超过 N 分钟的 → 标记 FAILED
3. **Watchlist 层**: `watchlist_analyses` 中 completed_at IS NULL 但关联 AnalysisTask 已 COMPLETED → 补完

**规约**: 对账函数使用 `FOR UPDATE SKIP LOCKED` 模式，防止多实例并发对账。

---

## 6. API 规约

### 6.1 路由注册规范

新增自选股相关 API 端点必须：

1. 注册在对应 Router 文件中（`watchlist.py` 或 `queue.py`）
2. 使用 `/api/v1/` 前缀
3. 响应格式统一为 JSON
4. DELETE 操作返回 `204 No Content`
5. 错误响应使用 `HTTPException` + 标准 `detail` 字段

### 6.2 SSE 进度流规约

- 端点路径: `/api/v1/analysis/{task_id}/progress`
- 事件类型: `progress`, `complete`, `error`
- 数据格式: `{"task_id": "...", "agent": "...", "progress": 45, "status": "running"}`
- 完成时发送 `event: complete` 后关闭连接

### 6.3 分页规约

- 列表查询支持 `limit` 和 `offset` 参数
- 默认 `limit=50`，最大 `limit=200`
- 返回格式包含 `total` 总数字段

---

## 7. 变更控制规约

### 7.1 数据库变更

- 新增表/字段 → 必须创建 Alembic migration (`alembic revision --autogenerate`)
- migration 文件命名: `<内容描述>.py`
- 索引命名: `ix_<table>_<column>` 或 `idx_<table>_<columns>`
- 新增 Column 必须同步更新 `to_dict()` 和 `from_dict()` 方法

### 7.2 调度变更

- 新增/修改 Job → 必须更新本规约的"调度策略"表格
- 修改 Cron 表达式 → 必须评估对 LLM API 调用量的影响
- 修改分析频率 → 必须评估并发 AnalysisTask 数量是否超过 `MAX_CONCURRENT_ANALYSIS`

### 7.3 TODO/Placeholder 处理

当前代码中存在以下 placeholder 函数，实现时必须遵守对应规约：

| 函数 | 状态 | 实现要求 |
|------|------|----------|
| `full_analysis_job()` | Placeholder | 必须通过 QueueService 入队，不能直接执行 |
| `quick_analysis_job()` | Placeholder | 同上 |
| `_run_watchlist_job_batch()` | Placeholder | 必须支持 timeout 和并发控制 |
| 任务取消 | 待实现 | 需要先实现 AnalysisRunner 的取消机制 |

**规约**: 实现 placeholder 时，先读取本规约确认架构边界，再编码。

---

## 8. 已知限制

| 限制 | 影响 | 规避措施 |
|------|------|----------|
| 单进程调度 | 无法水平扩展 | 当前单节点足够，扩展时迁移到 Celery/Dramatiq |
| 节假日未处理 | 非交易日仍会触发 | 待接入交易日历 API |
| 无任务取消 | 手动无法中断分析 | 待实现 |
| 进度报告不完整 | runner 只报一次 60% | 已知 bug，待修复 |
| Y/N 字符串 | 查询需 `== 'Y'` 而非 truthy | to_dict() 已做转换 |
| 高频无上限 | 转折点频发时 HF 窗口持续延长 | 稳定性检测会自动降频 |

---

## 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-05-13 | 1.1.0 | 新增 §0 上游隔离原则（最高优先级），明确下游适配优先策略，强化 merge 修复流程 |
| 2026-05-13 | 1.0.0 | 初始版本：架构边界、状态机、数据规约、调度规约、错误处理 |
