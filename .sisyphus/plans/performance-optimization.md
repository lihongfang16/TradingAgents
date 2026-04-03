# TradingAgents 性能优化实施计划

> **目标**：一次性解决 Phase 1/2/3 的所有性能问题
> **核心策略**：统一执行模型为队列异步，消除同步阻塞和轮询压力
> **预计工期**：2-3 天（含测试验证）

---

## 执行摘要

### 问题根因（Hephaestus 分析）

当前系统慢的根本原因是**三重结构性缺陷**：
1. **调度器与 API 同进程** → 重任务挤占在线路径
2. **轮询驱动而非事件驱动** → DB 被当消息总线用
3. **多执行模型并存** → 队列/同步直跑/调度同步等待混杂

### 核心杠杆点

**统一所有分析执行为队列异步模型**：
- 增量分析 → 走队列（当前直接 `runner.run()`）
- 调度任务 → 仅创建任务，不等待（当前 `run_analysis_sync()`）
- API 请求 → 只提交，通过 SSE/轮询查结果

这能一次性解决资源竞争、忙等轮询、模型不一致三大问题。

### 预期效果

| 指标 | 当前 | 优化后 | 改善 |
|------|------|--------|------|
| 页面渲染（10 股票） | ~30 秒 | <1 秒 | 30x |
| 增量分析阻塞 | 1-3 分钟 | 立即返回 | 异步化 |
| DB 轮询 QPS | 高频（0.5s/2s 间隔） | 事件驱动 | 90%↓ |
| 并发用户支撑 | <5 人 | 10+ 人 | 2x+ |

---

## Phase 1: 紧急修复（Day 1）

### 任务 1.1: 增量分析异步化

**问题**：`incremental_analyze` 端点同步调用 `service.run_incremental()`，阻塞事件循环 1-3 分钟

**位置**：`webapi/routers/watchlist.py:892-896`

**当前代码**：
```python
# Line 889-896
from webapi.services.incremental_analysis_service import IncrementalAnalysisService
service = IncrementalAnalysisService(db)
result = service.run_incremental(
    symbol=watchlist_item.symbol,
    analysis_date=date.today().isoformat(),
    options=options,
)
```

**修复方案**：改为 `asyncio.to_thread()` 或统一走队列

**建议实现**（快速修复）：
```python
# 改为异步执行
result = await asyncio.to_thread(
    service.run_incremental,
    symbol=watchlist_item.symbol,
    analysis_date=date.today().isoformat(),
    options=options,
)
```

**长期方案**（Phase 2）：统一走队列，API 只创建任务

**验收标准**：
- [ ] 增量分析请求立即返回（<100ms），不阻塞其他 API 请求
- [ ] 并发请求测试：同时发起 5 个增量分析，其他接口（如健康检查）响应正常

---

### 任务 1.2: 数据库连接池配置

**问题**：`create_engine()` 无 pool_size/max_overflow 配置，使用默认值（5/10）

**位置**：`webapi/config/database.py:11`

**当前代码**：
```python
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
```

**修复方案**：
```python
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,              # 基础连接数
    max_overflow=20,           # 最大溢出连接
    pool_recycle=300,          # 5 分钟回收
    pool_timeout=10,           # 获取连接超时 10 秒
    echo=False,                # 生产环境关闭 SQL 日志
)
```

**验收标准**：
- [ ] 配置生效，可通过 `engine.pool.size()` 验证
- [ ] 高并发场景下无 "QueuePool limit reached" 错误

---

### 任务 1.3: 修复 func.date() 索引失效

**问题**：`func.date(created_at) == today` 阻止索引使用，导致全表扫描

**位置**：
- `webapi/routers/watchlist.py:831`
- `webapi/services/incremental_analysis_service.py:96`

**当前代码**：
```python
func.date(WatchlistAnalysis.created_at) == today
```

**修复方案**：改为范围查询
```python
from datetime import datetime, timedelta

today_start = datetime.combine(date.today(), datetime.min.time())
tomorrow_start = today_start + timedelta(days=1)

query = query.filter(
    WatchlistAnalysis.created_at >= today_start,
    WatchlistAnalysis.created_at < tomorrow_start,
)
```

**验收标准**：
- [ ] SQL 执行计划显示使用 `idx_watchlist_analyses_watchlist_id` 索引
- [ ] 查询耗时 <50ms（当前可能秒级）

---

### 任务 1.4: 移除 time.sleep() 阻塞

**问题**：多处 `time.sleep()` 阻塞 Streamlit 主线程，最严重的是 `time.sleep(10)` 自动刷新

**位置**：`web/components/watchlist_manager.py`

**所有 sleep 点**：
| 行号 | 值 | 用途 |
|------|-----|------|
| 633 | 1s | 增量分析后延迟 |
| 1053 | 0.5s | 添加股票后 |
| 1204 | 1s | 全量分析后 |
| 1277, 1284 | 0.5s | 监控开关后 |
| 1299 | 0.2s | 批量分析间隔 |
| 1303 | 1s | 批量分析后 |
| 1654 | 0.5s | 设置保存后 |
| **1864** | **10s** | **自动刷新 - 最严重** |

**修复方案**：
1. **删除所有 `time.sleep(1)` 和 `time.sleep(0.5)`**：`st.rerun()` 本身会立即重渲染，sleep 只是人为延迟
2. **替换 `time.sleep(10)` 自动刷新**：使用 `st.cache_data(ttl=10)` 或 `st_autorefresh` 组件

**建议实现**：
```python
# 方案 A：使用 st.cache_data（推荐）
@st.cache_data(ttl=10)
def load_watchlist_cached():
    return load_watchlist()

# 方案 B：使用 st_autorefresh（需安装）
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=10 * 1000, key="watchlist_refresh")
```

**验收标准**：
- [ ] 页面交互无卡顿感
- [ ] 自动刷新不阻塞用户操作

---

## Phase 2: 体验优化（Day 1-2）

### 任务 2.1: 统一分析执行为队列模型

**问题**：三条执行路径不一致
- 常规分析 → 走队列（worker 子进程）
- 增量分析 → 同步直跑（API 进程）
- 调度任务 → 同步等待（调度器线程）

**核心改动**：所有分析统一为"API 创建任务 + 队列异步执行"

#### 2.1.1 增量分析走队列

**位置**：`webapi/routers/watchlist.py:865-907`

**修改方案**：
```python
# 当前：直接执行
service = IncrementalAnalysisService(db)
result = service.run_incremental(...)

# 改为：创建任务并入队
from webapi.services.queue_service import AnalysisQueueService

queue_service = AnalysisQueueService()
task_id = queue_service.enqueue(
    symbol=watchlist_item.symbol,
    analysis_type="incremental",
    analysis_date=date.today().isoformat(),
    options=options,
)

# 立即返回任务 ID，前端通过 SSE 查进度
return {"task_id": task_id, "status": "QUEUED"}
```

#### 2.1.2 调度器改为仅创建任务

**位置**：`webapi/services/scheduler_service.py:199-268` (quick_analysis_job)

**当前代码**：
```python
for watchlist in watchlists:
    task = analysis_service.create_task(request)
    result = analysis_service.run_analysis_sync(
        task.task_id, request, priority=10, timeout=300
    )  # ← 同步等待！
```

**修改方案**：
```python
from webapi.services.queue_service import AnalysisQueueService

queue_service = AnalysisQueueService()

for watchlist in watchlists:
    task = analysis_service.create_task(request)
    queue_service.enqueue(task.task_id)  # ← 只入队，不等待
    
# 调度器 job 立即完成，不阻塞
```

**验收标准**：
- [ ] 调度器 job 执行时间 <1 秒（当前 5-30 分钟）
- [ ] API 和调度器无资源竞争
- [ ] 所有分析任务在 `analysis_tasks` 表中有统一状态流转

---

### 任务 2.2: 批量查询 API

**问题**：前端 N+1 请求 — 10 只股票产生 30+ 次 API 调用

**位置**：
- `web/components/watchlist_manager.py:1182-1184`（调用点）
- `_is_analysis_running()`, `_has_full_analysis_today()`, `_has_multiple_analyses_today()`

**新增 API**：`GET /api/v1/watchlist/analysis-status`

**后端实现**：
```python
@router.get("/analysis-status", response_model=List[WatchlistAnalysisStatusResponse])
async def get_watchlist_analysis_status(
    symbols: List[str] = Query(..., description="List of stock symbols"),
    db: Session = Depends(get_db)
):
    """批量查询多只股票的分析状态，替代 N+1 请求"""
    
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # 单条 SQL 搞定所有查询
    results = db.query(
        AnalysisTask.symbol,
        func.bool_or(AnalysisTask.status.in_(['RUNNING', 'PENDING'])).label('is_analyzing'),
        func.bool_and(
            AnalysisTask.analysis_type == 'full',
            AnalysisTask.status == 'COMPLETED',
            AnalysisTask.created_at >= today_start
        ).label('has_full_today'),
        func.count().filter(
            AnalysisTask.status == 'COMPLETED',
            AnalysisTask.created_at >= today_start
        ).label('completed_count')
    ).filter(
        AnalysisTask.symbol.in_(symbols)
    ).group_by(AnalysisTask.symbol).all()
    
    return results
```

**前端修改**：
```python
# 原来：每只股 3 次请求
for symbol in symbols:
    is_analyzing = _is_analysis_running(symbol)
    has_full = _has_full_analysis_today(symbol)
    has_multiple = _has_multiple_analyses_today(symbol)

# 改为：1 次批量请求
statuses = requests.get(
    f"{API_URL}/api/v1/watchlist/analysis-status",
    params={"symbols": symbols}  # 批量
).json()
```

**验收标准**：
- [ ] 10 只股票的 watchlist 页面渲染 <1 秒（当前 ~30 秒）
- [ ] 网络请求数从 30+ 减少到 3 个以内

---

### 任务 2.3: 调度器任务并行化

**问题**：调度器串行处理股票，10 只 × 30s = 5 分钟，超过调度间隔

**位置**：`webapi/services/scheduler_service.py:226-263`

**修改方案**：使用 `asyncio.gather()` 并行入队

```python
import asyncio

async def enqueue_analysis(watchlist):
    task = analysis_service.create_task(request)
    queue_service.enqueue(task.task_id)
    return task.task_id

# 并行处理所有股票
tasks = [enqueue_analysis(w) for w in watchlists]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**验收标准**：
- [ ] 10 只股票的 quick analysis job 完成 <5 秒
- [ ] 无 job 堆积（调度间隔 5 分钟，执行时间 <5 秒）

---

### 任务 2.4: 统一 Session 管理

**问题**：`SessionLocal()` 散落在各处，事务边界不清

**修改方案**：统一使用上下文管理器

```python
# webapi/services/db_utils.py
from contextlib import contextmanager
from webapi.config.database import SessionLocal

@contextmanager
def db_session():
    """统一的数据库会话上下文管理器"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# 使用示例
def create_task(request):
    with db_session() as db:
        task = AnalysisTask(...)
        db.add(task)
        return task
```

**需要修改的文件**：
- `analysis_service.py`（所有方法）
- `queue_service.py`
- `scheduler_service.py`
- `create_analysis_complete_callback()`

**验收标准**：
- [ ] 所有数据库操作使用统一的 `db_session()` 上下文
- [ ] 无散落式 `SessionLocal()` 创建

---

## Phase 3: 进阶优化（Day 2-3）

### 任务 3.1: SSE 重构为事件驱动

**问题**：SSE 每 2 秒轮询 DB，并发连接数上来后 DB 压力过大

**位置**：`webapi/routers/analysis.py:129-184`

**修改方案**：使用 PostgreSQL NOTIFY/LISTEN

```python
# 1. 任务状态变更时发送通知
# 在 queue_service.py 或 analysis_service.py 中
def update_task_status(task_id: str, status: str):
    with db_session() as db:
        db.execute(
            text("NOTIFY analysis_progress, :payload"),
            {"payload": json.dumps({"task_id": task_id, "status": status})}
        )

# 2. SSE 端点监听通知
@router.get("/{task_id}/progress")
async def get_progress(task_id: str):
    async def event_generator():
        # 建立数据库监听连接
        async with asyncpg.connect(DATABASE_URL) as conn:
            await conn.add_listener('analysis_progress', listener)
            
            while True:
                # 等待通知，而非轮询
                msg = await notification_queue.get()
                yield msg
    
    return EventSourceResponse(event_generator())
```

**简化方案**（如果不引入 asyncpg）：
- 增加轮询间隔动态退避：2s → 5s → 10s（任务运行越久，查询越稀疏）
- 任务完成后立即发送最后一次更新，而非等前端轮询到

**验收标准**：
- [ ] SSE 连接数 10+ 时，DB CPU 使用率 <20%
- [ ] 进度更新延迟 <3 秒（当前平均 1 秒，但负载高时恶化）

---

### 任务 3.2: 缓存主链路化

**问题**：`CachedAnalysisRunner` 存在但未成为唯一主链路

**修改方案**：

1. **Worker 统一使用 CachedAnalysisRunner**
   ```python
   # webapi/subprocess_runner.py
   from tradingagents.core.cached_analysis_runner import CachedAnalysisRunner
   
   runner = CachedAnalysisRunner()  # 替代 AnalysisRunner
   ```

2. **缓存 TTL 策略优化**
   - market: 15 分钟（股价变化快）
   - sentiment: 2 小时（情绪变化中等）
   - news: 2 小时（新闻更新频率）
   - fundamentals: 24 小时（基本面变化慢）

3. **缓存预热**
   - 调度器在开盘前预热热门股票的 market analysis

**验收标准**：
- [ ] 缓存命中率 >60%
- [ ] 平均分析耗时减少 50%

---

### 任务 3.3: 消除重复代码

**问题**：`detect_turning_point()` 两份实现

**位置**：
- `webapi/routers/watchlist.py:285`
- `webapi/services/scheduler_service.py:33`

**修改方案**：

```python
# webapi/services/turning_point_service.py
from typing import Tuple

def detect_turning_point(
    current_result: Dict[str, Any],
    previous_result: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str, float]:
    """统一的转折点检测逻辑"""
    # 合并两份实现，以 scheduler_service.py 版本为基础
    # 返回元组 (is_turning, reason, importance_score)
    ...

# watchlist.py 中的 Pydantic 包装
def detect_turning_point_api(...) -> TurningDetectionResponse:
    is_turning, reason, score = turning_point_service.detect_turning_point(...)
    return TurningDetectionResponse(
        is_turning_point=is_turning,
        reason=reason,
        importance_score=score
    )
```

**验收标准**：
- [ ] 单点修改，两边生效
- [ ] 逻辑一致性验证通过

---

## 实施顺序与依赖关系

```
Phase 1（紧急修复）
├── 1.1 增量分析异步化 [独立]
├── 1.2 连接池配置 [独立]
├── 1.3 func.date() 修复 [依赖：无]
└── 1.4 移除 time.sleep() [独立]

Phase 2（体验优化）
├── 2.1 统一队列模型 [依赖：1.1]
│   ├── 2.1.1 增量分析走队列
│   └── 2.1.2 调度器改为仅入队
├── 2.2 批量查询 API [独立，可并行]
├── 2.3 调度器并行化 [依赖：2.1.2]
└── 2.4 统一 Session [依赖：2.1]

Phase 3（进阶优化）
├── 3.1 SSE 重构 [依赖：2.1]
├── 3.2 缓存主链路化 [依赖：2.1]
└── 3.3 消除重复代码 [独立]
```

---

## 风险控制

### 高风险项

| 任务 | 风险 | 缓解措施 |
|------|------|----------|
| 2.1 统一队列模型 | 执行路径变更大，可能引入 bug | 保留原有代码路径作为 fallback，通过 feature flag 切换 |
| 3.1 SSE 重构 | NOTIFY/LISTEN 需要额外库 | 先实现简化方案（动态退避），再考虑 NOTIFY |

### 测试策略

1. **单元测试**：每个修改的函数都要有测试覆盖
2. **集成测试**：端到端测试分析流程（创建→入队→执行→查询结果）
3. **性能测试**：
   - 10 股票 watchlist 页面渲染时间
   - 并发 5 用户同时发起分析
   - DB 连接池监控
4. **回滚计划**：每个 Phase 独立可回滚

---

## 监控与验收

### 关键指标

| 指标 | 当前基线 | 目标值 | 监控方式 |
|------|----------|--------|----------|
| 页面渲染时间 | ~30s | <1s | 前端日志 |
| API P99 延迟 | ~3s | <500ms | FastAPI 中间件 |
| DB QPS | 高频 | 减少 90% | PostgreSQL 日志 |
| 连接池使用率 | 峰值 100% | <70% | SQLAlchemy 事件 |
| 缓存命中率 | 未知 | >60% | 应用日志 |

### 验收清单

- [ ] Phase 1 所有任务完成并通过测试
- [ ] Phase 2 所有任务完成，watchlist 页面渲染 <1 秒
- [ ] Phase 3 可选，但推荐完成 SSE 优化
- [ ] 端到端测试通过：创建分析 → 队列执行 → 结果查询
- [ ] 并发测试通过：10 用户同时操作无错误

---

## 结论

**先做任务 2.1（统一队列模型）**，这是 Hephaestus 指出的唯一杠杆点，能同时解决三大结构性问题。其他任务都是在此基础上锦上添花。

如果资源有限，**最小可行方案**是：
1. 任务 1.1（增量分析异步化）- 立即缓解阻塞
2. 任务 2.1（统一队列模型）- 根本性解决
3. 任务 2.2（批量查询 API）- 解决前端卡顿

这三项完成后，系统性能会有质的飞跃。
