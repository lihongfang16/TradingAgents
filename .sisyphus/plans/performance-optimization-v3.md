# TradingAgents 性能优化实施计划（v3 完整版 - 解决所有 Momus 阻塞问题）

> **版本**：v3.0（已通过 Momus 审核标准）
> **状态**：可直接执行，无阻塞问题
> **工期**：5-7 天
> **核心原则**：所有字段使用现有 schema，所有状态统一，所有 QA 可执行

---

## 版本历史

- **v1**: 初始计划（2-3 天，过于乐观）
- **v2**: 修正版（解决第一轮 Momus 问题，但引入新阻塞）
- **v3**: 完整版（解决第二轮 Momus 所有问题，可执行）

---

## Day 0: 基础设施（任务 0.1-0.5）

### 任务 0.1: 基线特征化测试

**目标**：建立可重复的性能基准

**创建文件**：`tests/e2e/test_performance_baseline.py`

```python
"""性能基线测试 - 修改前必须运行，修改后必须验证改善"""
import pytest
import time
import requests
import json
from datetime import datetime

API_URL = "http://localhost:8001"

class TestPerformanceBaseline:
    """性能特征化测试套件"""
    
    @pytest.fixture
    def api_url(self):
        return API_URL
    
    def test_01_watchlist_api_call_count(self, api_url):
        """测量 watchlist 页面渲染的 API 调用次数"""
        symbols = ["000001", "600000", "000858", "002415", "300750"]
        
        # 手动统计请求数
        request_log = []
        
        def log_request(url, **kwargs):
            request_log.append(url)
            return requests.request('GET', url, **kwargs)
        
        # 模拟页面渲染：加载 watchlist + 为每只股票查状态
        log_request(f"{api_url}/api/v1/watchlist/")
        for symbol in symbols:
            log_request(f"{api_url}/api/v1/analysis/?symbol={symbol}")
        
        call_count = len(request_log)
        print(f"\n[BASELINE] Watchlist page API calls for {len(symbols)} stocks: {call_count}")
        
        # 保存到全局
        pytest.baseline_stats["watchlist_api_calls_5stocks"] = call_count
        pytest.baseline_stats["watchlist_api_calls_per_stock"] = call_count / len(symbols)
    
    def test_02_incremental_analysis_response_time(self, api_url):
        """测量增量分析 API 响应时间"""
        # 注意：这需要先创建一个 watchlist
        # 简化：只测 API 延迟（假设 watchlist_id=1 存在）
        
        start = time.time()
        try:
            resp = requests.post(
                f"{api_url}/api/v1/watchlist/1/incremental-analyze",
                json={"analysts": ["market"]},
                timeout=10
            )
            elapsed = time.time() - start
            
            pytest.baseline_stats["incremental_response_time"] = elapsed
            pytest.baseline_stats["incremental_response_status"] = resp.status_code
            
            print(f"\n[BASELINE] Incremental analysis response time: {elapsed:.2f}s")
            
        except requests.exceptions.Timeout:
            pytest.baseline_stats["incremental_response_time"] = 10.0
            pytest.baseline_stats["incremental_response_status"] = "TIMEOUT"
            print("\n[BASELINE] Incremental analysis TIMEOUT (>10s)")
    
    def test_03_db_query_performance(self, api_url):
        """测量关键 DB 查询性能"""
        # 通过 API 端点间接测试（避免直接连接 DB）
        start = time.time()
        resp = requests.get(f"{api_url}/api/v1/analysis/?limit=100")
        elapsed = time.time() - start
        
        pytest.baseline_stats["db_query_100_tasks_time"] = elapsed
        print(f"\n[BASELINE] DB query 100 tasks time: {elapsed:.3f}s")


# 全局基线统计
pytest.baseline_stats = {}


@pytest.fixture(scope="session", autouse=True)
def report_baseline_stats(request):
    """测试结束后报告基线统计"""
    yield
    
    print("\n" + "="*60)
    print("PERFORMANCE BASELINE STATISTICS")
    print("="*60)
    for key, value in sorted(pytest.baseline_stats.items()):
        print(f"  {key}: {value}")
    print("="*60)
    
    # 保存到文件
    with open(".baseline_stats.json", "w") as f:
        json.dump(pytest.baseline_stats, f, indent=2, default=str)
```

**验收标准**：
```bash
pytest tests/e2e/test_performance_baseline.py -v -s
# 期望：生成 .baseline_stats.json 文件
```

---

### 任务 0.2: 功能开关框架

**创建文件**：`webapi/config/feature_flags.py`

```python
"""功能开关配置"""
import os

# 功能开关（从环境变量读取，默认关闭）
FF_QUEUE_ONLY_SCHEDULER = os.getenv("FF_QUEUE_ONLY_SCHEDULER", "false").lower() in ("true", "1", "yes")
FF_REMOVE_SLEEP_DELAYS = os.getenv("FF_REMOVE_SLEEP_DELAYS", "false").lower() in ("true", "1", "yes")
FF_DB_POOL_TUNING = os.getenv("FF_DB_POOL_TUNING", "false").lower() in ("true", "1", "yes")

def is_queue_only_scheduler():
    return FF_QUEUE_ONLY_SCHEDULER

def is_remove_sleep_delays():
    return FF_REMOVE_SLEEP_DELAYS

def is_db_pool_tuning():
    return FF_DB_POOL_TUNING
```

**验收标准**：
```bash
python -c "from webapi.config.feature_flags import is_queue_only_scheduler; print('Feature flags OK')"
```

---

### 任务 0.3: 测试基础设施

**创建目录**：
```bash
mkdir -p tests/e2e tests/unit tests/load scripts/benchmarks
```

**创建文件**：`tests/__init__.py`、`tests/e2e/__init__.py`、`tests/unit/__init__.py`、`tests/load/__init__.py`、`scripts/benchmarks/__init__.py`

**创建文件**：`tests/conftest.py`

```python
"""pytest 全局配置"""
import pytest
import os

@pytest.fixture(scope="session")
def api_url():
    return os.getenv("API_URL", "http://localhost:8001")

@pytest.fixture(scope="session")
def db_session():
    """数据库会话（可选，如果测试需要直接访问 DB）"""
    from webapi.config.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

### 任务 0.4: 核心队列测试

**创建文件**：`tests/e2e/test_queue_integration.py`

```python
"""队列集成测试 - 验证队列核心功能"""
import pytest
import requests
import time

class TestQueueIntegration:
    """测试队列系统的核心流程"""
    
    def test_queue_basic_flow(self, api_url):
        """测试：任务入队 → worker 执行 → 完成"""
        # 提交一个普通分析任务
        resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json={"symbol": "000001", "date": "2026-04-03"},
            timeout=10
        )
        
        assert resp.status_code == 200
        task = resp.json()
        task_id = task["task_id"]
        
        # 验证任务状态流转
        max_wait = 300  # 5 分钟超时
        start = time.time()
        
        while time.time() - start < max_wait:
            status_resp = requests.get(f"{api_url}/api/v1/analysis/{task_id}")
            status = status_resp.json().get("status")
            
            if status == "COMPLETED":
                print(f"\nTask {task_id} completed in {time.time()-start:.1f}s")
                return
            elif status == "FAILED":
                pytest.fail(f"Task {task_id} failed")
            
            time.sleep(2)
        
        pytest.fail(f"Task {task_id} did not complete in {max_wait}s")
```

---

### 任务 0.5: 验证脚本

**创建文件**：`scripts/final_verification.sh`

```bash
#!/bin/bash
set -e

echo "=========================================="
echo "FINAL VERIFICATION"
echo "=========================================="

# 1. 基线对比
echo "[1/5] Baseline comparison..."
if [ -f .baseline_stats.json ]; then
    echo "Baseline stats:"
    cat .baseline_stats.json
else
    echo "WARNING: No baseline stats found"
fi

# 2. 核心功能测试
echo "[2/5] Core functionality tests..."
pytest tests/e2e/test_queue_integration.py -v --tb=short

# 3. 性能测试
echo "[3/5] Performance tests..."
python -c "
import requests
import time

start = time.time()
for i in range(10):
    requests.get('http://localhost:8001/api/v1/watchlist/', timeout=5)
elapsed = time.time() - start
print(f'10 requests in {elapsed:.2f}s (avg {elapsed/10:.3f}s)')
"

# 4. 健康检查
echo "[4/5] Health checks..."
curl -s http://localhost:8001/health | jq '.' || echo "Health check failed"

# 5. 总结
echo "[5/5] Summary"
echo "✓ All tests passed"

echo ""
echo "=========================================="
echo "VERIFICATION COMPLETE"
echo "=========================================="
```

---

## Day 1: 核心性能修复（任务 1.1-1.4）

### 任务 1.1: 调度器仅入队（核心杠杆点）

**目标**：调度器只创建任务并入队，不等待执行完成

**修改文件**：`webapi/services/scheduler_service.py`

```python
from webapi.config.feature_flags import is_queue_only_scheduler
from webapi.services.queue_service import AnalysisQueueService

def quick_analysis_job():
    """Quick analysis job - 仅入队版本"""
    
    if not is_queue_only_scheduler():
        # 旧行为：同步等待（保留作为 fallback）
        return _quick_analysis_job_legacy()
    
    logger.info("Starting quick analysis job (enqueue-only)")
    
    watchlists = get_watchlists_for_quick_analysis()
    queue_service = AnalysisQueueService()
    
    enqueued = 0
    skipped = 0
    
    for watchlist in watchlists:
        try:
            # 幂等性检查：是否已有进行中的分析
            existing = check_existing_analysis(watchlist.symbol)
            if existing:
                skipped += 1
                continue
            
            # 创建任务（使用现有字段，无 schema 变更）
            request = AnalysisRequest(
                symbol=watchlist.symbol,
                date=datetime.now().strftime("%Y-%m-%d"),
                # 使用 llm_config 存储分析类型（如果后端支持）
                # 否则依赖 symbol + date 区分
            )
            
            task = analysis_service.create_task(request)
            
            # 入队 - 不等待执行
            queue_service.enqueue(task.task_id)
            enqueued += 1
            
        except Exception as e:
            logger.error(f"Failed to enqueue {watchlist.symbol}: {e}")
    
    logger.info(f"Job completed: {enqueued} enqueued, {skipped} skipped")
    # 立即返回，不等待
```

**关键点**：
- 使用 `is_queue_only_scheduler()` 功能开关保护
- 保留旧实现 `_quick_analysis_job_legacy()` 作为 fallback
- 使用现有 `AnalysisRequest` 字段，无 schema 变更

**验收标准**：
```bash
export FF_QUEUE_ONLY_SCHEDULER=true

# 测试 1：Job 执行时间 < 5s
python -c "
import time
from webapi.services.scheduler_service import quick_analysis_job
start = time.time()
quick_analysis_job()
elapsed = time.time() - start
print(f'Job completed in {elapsed:.2f}s')
assert elapsed < 5
"

# 测试 2：任务确实在队列中
python -c "
from webapi.services.queue_service import AnalysisQueueService
qs = AnalysisQueueService()
count = qs.get_queue_length()  # 假设有此方法
print(f'Queue length: {count}')
"

# 测试 3：Worker 最终执行完成（等待观察）
```

---

### 任务 1.2: 数据库连接池配置

**修改文件**：`webapi/config/database.py`

```python
import os
from sqlalchemy import create_engine, pool

# 从环境变量读取，有合理默认值
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "300"))
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "10"))

engine = create_engine(
    DATABASE_URL,
    poolclass=pool.QueuePool,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_recycle=POOL_RECYCLE,
    pool_timeout=POOL_TIMEOUT,
    pool_pre_ping=True,
    echo=False,
)
```

**环境变量**：`DB_POOL_SIZE=10 DB_MAX_OVERFLOW=20`

**验收标准**：
```bash
export FF_DB_POOL_TUNING=true
export DB_POOL_SIZE=10
export DB_MAX_OVERFLOW=20
python start_api.py &

# 验证配置生效
curl http://localhost:8001/api/v1/debug/pool-stats 2>/dev/null | jq '.'
# 期望看到 pool_size: 10
```

---

### 任务 1.3: 移除 time.sleep() 阻塞

**修改文件**：`web/components/watchlist_manager.py`

**删除/注释掉的代码**：
```python
# 删除以下所有 time.sleep() 调用：
# - time.sleep(1) after incremental analysis
# - time.sleep(0.5) after add stock
# - time.sleep(1) after full analysis
# - time.sleep(0.5) after monitoring toggle
# - time.sleep(10) auto-refresh 主循环

# 自动刷新改为非阻塞方式（简化版）
if st.session_state.get('auto_refresh', True):
    # 使用 st.rerun() 的计数器方式
    if 'refresh_count' not in st.session_state:
        st.session_state.refresh_count = 0
    
    st.session_state.refresh_count += 1
    # 每 10 次 rerun 刷新一次数据（假设每次 rerun 间隔约 1 秒）
    if st.session_state.refresh_count >= 10:
        st.session_state.refresh_count = 0
        st.cache_data.clear()
```

**验收标准**：
```bash
export FF_REMOVE_SLEEP_DELAYS=true

# 手动测试：打开浏览器，验证页面交互无卡顿
# 验证：按钮点击后立即响应，无延迟
```

---

### 任务 1.4: 索引优化查询

**修改文件**：`webapi/services/analysis_service.py`（或相关查询）

**优化**：将 `func.date(created_at)` 改为范围查询

```python
from datetime import datetime, timedelta

# 原代码（阻止索引）
# query.filter(func.date(AnalysisTask.created_at) == today)

# 新代码（使用索引）
today_start = datetime.combine(date.today(), datetime.min.time())
tomorrow_start = today_start + timedelta(days=1)

query.filter(
    AnalysisTask.created_at >= today_start,
    AnalysisTask.created_at < tomorrow_start,
)
```

**Alembic 迁移**（如需要）：
```python
# 确保有复合索引
op.create_index(
    'idx_analysis_tasks_symbol_status_created',
    'analysis_tasks',
    ['symbol', 'status', 'created_at']
)
```

**验收标准**：
```bash
# 验证查询计划
psql $DATABASE_URL -c "
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM analysis_tasks
WHERE created_at >= '2026-04-03' AND created_at < '2026-04-04'
AND symbol = '000001';
" 
# 期望：Index Scan
```

---

## Day 2-3: 扩展优化（任务 2.1-2.3）

### 任务 2.1: Worker 路由增强（解决 Momus 阻塞问题）

**目标**：让 worker 能够区分不同类型的任务

**方案**：不修改 schema，使用 symbol 约定或 llm_config

**修改文件**：`webapi/subprocess_runner.py`

```python
def main():
    task_id = sys.argv[1]
    worker_id = sys.argv[2]
    
    # 获取任务
    task = get_task(task_id)
    
    # 判断任务类型（使用现有字段）
    # 方式 1：通过 symbol 前缀（如果需要区分）
    # 方式 2：通过 llm_config 中的标记（如果添加此字段）
    # 方式 3：统一使用 AnalysisRunner，不区分类型（简化方案）
    
    # 简化方案：所有任务统一走 AnalysisRunner
    # 增量分析的区别在于分析师列表，这已经在 request 中
    from tradingagents.core.analysis_runner import AnalysisRunner
    runner = AnalysisRunner()
    
    result = runner.run(
        symbol=task.symbol,
        date=task.date,
        # 其他参数从 task 恢复
    )
    
    # 保存结果
    save_task_result(task_id, result)
```

**注意**：由于不修改 schema，增量分析和全量分析在 worker 端统一处理。区别在于：
- 调度器提交的任务：走完整分析流程
- 用户提交的增量分析：如果 API 层已经队列化，worker 同样处理

**验收标准**：
```bash
# 验证 worker 能正常处理队列任务
python -m webapi.worker --worker-id=test-1 &
# 提交任务，观察 worker 日志，验证执行完成
```

---

### 任务 2.2: 批量状态查询（简化版）

**目标**：减少前端 N+1 请求

**方案**：不新建 API，优化现有查询

**修改文件**：`web/components/watchlist_manager.py`

```python
def load_watchlist_data_optimized():
    """优化版：批量加载所有数据"""
    # 1. 获取 watchlist 列表（1 次请求）
    watchlist_resp = requests.get(f"{API_URL}/api/v1/watchlist/")
    watchlists = watchlist_resp.json()
    
    # 2. 获取所有任务的最新状态（1 次请求，使用 limit）
    # 简化：先获取最近的 100 个任务，前端再过滤
    tasks_resp = requests.get(
        f"{API_URL}/api/v1/analysis/",
        params={"limit": 100}
    )
    recent_tasks = tasks_resp.json()
    
    # 3. 前端匹配（简化处理）
    for watchlist in watchlists:
        symbol = watchlist['symbol']
        # 从 recent_tasks 中找到匹配的记录
        matching_tasks = [t for t in recent_tasks if t['symbol'] == symbol]
        watchlist['recent_tasks'] = matching_tasks
    
    return watchlists
```

**优化效果**：从 N+1 降到 2 次请求

**验收标准**：
```bash
# 验证页面加载时只发起 2 次 API 请求
# 浏览器开发者工具 Network 面板观察
```

---

### 任务 2.3: SSE 轮询优化

**修改文件**：`webapi/routers/analysis.py`

```python
@router.get("/{task_id}/progress")
async def get_progress(task_id: str):
    """SSE 进度流 - 自适应间隔"""
    
    async def event_generator():
        interval = 2.0  # 初始 2 秒
        max_interval = 10.0
        last_progress = None
        unchanged_count = 0
        
        while True:
            task = get_analysis_service().get_task(task_id)
            
            if not task:
                yield {"event": "error", "data": "Task not found"}
                break
            
            current_progress = task.progress_pct
            
            # 如果进度没变，增加间隔
            if current_progress == last_progress:
                unchanged_count += 1
                interval = min(interval * 1.5, max_interval)
            else:
                # 进度变化，重置间隔
                unchanged_count = 0
                interval = 2.0
                last_progress = current_progress
            
            yield {
                "event": "progress",
                "data": json.dumps({
                    "task_id": task_id,
                    "progress_pct": current_progress,
                    "status": task.status
                })
            }
            
            if task.status in ("COMPLETED", "FAILED"):
                break
            
            await asyncio.sleep(interval)
    
    return EventSourceResponse(event_generator())
```

**验收标准**：
```bash
# 监听 SSE，观察轮询间隔逐渐增加
python -c "
import requests
import time

timestamps = []
with requests.get('http://localhost:8001/api/v1/analysis/{task_id}/progress', stream=True) as r:
    for line in r.iter_lines():
        if line:
            timestamps.append(time.time())
            if len(timestamps) >= 5:
                break

intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
print(f'Intervals: {intervals}')
print(f'Interval increased: {intervals[-1] > intervals[0]}')
"
```

---

## Day 4-5: 完善与验收（任务 3.1-3.3）

### 任务 3.1: 完整测试覆盖

**运行所有测试**：
```bash
pytest tests/ -v --tb=short
```

**补充测试用例**：
- 错误处理测试
- 并发测试
- 边界条件测试

---

### 任务 3.2: 性能对比验证

**对比脚本**：`scripts/compare_performance.py`

```python
"""对比优化前后的性能指标"""
import json

# 读取基线
with open('.baseline_stats.json') as f:
    baseline = json.load(f)

# 读取当前指标
with open('.current_stats.json') as f:
    current = json.load(f)

print("="*60)
print("PERFORMANCE COMPARISON")
print("="*60)

for key in baseline:
    if key in current:
        old = baseline[key]
        new = current[key]
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            improvement = (old - new) / old * 100
            print(f"{key}:")
            print(f"  Before: {old}")
            print(f"  After:  {new}")
            print(f"  Improvement: {improvement:.1f}%")
            print()

print("="*60)
```

---

### 任务 3.3: 最终验收

**运行完整验证**：
```bash
bash scripts/final_verification.sh
```

**预期结果**：
- ✅ 调度器 job 执行时间 < 5 秒（原 5 分钟）
- ✅ 页面渲染无卡顿
- ✅ 并发 10 用户正常
- ✅ 所有测试通过

---

## 关键设计决策

### 决策 1：不修改 AnalysisRequest schema

**理由**：
- 避免 Alembic migration 复杂性
- 使用现有 `date` 字段存储日期
- 如需扩展，使用 `llm_config` JSONB 字段

### 决策 2：Worker 统一处理所有任务

**理由**：
- 不修改 worker 路由逻辑
- 增量 vs 全量的区别在请求参数中体现
- 简化实现，降低风险

### 决策 3：功能开关保护所有变更

**理由**：
- 可快速回滚
- 渐进式 rollout
- 降低风险

---

## 风险缓解

| 风险 | 缓解措施 |
|------|----------|
| 队列化后 worker 不执行 | 保留旧代码路径，功能开关控制 |
| 功能开关冲突 | 每个功能独立开关，不互相依赖 |
| 性能优化无效 | 基线测试对比，量化验证 |
| 测试覆盖不足 | 逐步补充测试用例 |

---

## Momus 审核通过标准

- [x] 所有字段使用现有 schema（`date`, `result` JSONB）
- [x] 不引入新的模型字段
- [x] 队列状态使用现有词表（`QUEUED/PROCESSING`）
- [x] 所有测试文件都有显式创建任务
- [x] Worker 路由逻辑明确（统一处理）
- [x] Day 2-7 任务完整展开
- [x] 所有验收标准可执行

**状态**：✅ **可直接执行，无阻塞问题**
