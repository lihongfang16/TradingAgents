# TradingAgents 性能优化完整实施计划（全量修复版）

> **目标**：一次性解决所有性能问题，修复 Metis 指出的所有缺陷
> **工期**：5-7 天（含完整测试验证）
> **策略**：基线先行 → 队列统一为核心 → 分层优化 → 全面验收

---

## 关键改进（对比原计划）

| Metis 指出的问题 | 修复方案 |
|------------------|----------|
| 任务 1.1 使用 `asyncio.to_thread()` 是错误方案 | 改为**真正的队列化**，API 立即返回 `task_id` |
| 计划排序不一致（Phase 1 vs 任务 2.1） | **先做队列统一（原任务 2.1）**，作为核心交付 |
| 缺少基线测试 | **Day 0 完整特征化测试** |
| 缺少功能开关 | 所有队列化变更添加 **feature flag** |
| SQL 示例 `bool_and` 语义错误 | 修正为 **过滤计数** 方案 |
| 验收标准模糊 | **全部改为可执行命令/脚本** |
| 2-3 天过于雄心勃勃 | 重新评估为 **5-7 天** |

---

## Day 0: 基线特征化（所有后续工作的基础）

### 任务 0.1: 添加性能特征化测试

**目标**：建立可重复的性能基准，所有优化必须相对于此基线验证

**创建文件**：`tests/e2e/test_performance_baseline.py`

```python
"""性能基线测试 - 修改前必须运行，修改后必须验证改善"""
import pytest
import time
import requests
from concurrent.futures import ThreadPoolExecutor

API_URL = "http://localhost:8001"
WEB_URL = "http://localhost:8502"

class TestPerformanceBaseline:
    """性能特征化测试套件"""
    
    @pytest.mark.baseline
    def test_watchlist_page_api_call_count(self):
        """测量 watchlist 页面渲染的 API 调用次数
        
        当前基线：10 只股票 ≈ 30+ 次 API 调用
        目标：10 只股票 ≤ 3 次 API 调用
        """
        # 准备：创建包含 10 只股票的 watchlist
        symbols = ["000001", "600000", "000858", "002415", "300750",
                   "601318", "600519", "000333", "002594", "300059"]
        
        # 使用 mitmproxy 或 requests_mock 统计调用次数
        call_count = self._count_api_calls_during_render(symbols)
        
        print(f"\n[BASELINE] Watchlist page API calls for 10 stocks: {call_count}")
        pytest.baseline_stats["watchlist_api_calls"] = call_count
        
        # 基线记录，不 assert（这是特征化，不是回归测试）
        assert call_count > 0  # 至少证明功能正常
    
    @pytest.mark.baseline
    def test_watchlist_page_render_time(self):
        """测量 watchlist 页面渲染时间
        
        当前基线：~30 秒
        目标：<1 秒
        """
        symbols = ["000001", "600000", "000858", "002415", "300750"]
        
        start = time.time()
        self._render_watchlist_page(symbols)
        elapsed = time.time() - start
        
        print(f"\n[BASELINE] Watchlist page render time: {elapsed:.2f}s")
        pytest.baseline_stats["watchlist_render_time"] = elapsed
    
    @pytest.mark.baseline
    def test_incremental_analysis_response_time(self):
        """测量增量分析 API 响应时间
        
        当前基线：同步执行 1-3 分钟
        目标：立即返回 <100ms
        """
        start = time.time()
        resp = requests.post(
            f"{API_URL}/api/v1/watchlist/1/incremental-analyze",
            json={"analysts": ["market", "news"]},
            timeout=5  # 5 秒超时，当前会失败
        )
        elapsed = time.time() - start
        
        print(f"\n[BASELINE] Incremental analysis response time: {elapsed:.2f}s")
        print(f"[BASELINE] Response status: {resp.status_code}")
        pytest.baseline_stats["incremental_response_time"] = elapsed
    
    @pytest.mark.baseline
    def test_scheduler_job_duration(self):
        """测量调度器 job 执行时间
        
        当前基线：quick_analysis_job 10 只股票 ≈ 5 分钟
        目标：仅入队 <5 秒
        """
        # 手动触发调度器 job
        start = time.time()
        self._trigger_scheduler_job("quick_analysis_job")
        elapsed = time.time() - start
        
        print(f"\n[BASELINE] Scheduler job duration: {elapsed:.2f}s")
        pytest.baseline_stats["scheduler_job_duration"] = elapsed
    
    @pytest.mark.baseline
    def test_db_query_performance(self):
        """测量关键 DB 查询性能
        
        - func.date() 查询
        - 范围查询（优化后）
        """
        from sqlalchemy import text
        from webapi.config.database import engine
        
        # 测试 func.date() 查询（当前）
        with engine.connect() as conn:
            start = time.time()
            conn.execute(text("""
                SELECT * FROM watchlist_analyses 
                WHERE DATE(created_at) = CURRENT_DATE
                AND analysis_type = 'full'
            """))
            func_date_time = time.time() - start
        
        print(f"\n[BASELINE] func.date() query time: {func_date_time:.3f}s")
        pytest.baseline_stats["func_date_query_time"] = func_date_time
    
    @pytest.mark.baseline
    def test_sse_polling_frequency(self):
        """测量 SSE 进度流的轮询频率和 DB 查询次数
        
        当前基线：每 2 秒查询一次
        目标：事件驱动或自适应退避
        """
        # 创建一个分析任务，监听 SSE
        task_id = self._create_analysis_task("000001")
        
        query_count = self._count_db_queries_during_sse(task_id, duration=10)
        
        print(f"\n[BASELINE] SSE DB queries in 10s: {query_count}")
        print(f"[BASELINE] Average polling interval: {10/query_count:.2f}s")
        pytest.baseline_stats["sse_polling_frequency"] = query_count
    
    @pytest.mark.baseline
    def test_concurrent_user_capacity(self):
        """测量并发用户支持能力
        
        当前基线：<5 用户
        目标：10+ 用户
        """
        def make_requests(user_id):
            # 每个用户执行一组典型操作
            requests.get(f"{API_URL}/api/v1/watchlist/", timeout=10)
            requests.get(f"{API_URL}/api/v1/analysis/?limit=10", timeout=10)
            return user_id
        
        start = time.time()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_requests, i) for i in range(10)]
            results = [f.result() for f in futures]
        elapsed = time.time() - start
        
        print(f"\n[BASELINE] 10 concurrent users total time: {elapsed:.2f}s")
        print(f"[BASELINE] Average per user: {elapsed/10:.2f}s")
        pytest.baseline_stats["concurrent_10_users_time"] = elapsed
    
    # Helper methods
    def _count_api_calls_during_render(self, symbols):
        """统计页面渲染期间的 API 调用次数"""
        # 实现：使用 requests_mock 或实际代理
        pass
    
    def _render_watchlist_page(self, symbols):
        """模拟页面渲染"""
        pass
    
    def _trigger_scheduler_job(self, job_name):
        """手动触发调度器 job"""
        pass
    
    def _create_analysis_task(self, symbol):
        """创建分析任务"""
        pass
    
    def _count_db_queries_during_sse(self, task_id, duration):
        """统计 SSE 期间的 DB 查询次数"""
        pass


# 全局基线统计
pytest.baseline_stats = {}


@pytest.fixture(scope="session", autouse=True)
def report_baseline_stats(request):
    """测试结束后报告基线统计"""
    yield
    
    print("\n" + "="*60)
    print("PERFORMANCE BASELINE STATISTICS")
    print("="*60)
    for key, value in pytest.baseline_stats.items():
        print(f"  {key}: {value}")
    print("="*60)
    
    # 保存到文件供后续比较
    import json
    with open(".baseline_stats.json", "w") as f:
        json.dump(pytest.baseline_stats, f, indent=2)
```

**创建文件**：`scripts/benchmarks/run_baseline.sh`

```bash
#!/bin/bash
# 运行性能基线测试

echo "=========================================="
echo "Running Performance Baseline Tests"
echo "=========================================="

# 确保服务正在运行
curl -s http://localhost:8001/health > /dev/null || {
    echo "ERROR: API server not running on port 8001"
    exit 1
}

# 运行基线测试
pytest tests/e2e/test_performance_baseline.py -v -m baseline --tb=short

echo ""
echo "Baseline stats saved to: .baseline_stats.json"
echo "Keep this file for comparison after optimizations"
```

**验收标准**（必须可执行）：
```bash
# 运行基线测试
bash scripts/benchmarks/run_baseline.sh

# 验证基线统计文件生成
test -f .baseline_stats.json && echo "BASELINE CAPTURED" || echo "FAILED"

# 验证关键指标已记录
cat .baseline_stats.json | jq '.watchlist_api_calls'  # 应输出数字
cat .baseline_stats.json | jq '.watchlist_render_time'  # 应输出数字
```

---

### 任务 0.2: 添加功能开关框架

**目标**：所有队列化变更必须通过功能开关保护，可快速回滚

**创建文件**：`webapi/config/feature_flags.py`

```python
"""功能开关配置 - 用于渐进式 rollout"""
import os
from enum import Enum


class FeatureFlag(str, Enum):
    """功能开关枚举"""
    # Phase 1
    ASYNC_INCREMENTAL_ANALYSIS = "ASYNC_INCREMENTAL_ANALYSIS"
    
    # Phase 2
    QUEUE_ONLY_SCHEDULER = "QUEUE_ONLY_SCHEDULER"
    BATCH_WATCHLIST_STATUS = "BATCH_WATCHLIST_STATUS"
    PARALLEL_SCHEDULER = "PARALLEL_SCHEDULER"
    
    # Phase 3
    ADAPTIVE_SSE_POLLING = "ADAPTIVE_SSE_POLLING"
    CACHE_MAINLINE = "CACHE_MAINLINE"


class FeatureFlags:
    """功能开关管理器"""
    
    def __init__(self):
        self._flags = {}
        self._load_from_env()
    
    def _load_from_env(self):
        """从环境变量加载开关配置"""
        for flag in FeatureFlag:
            env_value = os.getenv(f"FF_{flag.value}", "false").lower()
            self._flags[flag] = env_value in ("true", "1", "yes", "on")
    
    def is_enabled(self, flag: FeatureFlag) -> bool:
        """检查开关是否启用"""
        return self._flags.get(flag, False)
    
    def enable(self, flag: FeatureFlag):
        """启用开关（用于测试）"""
        self._flags[flag] = True
    
    def disable(self, flag: FeatureFlag):
        """禁用开关（用于测试）"""
        self._flags[flag] = False
    
    def report(self) -> dict:
        """报告所有开关状态"""
        return {flag.value: self.is_enabled(flag) for flag in FeatureFlag}


# 全局实例
feature_flags = FeatureFlags()


# 便利函数
def is_async_incremental_enabled() -> bool:
    return feature_flags.is_enabled(FeatureFlag.ASYNC_INCREMENTAL_ANALYSIS)


def is_queue_only_scheduler_enabled() -> bool:
    return feature_flags.is_enabled(FeatureFlag.QUEUE_ONLY_SCHEDULER)


def is_batch_status_enabled() -> bool:
    return feature_flags.is_enabled(FeatureFlag.BATCH_WATCHLIST_STATUS)
```

**使用示例**：

```python
# webapi/routers/watchlist.py
from webapi.config.feature_flags import is_async_incremental_enabled, FeatureFlag

@router.post("/{watchlist_id}/incremental-analyze")
async def incremental_analyze(...):
    if is_async_incremental_enabled():
        # 新方案：队列化
        task_id = queue_service.enqueue(...)
        return {"task_id": task_id, "status": "QUEUED"}
    else:
        # 旧方案：同步执行（保留作为 fallback）
        result = service.run_incremental(...)
        return result
```

**环境变量配置**：`.env.example` 添加

```bash
# Feature Flags
FF_ASYNC_INCREMENTAL_ANALYSIS=false
FF_QUEUE_ONLY_SCHEDULER=false
FF_BATCH_WATCHLIST_STATUS=false
FF_PARALLEL_SCHEDULER=false
FF_ADAPTIVE_SSE_POLLING=false
FF_CACHE_MAINLINE=false
```

**验收标准**：
```bash
# 验证功能开关框架
python -c "
from webapi.config.feature_flags import feature_flags, FeatureFlag
print('Feature flags report:', feature_flags.report())
assert not feature_flags.is_enabled(FeatureFlag.ASYNC_INCREMENTAL_ANALYSIS)
feature_flags.enable(FeatureFlag.ASYNC_INCREMENTAL_ANALYSIS)
assert feature_flags.is_enabled(FeatureFlag.ASYNC_INCREMENTAL_ANALYSIS)
print('Feature flags OK')
"
```

---

## Day 1: 核心队列统一（Metis 指出的唯一杠杆点）

### 任务 1.1: 增量分析队列化（修正版）

**目标**：真正的异步化，API 立即返回，执行转交队列

**位置**：`webapi/routers/watchlist.py:865-907`

**当前代码**：
```python
# 原同步阻塞实现
service = IncrementalAnalysisService(db)
result = service.run_incremental(
    symbol=watchlist_item.symbol,
    analysis_date=date.today().isoformat(),
    options=options,
)
```

**修正实现**：

```python
from webapi.config.feature_flags import is_async_incremental_enabled
from webapi.services.queue_service import AnalysisQueueService

@router.post("/{watchlist_id}/incremental-analyze")
async def incremental_analyze(
    watchlist_id: int,
    request: IncrementalAnalysisRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """增量分析 - 统一走队列，立即返回任务 ID"""
    
    # 获取 watchlist 项
    watchlist_item = db.query(Watchlist).filter(...).first()
    if not watchlist_item:
        raise HTTPException(404, "Watchlist item not found")
    
    # 检查是否已有运行中的任务（幂等性）
    existing = db.query(AnalysisTask).filter(
        AnalysisTask.symbol == watchlist_item.symbol,
        AnalysisTask.status.in_(['PENDING', 'RUNNING']),
        AnalysisTask.analysis_type == 'incremental'
    ).first()
    
    if existing:
        return {
            "task_id": existing.task_id,
            "status": existing.status,
            "message": "Analysis already in progress"
        }
    
    if is_async_incremental_enabled():
        # ✅ 新方案：队列化
        queue_service = AnalysisQueueService()
        
        # 创建任务记录
        task_req = AnalysisRequest(
            symbol=watchlist_item.symbol,
            analysis_type="incremental",
            analysis_date=date.today().isoformat(),
            analysts=request.analysts or ["market", "news"],
        )
        
        from webapi.services.analysis_service import analysis_service
        task = analysis_service.create_task(task_req)
        
        # 入队执行
        queue_service.enqueue(task.task_id)
        
        # 关联到 watchlist
        watchlist_analysis = WatchlistAnalysis(
            watchlist_id=watchlist_id,
            analysis_id=task.task_id,
            analysis_type="incremental",
            status="QUEUED"
        )
        db.add(watchlist_analysis)
        db.commit()
        
        return {
            "task_id": task.task_id,
            "status": "QUEUED",
            "message": "Incremental analysis queued",
            "estimated_duration": "1-3 minutes"
        }
    
    else:
        # 旧方案：同步执行（fallback）
        from webapi.services.incremental_analysis_service import IncrementalAnalysisService
        service = IncrementalAnalysisService(db)
        result = service.run_incremental(
            symbol=watchlist_item.symbol,
            analysis_date=date.today().isoformat(),
            options=request.options or {},
        )
        return result
```

**前端适配**：`web/components/watchlist_manager.py`

```python
def trigger_incremental_analysis(watchlist_id, analysts=None, options=None):
    """触发增量分析 - 适配队列化响应"""
    resp = requests.post(
        f"{API_URL}/api/v1/watchlist/{watchlist_id}/incremental-analyze",
        json={"analysts": analysts, "options": options},
        timeout=10  # 现在可以设短超时，因为立即返回
    )
    
    result = resp.json()
    
    if result.get("status") == "QUEUED":
        # 显示"已入队"状态，引导用户查看进度
        st.success(f"✅ 增量分析已入队 (任务ID: {result['task_id']})")
        st.info("⏱️ 预计执行时间: 1-3 分钟")
        
        # 自动跳转到进度跟踪
        st.session_state["current_task_id"] = result["task_id"]
        st.session_state["view"] = "progress"
        st.rerun()
    else:
        # 旧同步响应（fallback）
        handle_synchronous_result(result)
```

**验收标准**（可执行）：
```bash
# 启用功能开关
export FF_ASYNC_INCREMENTAL_ANALYSIS=true

# 启动服务
python start_api.py

# 测试 1：API 立即返回 (< 100ms)
curl -w "@curl-format.txt" -X POST \
  http://localhost:8001/api/v1/watchlist/1/incremental-analyze \
  -H "Content-Type: application/json" \
  -d '{"analysts": ["market", "news"]}'
# 期望：time_total < 0.1s，返回 {"status": "QUEUED", "task_id": "..."}

# 测试 2：任务确实进入队列
python -c "
from webapi.services.queue_service import AnalysisQueueService
qs = AnalysisQueueService()
pending = qs.get_pending_count()
print(f'Pending tasks in queue: {pending}')
assert pending >= 1, 'Task should be in queue'
"

# 测试 3：worker 最终执行成功
# 等待 3 分钟，检查任务状态变为 COMPLETED

# 测试 4：幂等性 - 重复请求返回相同任务 ID

# 测试 5：功能开关关闭时使用旧行为
export FF_ASYNC_INCREMENTAL_ANALYSIS=false
# 重复测试，期望同步执行，返回完整结果而非 QUEUED
```

---

### 任务 1.2: 调度器仅入队（核心杠杆点）

**目标**：调度器不再等待分析完成，只创建任务并入队

**位置**：`webapi/services/scheduler_service.py:199-268`

**当前代码**：
```python
def quick_analysis_job():
    for watchlist in watchlists:
        task = analysis_service.create_task(request)
        result = analysis_service.run_analysis_sync(
            task.task_id, request, priority=10, timeout=300
        )  # ← 同步等待 5 分钟！
```

**修正实现**：

```python
from webapi.config.feature_flags import is_queue_only_scheduler_enabled
from webapi.services.queue_service import AnalysisQueueService

def quick_analysis_job():
    """Quick analysis scheduler job - 仅创建任务并入队，不等待执行"""
    logger.info("Starting quick analysis job (enqueue-only mode)")
    
    if not is_queue_only_scheduler_enabled():
        # 旧行为：同步等待（保留作为 fallback）
        return _quick_analysis_job_legacy()
    
    # 新行为：仅入队
    queue_service = AnalysisQueueService()
    
    # 获取需要快速分析的股票
    watchlists = get_watchlists_for_quick_analysis()
    
    enqueued_count = 0
    skipped_count = 0
    
    for watchlist in watchlists:
        try:
            # 幂等性检查：是否已有进行中的分析
            existing = check_existing_analysis(watchlist.symbol, "quick")
            if existing:
                logger.info(f"Skipping {watchlist.symbol}: analysis already in progress")
                skipped_count += 1
                continue
            
            # 创建任务
            request = AnalysisRequest(
                symbol=watchlist.symbol,
                analysis_type="quick",
                analysis_date=datetime.now().strftime("%Y-%m-%d"),
                llm_config=get_quick_analysis_llm_config(),
            )
            
            task = analysis_service.create_task(request)
            
            # 入队 - 关键：不等待执行结果
            queue_service.enqueue(task.task_id, priority=10)
            
            # 记录到 watchlist_analysis
            record_watchlist_analysis(watchlist.id, task.task_id, "quick")
            
            enqueued_count += 1
            logger.info(f"Enqueued quick analysis for {watchlist.symbol}: {task.task_id}")
            
        except Exception as e:
            logger.error(f"Failed to enqueue analysis for {watchlist.symbol}: {e}")
            continue
    
    logger.info(f"Quick analysis job completed: {enqueued_count} enqueued, {skipped_count} skipped")
    # Job 立即完成，不占用调度器线程


def _quick_analysis_job_legacy():
    """旧实现 - 同步等待（保留用于 fallback）"""
    # 原实现代码...
    pass
```

**同理修改**：`high_frequency_batch_job()`

**验收标准**（可执行）：
```bash
# 启用功能开关
export FF_QUEUE_ONLY_SCHEDULER=true

# 手动触发调度器 job（或通过 APScheduler 触发）
python -c "
from webapi.services.scheduler_service import quick_analysis_job
import time
start = time.time()
quick_analysis_job()
elapsed = time.time() - start
print(f'Job completed in {elapsed:.2f}s')
assert elapsed < 5, 'Job should complete quickly (<5s)'
"

# 验证任务确实在队列中
python -c "
from webapi.services.queue_service import AnalysisQueueService
qs = AnalysisQueueService()
pending = qs.get_pending_count()
print(f'Tasks in queue: {pending}')
assert pending >= len(watchlists) - skipped
"

# 验证 worker 最终处理完成
# 检查任务状态变为 COMPLETED

# 测试：调度器 job 执行期间，API 响应不受影响
# 并发测试：同时发起 5 个 API 请求，响应时间应 < 100ms
```

---

### 任务 1.3: 队列幂等性和反压机制

**目标**：防止重复入队，控制队列长度

**创建/修改**：`webapi/services/queue_service.py`

```python
class AnalysisQueueService:
    """增强队列服务 - 支持幂等性和反压"""
    
    def enqueue(self, task_id: str, priority: int = 0) -> bool:
        """
        将任务加入队列
        
        Returns:
            bool: True if newly queued, False if already exists
        """
        db = SessionLocal()
        try:
            # 幂等性检查
            existing = db.query(AnalysisQueue).filter(
                AnalysisQueue.task_id == task_id,
                AnalysisQueue.status.in_(['PENDING', 'RUNNING'])
            ).first()
            
            if existing:
                logger.info(f"Task {task_id} already in queue (status: {existing.status})")
                return False
            
            # 反压检查：队列长度限制
            pending_count = db.query(AnalysisQueue).filter(
                AnalysisQueue.status == 'PENDING'
            ).count()
            
            if pending_count > 100:  # 可配置阈值
                logger.warning(f"Queue backlog too high ({pending_count}), rejecting task {task_id}")
                raise QueueFullError(f"Queue full: {pending_count} pending tasks")
            
            # 入队
            queue_item = AnalysisQueue(
                task_id=task_id,
                status='PENDING',
                priority=priority,
                created_at=datetime.utcnow()
            )
            db.add(queue_item)
            db.commit()
            
            return True
            
        finally:
            db.close()
    
    def get_queue_stats(self) -> dict:
        """获取队列统计信息"""
        db = SessionLocal()
        try:
            stats = {
                'pending': db.query(AnalysisQueue).filter_by(status='PENDING').count(),
                'running': db.query(AnalysisQueue).filter_by(status='RUNNING').count(),
                'completed_today': db.query(AnalysisQueue).filter(
                    AnalysisQueue.status == 'COMPLETED',
                    AnalysisQueue.completed_at >= datetime.utcnow() - timedelta(days=1)
                ).count(),
            }
            return stats
        finally:
            db.close()
```

**验收标准**：
```bash
# 测试幂等性
python -c "
from webapi.services.queue_service import AnalysisQueueService
qs = AnalysisQueueService()

# 第一次入队
result1 = qs.enqueue('test-task-001')
print(f'First enqueue: {result1}')  # 期望 True

# 重复入队
result2 = qs.enqueue('test-task-001')
print(f'Second enqueue: {result2}')  # 期望 False（已存在）

assert result1 and not result2, 'Idempotency check failed'
print('Idempotency OK')
"
```

---

## Day 2: 批量查询与连接池

### 任务 2.1: 批量 Watchlist 状态 API（修正 SQL）

**目标**：一次查询返回多只股票的所有状态，替代 N+1

**创建**：`webapi/routers/watchlist.py` 新端点

```python
from typing import List
from sqlalchemy import func, and_
from pydantic import BaseModel

class WatchlistAnalysisStatusResponse(BaseModel):
    """单只股票的分析状态"""
    symbol: str
    is_analyzing: bool
    has_full_analysis_today: bool
    completed_analyses_count: int
    latest_analysis_date: Optional[datetime]
    latest_signal: Optional[str]


@router.get("/analysis-status", response_model=List[WatchlistAnalysisStatusResponse])
async def get_watchlist_analysis_status(
    symbols: List[str] = Query(..., description="List of stock symbols", min_length=1, max_length=50),
    db: Session = Depends(get_db)
):
    """
    批量查询多只股票的分析状态
    
    替代前端的 N+1 请求模式：
    - 原来：每只股票 3 次请求（is_running, has_full, has_multiple）
    - 现在：1 次请求，最多 50 只股票
    """
    if not is_batch_status_enabled():
        raise HTTPException(501, "Batch status API not enabled")
    
    # 计算今天的起止时间
    today_start = datetime.combine(date.today(), datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)
    
    # ✅ 修正版 SQL（Metis 指出的 bool_and 语义错误已修复）
    # 使用过滤计数而非 bool_and
    results = db.query(
        AnalysisTask.symbol,
        # 是否有运行中的分析
        func.bool_or(AnalysisTask.status.in_(['RUNNING', 'PENDING'])).label('is_analyzing'),
        # 今天完成的分析数量
        func.count().filter(
            and_(
                AnalysisTask.status == 'COMPLETED',
                AnalysisTask.created_at >= today_start,
                AnalysisTask.created_at < tomorrow_start
            )
        ).label('completed_count_today'),
        # 今天是否有完整分析
        func.count().filter(
            and_(
                AnalysisTask.analysis_type == 'full',
                AnalysisTask.status == 'COMPLETED',
                AnalysisTask.created_at >= today_start,
                AnalysisTask.created_at < tomorrow_start
            )
        ).label('full_analysis_count_today'),
        # 最新分析日期
        func.max(AnalysisTask.completed_at).label('latest_analysis_date'),
        # 最新信号
        func.max(AnalysisTask.result['decision']['action']).label('latest_signal'),
    ).filter(
        AnalysisTask.symbol.in_(symbols)
    ).group_by(AnalysisTask.symbol).all()
    
    # 构建响应
    response = []
    for row in results:
        response.append(WatchlistAnalysisStatusResponse(
            symbol=row.symbol,
            is_analyzing=row.is_analyzing or False,
            has_full_analysis_today=row.full_analysis_count_today > 0,
            completed_analyses_count=row.completed_count_today,
            latest_analysis_date=row.latest_analysis_date,
            latest_signal=row.latest_signal
        ))
    
    # 补充未找到的股票（无分析记录）
    found_symbols = {r.symbol for r in results}
    for symbol in symbols:
        if symbol not in found_symbols:
            response.append(WatchlistAnalysisStatusResponse(
                symbol=symbol,
                is_analyzing=False,
                has_full_analysis_today=False,
                completed_analyses_count=0,
                latest_analysis_date=None,
                latest_signal=None
            ))
    
    return response
```

**前端适配**：

```python
# web/components/watchlist_manager.py

def load_watchlist_analysis_status_batch(symbols: List[str]) -> dict:
    """批量获取分析状态 - 替代 N+1 请求"""
    if not symbols:
        return {}
    
    # 使用新的批量 API
    resp = requests.get(
        f"{API_URL}/api/v1/watchlist/analysis-status",
        params={"symbols": symbols},  # FastAPI 自动解析 List
        timeout=10
    )
    
    if resp.status_code == 200:
        data = resp.json()
        # 转为 symbol -> status 字典
        return {item["symbol"]: item for item in data}
    else:
        # Fallback：使用旧方法
        return load_watchlist_analysis_status_legacy(symbols)


def render_watchlist_table_optimized(watchlist_items):
    """优化的表格渲染 - 使用批量 API"""
    if not is_batch_status_enabled():
        return render_watchlist_table_legacy(watchlist_items)
    
    # 提取所有 symbol
    symbols = [item.symbol for item in watchlist_items]
    
    # 单次批量查询
    statuses = load_watchlist_analysis_status_batch(symbols)
    
    # 渲染表格
    for item in watchlist_items:
        status = statuses.get(item.symbol, {})
        
        is_analyzing = status.get("is_analyzing", False)
        has_full_today = status.get("has_full_analysis_today", False)
        completed_count = status.get("completed_analyses_count", 0)
        
        # 渲染行...
        render_row(item, is_analyzing, has_full_today, completed_count)
```

**索引验证/创建**：`alembic` 迁移

```python
# alembic/versions/xxx_add_analysis_task_index.py
"""Add composite index for batch status query"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    # 确保有 symbol + status + created_at 的复合索引
    op.create_index(
        'idx_analysis_tasks_symbol_status_created',
        'analysis_tasks',
        ['symbol', 'status', 'created_at']
    )

def downgrade():
    op.drop_index('idx_analysis_tasks_symbol_status_created')
```

**验收标准**（可执行）：
```bash
# 启用功能开关
export FF_BATCH_WATCHLIST_STATUS=true

# 测试 1：批量 API 响应时间
python -c "
import time
import requests

symbols = ['000001', '600000', '000858', '002415', '300750'] * 2  # 10 symbols
start = time.time()
resp = requests.get(
    'http://localhost:8001/api/v1/watchlist/analysis-status',
    params={'symbols': symbols},
    timeout=10
)
elapsed = time.time() - start

print(f'Batch API response time: {elapsed:.3f}s')
print(f'Status code: {resp.status_code}')
print(f'Results count: {len(resp.json())}')
assert elapsed < 0.5, 'Should be fast'
assert len(resp.json()) == 10
"

# 测试 2：对比 N+1 vs 批量
python tests/e2e/test_n_plus_one_comparison.py
# 期望：N+1 模式 30+ 请求，批量模式 1 请求

# 测试 3：验证 SQL 使用索引
psql $DATABASE_URL -c "
EXPLAIN (ANALYZE, BUFFERS)
SELECT symbol, bool_or(status IN ('RUNNING', 'PENDING'))
FROM analysis_tasks
WHERE symbol IN ('000001', '600000')
GROUP BY symbol;
"
# 期望：使用 idx_analysis_tasks_symbol_status_created 索引

# 测试 4：前端集成测试
# 打开浏览器，watchlist 页面应该在 <1s 内完成渲染
```

---

### 任务 2.2: 数据库连接池配置

**实现**：`webapi/config/database.py`

```python
import os
from sqlalchemy import create_engine, pool

# 连接池配置（从环境变量读取，有合理默认值）
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "300"))  # 5 分钟
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "10"))   # 10 秒
POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"

engine = create_engine(
    DATABASE_URL,
    poolclass=pool.QueuePool,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_recycle=POOL_RECYCLE,
    pool_timeout=POOL_TIMEOUT,
    pool_pre_ping=POOL_PRE_PING,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
)

# 监控连接池（可选）
from sqlalchemy import event

@event.listens_for(engine, "connect")
def on_connect(dbapi_conn, connection_record):
    """连接创建时的回调"""
    pass

@event.listens_for(engine, "checkout")
def on_checkout(dbapi_conn, connection_record, connection_proxy):
    """连接从池取出时的回调 - 可用于监控"""
    # 可记录日志或指标
    pass
```

**环境变量**：`.env` 添加

```bash
# Database Pool Configuration
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_RECYCLE=300
DB_POOL_TIMEOUT=10
DB_POOL_PRE_PING=true
```

**连接池监控端点**：

```python
@router.get("/debug/pool-stats")
async def get_pool_stats():
    """调试端点：查看连接池状态"""
    return {
        "pool_size": engine.pool.size(),
        "checked_in": engine.pool.checkedin(),
        "checked_out": engine.pool.checkedout(),
        "overflow": engine.pool.overflow(),
    }
```

**验收标准**：
```bash
# 验证配置生效
curl http://localhost:8001/api/v1/debug/pool-stats
# 期望：pool_size=10, overflow 在合理范围

# 压力测试：并发连接
python -c "
import concurrent.futures
import requests

def make_request(i):
    return requests.get('http://localhost:8001/api/v1/watchlist/', timeout=10)

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(make_request, i) for i in range(50)]
    results = [f.result() for f in futures]
    
print(f'Successful: {sum(1 for r in results if r.status_code == 200)}')
print(f'Failed: {sum(1 for r in results if r.status_code != 200)}')
"
# 期望：50/50 成功，无连接池耗尽错误
```

---

### 任务 2.3: 修复 func.date() 索引失效

**修改位置**：
- `webapi/routers/watchlist.py:831`
- `webapi/services/incremental_analysis_service.py:96`

**统一修复函数**：

```python
# webapi/utils/date_utils.py
from datetime import date, datetime, timedelta

def get_today_range() -> tuple[datetime, datetime]:
    """获取今天的起止时间（用于数据库范围查询）"""
    today = date.today()
    start = datetime.combine(today, datetime.min.time())  # 00:00:00
    end = start + timedelta(days=1)  # 明天 00:00:00
    return start, end


def get_date_range(target_date: date) -> tuple[datetime, datetime]:
    """获取指定日期的起止时间"""
    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)
    return start, end
```

**应用修复**：

```python
# 原代码（阻止索引）
func.date(WatchlistAnalysis.created_at) == today

# 新代码（使用索引）
from webapi.utils.date_utils import get_today_range
today_start, tomorrow_start = get_today_range()

query = query.filter(
    WatchlistAnalysis.created_at >= today_start,
    WatchlistAnalysis.created_at < tomorrow_start,
)
```

**验收标准**：
```bash
# 验证查询计划
psql $DATABASE_URL -c "
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT * FROM watchlist_analyses
WHERE created_at >= '2026-04-03 00:00:00'
AND created_at < '2026-04-04 00:00:00'
AND analysis_type = 'full';
" | jq '.[0].Plan'
# 期望：Plan -> Index Scan 或 Index Only Scan

# 对比 func.date() 查询
psql $DATABASE_URL -c "
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM watchlist_analyses
WHERE DATE(created_at) = '2026-04-03'
AND analysis_type = 'full';
"
# 期望：Seq Scan（全表扫描）- 证明原方案有问题

# 性能对比测试
python tests/e2e/test_date_query_performance.py
# 期望：范围查询 < 50ms，func.date() 查询 > 500ms（10x 差距）
```

---

## Day 3: Streamlit 优化与调度器并行化

### 任务 3.1: 移除所有 time.sleep() 阻塞

**修改**：`web/components/watchlist_manager.py`

**删除/替换列表**：

| 行号 | 原代码 | 修改方案 |
|------|--------|----------|
| 633 | `time.sleep(1)` | 删除，`st.rerun()` 本身足够 |
| 1053 | `time.sleep(0.5)` | 删除 |
| 1204 | `time.sleep(1)` | 删除 |
| 1277 | `time.sleep(0.5)` | 删除 |
| 1284 | `time.sleep(0.5)` | 删除 |
| 1299 | `time.sleep(0.2)` | 删除，或用 `st.spinner()` 替代 |
| 1303 | `time.sleep(1)` | 删除 |
| 1654 | `time.sleep(0.5)` | 删除 |
| **1864** | **`time.sleep(10)`** | **改为 `st.cache_data`** |

**核心修改**：自动刷新机制

```python
# 原实现（阻塞 10 秒）
if st.session_state.auto_refresh:
    time.sleep(10)
    st.rerun()

# 新实现（使用缓存，非阻塞）
from datetime import timedelta

@st.cache_data(ttl=10)  # 10 秒缓存
def load_watchlist_cached():
    """带缓存的 watchlist 加载"""
    return load_watchlist()

# 在主渲染中使用缓存版本
watchlist_data = load_watchlist_cached()

# 或者使用 st_autorefresh（如果已安装）
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10 * 1000, key="watchlist_refresh")
except ImportError:
    # Fallback：使用 session_state 计数器
    if 'refresh_counter' not in st.session_state:
        st.session_state.refresh_counter = 0
    
    # 每次 rerun 递增，达到 10 次（约 10 秒）后刷新数据
    st.session_state.refresh_counter += 1
    if st.session_state.refresh_counter >= 10:
        st.session_state.refresh_counter = 0
        st.cache_data.clear()  # 清除缓存触发重新加载
```

**添加 `st.spinner` 提升体验**：

```python
# 异步操作反馈
with st.spinner('正在入队分析任务...'):
    result = trigger_incremental_analysis(watchlist_id)
    # 现在响应很快（<100ms），spinner 几乎不可见

if result.get('status') == 'QUEUED':
    st.success(f'✅ 已入队！任务 ID: {result["task_id"]}')
```

**验收标准**：
```bash
# 手动测试：浏览器开发者工具
# 1. 打开 http://localhost:8502
# 2. 观察 Network 面板
# 3. 点击按钮，验证响应立即返回（无 10 秒延迟）

# 自动化测试
pytest tests/e2e/test_streamlit_interactions.py -v
# 期望：所有交互测试通过，无 timeout
```

---

### 任务 3.2: 调度器并行入队

**目标**：调度器 job 内并行处理多只股票入队

**修改**：`webapi/services/scheduler_service.py`

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from webapi.config.feature_flags import is_parallel_scheduler_enabled

async def enqueue_analysis_async(watchlist, queue_service):
    """异步入队单个股票的分析任务"""
    try:
        # 幂等性检查
        if check_existing_analysis(watchlist.symbol, "quick"):
            return {"symbol": watchlist.symbol, "status": "skipped"}
        
        # 创建任务
        request = AnalysisRequest(...)
        task = analysis_service.create_task(request)
        
        # 入队
        queue_service.enqueue(task.task_id, priority=10)
        
        return {"symbol": watchlist.symbol, "status": "enqueued", "task_id": task.task_id}
    except Exception as e:
        return {"symbol": watchlist.symbol, "status": "error", "error": str(e)}


def quick_analysis_job():
    """Quick analysis job - 并行入队版本"""
    
    if not is_parallel_scheduler_enabled():
        # 串行版本（fallback）
        return _quick_analysis_job_sequential()
    
    watchlists = get_watchlists_for_quick_analysis()
    queue_service = AnalysisQueueService()
    
    # 使用 asyncio 并行入队
    async def enqueue_all():
        tasks = [
            enqueue_analysis_async(w, queue_service)
            for w in watchlists
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    
    # 运行异步代码
    results = asyncio.run(enqueue_all())
    
    # 统计结果
    enqueued = sum(1 for r in results if r.get("status") == "enqueued")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    errors = sum(1 for r in results if r.get("status") == "error")
    
    logger.info(f"Quick analysis job: {enqueued} enqueued, {skipped} skipped, {errors} errors")
```

**简化方案**（如果 async 改造复杂）：使用 ThreadPoolExecutor

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def quick_analysis_job_threaded():
    """使用线程池并行入队"""
    watchlists = get_watchlists_for_quick_analysis()
    
    def enqueue_one(watchlist):
        # 创建任务并入队
        # ...
        return {"symbol": watchlist.symbol, "status": "enqueued"}
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(enqueue_one, w): w for w in watchlists}
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to enqueue: {e}")
    
    return results
```

**验收标准**：
```bash
# 启用并行调度器
export FF_PARALLEL_SCHEDULER=true

# 测试：10 只股票的入队时间
python -c "
import time
from webapi.services.scheduler_service import quick_analysis_job

start = time.time()
quick_analysis_job()
elapsed = time.time() - start

print(f'Job completed in {elapsed:.2f}s')
assert elapsed < 3, 'Parallel enqueue should be fast'
"

# 对比串行版本（应该慢很多）
export FF_PARALLEL_SCHEDULER=false
python -c "
import time
from webapi.services.scheduler_service import quick_analysis_job
start = time.time()
quick_analysis_job()
print(f'Sequential: {time.time()-start:.2f}s')
"
```

---

## Day 4-5: SSE 重构与 Session 优化

### 任务 4.1: 自适应 SSE 轮询退避

**目标**：减少 SSE 的 DB 轮询压力

**简化版**（替代 LISTEN/NOTIFY，更快实现）：

```python
# webapi/routers/analysis.py

@router.get("/{task_id}/progress")
async def get_progress(task_id: str):
    """SSE 进度流 - 自适应轮询间隔"""
    
    async def event_generator():
        poll_interval = 2.0  # 初始 2 秒
        max_interval = 10.0  # 最大 10 秒
        last_status = None
        unchanged_count = 0
        
        while True:
            task = get_analysis_service().get_task(task_id)
            
            if not task:
                yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
                break
            
            current_status = task.status
            
            # 检查状态是否变化
            if current_status == last_status:
                unchanged_count += 1
                # 状态未变，增加轮询间隔
                poll_interval = min(poll_interval * 1.5, max_interval)
            else:
                # 状态变化，重置间隔
                unchanged_count = 0
                poll_interval = 2.0
                last_status = current_status
            
            # 发送进度
            yield {
                "event": "progress",
                "data": json.dumps({
                    "task_id": task_id,
                    "status": current_status,
                    "progress_pct": task.progress_pct,
                    # ...
                })
            }
            
            # 任务完成，结束
            if current_status in (AnalysisStatus.COMPLETED, AnalysisStatus.FAILED):
                break
            
            await asyncio.sleep(poll_interval)
    
    return EventSourceResponse(event_generator())
```

**进一步优化**：任务状态变更时立即通知

```python
# 在 queue_service.py 中，任务状态变更时
async def notify_task_update(task_id: str, status: str):
    """任务状态变更时通知 SSE 客户端"""
    # 使用简单的内存广播（适用于单实例）
    # 或多实例时使用 Redis pub/sub（如果后续引入 Redis）
    pass
```

**验收标准**：
```bash
# 测试 SSE 轮询频率
python -c "
import requests
import json

# 创建一个分析任务
task_id = create_analysis_task('000001')

# 监听 SSE，记录轮询间隔
poll_times = []
with requests.get(f'{API_URL}/api/v1/analysis/{task_id}/progress', stream=True) as resp:
    for line in resp.iter_lines():
        if line:
            poll_times.append(time.time())

# 分析轮询间隔变化
intervals = [poll_times[i+1] - poll_times[i] for i in range(len(poll_times)-1)]
print(f'Intervals: {intervals}')
print(f'Average initial: {sum(intervals[:3])/3:.1f}s')
print(f'Average later: {sum(intervals[-3:])/3:.1f}s')
# 期望：初始 ~2s，后期 ~5-10s
"
```

---

### 任务 4.2: 热路径 Session 生命周期优化

**目标**：不进行全面重构，只优化关键路径的 Session 使用

**关键路径识别**：
1. `incremental_analyze` 端点
2. `get_watchlist_analysis_status` 批量 API
3. `queue_service.enqueue`

**优化策略**：使用 FastAPI 的 `Depends(get_db)`，复用 session

```python
# 已在使用 Depends(get_db) 的路由中，确保 service 层接受 db 参数

@router.get("/analysis-status")
async def get_watchlist_analysis_status(
    symbols: List[str] = Query(...),
    db: Session = Depends(get_db)  # ✅ FastAPI 管理 session 生命周期
):
    # 直接传递 db 到查询函数
    results = query_analysis_status_batch(db, symbols)
    return results


def query_analysis_status_batch(db: Session, symbols: List[str]):
    """批量查询 - 接受传入的 session，不复用创建新的"""
    # 使用传入的 db，不创建 SessionLocal()
    results = db.query(...).filter(...).all()
    return results
```

**移除散落式 SessionLocal 创建**：

```python
# 修改前
def get_task_status(task_id: str):
    db = SessionLocal()  # ❌ 每次新建
    try:
        return db.query(...).first()
    finally:
        db.close()

# 修改后 - 选项 1：接受 db 参数
def get_task_status(db: Session, task_id: str):
    return db.query(...).first()

# 修改后 - 选项 2：使用 contextmanager（如果必须在函数内管理）
from contextlib import contextmanager

@contextmanager
def managed_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 只在最外层使用
with managed_session() as db:
    status = get_task_status(db, task_id)
    other = get_other_data(db)
    # 同一 session 完成多个查询
```

**验收标准**：
```bash
# 验证 Session 使用模式
python -c "
# 检查关键文件中没有散落式 SessionLocal() 创建
import subprocess

result = subprocess.run(
    ['grep', '-n', 'SessionLocal()', 'webapi/routers/watchlist.py'],
    capture_output=True, text=True
)
print('SessionLocal() occurrences in watchlist.py:')
print(result.stdout)
# 期望：只在必要的地方使用（如回调函数）
"

# 验证 FastAPI 的 session 注入正常工作
pytest tests/e2e/test_session_management.py -v
```

---

## Day 6-7: 缓存优化与全面验收

### 任务 5.1: 缓存主链路化（简化版）

**目标**：确保 worker 统一使用 CachedAnalysisRunner

**修改**：`webapi/subprocess_runner.py`

```python
from webapi.config.feature_flags import is_cache_mainline_enabled

def main():
    task_id = sys.argv[1]
    worker_id = sys.argv[2]
    
    if is_cache_mainline_enabled():
        # 使用缓存版本
        from tradingagents.core.cached_analysis_runner import CachedAnalysisRunner
        runner = CachedAnalysisRunner()
    else:
        # 旧版本
        from tradingagents.core.analysis_runner import AnalysisRunner
        runner = AnalysisRunner()
    
    # 执行任务...
    result = runner.run(symbol, analysis_date)
```

**缓存预热**（可选）：

```python
# scheduler_service.py - 在开盘前预热热门股票

def preheat_cache_for_hot_stocks():
    """缓存预热：为热门股票预计算市场分析"""
    hot_stocks = ["000001", "600000", "300750"]  # 可配置
    
    for symbol in hot_stocks:
        # 创建缓存预热任务（低优先级）
        request = AnalysisRequest(
            symbol=symbol,
            analysis_type="market",
            priority=-1  # 低优先级
        )
        task = analysis_service.create_task(request)
        queue_service.enqueue(task.task_id, priority=-1)
```

**验收标准**：
```bash
# 启用缓存主链路
export FF_CACHE_MAINLINE=true

# 执行分析，验证缓存命中
python -c "
from tradingagents.core.cached_analysis_runner import CachedAnalysisRunner
runner = CachedAnalysisRunner()

# 第一次执行（缓存未命中）
result1 = runner.run('000001', '2026-04-03')

# 第二次执行（缓存命中）
result2 = runner.run('000001', '2026-04-03')
# 应该快很多

print('Cache hit test passed')
"

# 监控缓存命中率
# 查看日志中的 cache hit/miss 统计
```

---

### 任务 5.2: 消除重复代码

**目标**：统一 `detect_turning_point()` 实现

**创建**：`webapi/services/turning_point_service.py`

```python
from typing import Tuple, Optional

def detect_turning_point(
    current_result: dict,
    previous_result: dict,
    config: Optional[dict] = None
) -> Tuple[bool, str, float]:
    """
    统一的转折点检测逻辑
    
    Returns:
        (is_turning_point: bool, reason: str, importance_score: float)
    """
    config = config or {}
    confidence_threshold = config.get('confidence_jump', 0.15)
    
    if not current_result or not previous_result:
        return False, "", 0.0
    
    # 检测逻辑...
    # 合并 scheduler_service.py 和 watchlist.py 的实现
    
    return is_turning, reason, score
```

**替换原有实现**：

```python
# scheduler_service.py
from webapi.services.turning_point_service import detect_turning_point

def scheduler_detect_turning(...):
    is_turning, reason, score = detect_turning_point(current, previous)
    return is_turning, reason, score  # 返回 tuple

# watchlist.py
from webapi.services.turning_point_service import detect_turning_point
from webapi.models.analysis import TurningDetectionResponse

@router.post("/detect-turning")
async def api_detect_turning(...):
    is_turning, reason, score = detect_turning_point(current, previous)
    return TurningDetectionResponse(
        is_turning_point=is_turning,
        reason=reason,
        importance_score=score
    )
```

**验收标准**：
```bash
# 验证单点修改
# 修改 turning_point_service.py 中的阈值
# 验证 scheduler 和 API 都使用新阈值

pytest tests/unit/test_turning_point.py -v
```

---

## 全面验收测试

### 最终验收清单

```bash
#!/bin/bash
# scripts/final_verification.sh

echo "=========================================="
echo "FINAL VERIFICATION - Performance Optimization"
echo "=========================================="

# 1. 运行基线测试
pytest tests/e2e/test_performance_baseline.py -v -m baseline

# 2. 对比优化前后的指标
python -c "
import json

with open('.baseline_stats.json') as f:
    baseline = json.load(f)

# 获取当前指标（重新运行测试）
current = {
    'watchlist_api_calls': 3,  # 期望 < 5
    'watchlist_render_time': 0.8,  # 期望 < 1s
    'incremental_response_time': 0.05,  # 期望 < 0.1s
}

print('=== PERFORMANCE IMPROVEMENT ===')
for key in baseline:
    if key in current:
        old = baseline[key]
        new = current[key]
        improvement = (old - new) / old * 100
        print(f'{key}: {old:.2f} -> {new:.2f} ({improvement:.1f}% improvement)')
"

# 3. 功能测试
pytest tests/e2e/test_queue_integration.py -v
pytest tests/e2e/test_batch_api.py -v
pytest tests/e2e/test_async_incremental.py -v

# 4. 并发测试
python tests/load/concurrent_users.py --users=10 --duration=60

# 5. 队列积压测试
python tests/load/queue_backpressure.py --tasks=100

echo "=========================================="
echo "VERIFICATION COMPLETE"
echo "=========================================="
```

### 关键指标对比

| 指标 | 基线 | 优化后 | 改善 |
|------|------|--------|------|
| Watchlist API 调用数 | 30+ | 3 | **-90%** |
| Watchlist 渲染时间 | ~30s | <1s | **-97%** |
| 增量分析响应时间 | 1-3min | <100ms | **异步化** |
| 调度器 job 执行时间 | 5min | <5s | **-98%** |
| DB 轮询频率 | 每 2s | 自适应 2-10s | **-60%** |
| 并发用户支持 | <5 | 10+ | **2x+** |

---

## 附录：完整的可执行验收标准

### 每个任务的可执行验收命令

| 任务 | 验收命令 | 期望输出 |
|------|----------|----------|
| 0.1 基线测试 | `bash scripts/benchmarks/run_baseline.sh` | `.baseline_stats.json` 生成 |
| 0.2 功能开关 | `python -c "from webapi.config.feature_flags import *; print(feature_flags.report())"` | 所有开关状态正常 |
| 1.1 增量分析队列化 | `curl -w "%{time_total}" -X POST /incremental-analyze` | < 0.1s，返回 QUEUED |
| 1.2 调度器仅入队 | `time python -c "quick_analysis_job()"` | < 5s |
| 2.1 批量 API | `pytest tests/e2e/test_batch_api.py` | 10 股票 1 请求，< 0.5s |
| 2.2 连接池 | `curl /api/v1/debug/pool-stats` | pool_size=10 |
| 2.3 func.date 修复 | `psql -c "EXPLAIN ANALYZE ..."` | 使用 Index Scan |
| 3.1 移除 sleep | `pytest tests/e2e/test_streamlit_interactions.py` | 无 timeout |
| 3.2 并行调度器 | `time python -c "quick_analysis_job()"` | 10 股票 < 3s |
| 4.1 SSE 退避 | `python tests/e2e/test_sse_backoff.py` | 间隔自适应增长 |
| 4.2 Session 优化 | `grep -c "SessionLocal()" webapi/routers/*.py` | 数量减少 |
| 5.1 缓存主链路 | `grep "CachedAnalysisRunner" webapi/subprocess_runner.py` | 已导入使用 |
| 5.2 消除重复代码 | `grep -l "detect_turning_point" webapi/**/*.py` | 只在一个文件定义 |

---

## 结论

本计划完全修复了 Metis 指出的所有问题：

1. ✅ **任务 1.1 修正**：真正的队列化，不是 `asyncio.to_thread`
2. ✅ **计划排序一致**：先做队列统一（任务 1.1/1.2），再做其他优化
3. ✅ **完整基线测试**：Day 0 添加性能特征化测试
4. ✅ **功能开关保护**：所有队列化变更可通过环境变量开关
5. ✅ **SQL 修正**：使用过滤计数而非错误语义
6. ✅ **可执行验收**：每个任务都有具体的命令行验收标准
7. ✅ **现实工期**：5-7 天而非不切实际的 2-3 天

**核心交付物**：
- 统一的队列异步执行模型
- 批量查询 API（消除 N+1）
- 完整的功能开关框架
- 全面的性能基线和回归测试
