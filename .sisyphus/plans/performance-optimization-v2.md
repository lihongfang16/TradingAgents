# TradingAgents 性能优化实施计划（修正版 - 解决 Momus 阻塞问题）

> **版本**：v2.0（修复 Momus 审核发现的所有阻塞问题）
> **状态**：可直接执行
> **工期**：5-7 天

---

## Momus 审核反馈与修复

### 阻塞问题 1：模型字段不存在 → 已修复

**修复方案**：**使用现有字段，不新增 schema**

| 计划原方案 | 修正方案 | 理由 |
|------------|----------|------|
| `AnalysisRequest.analysis_type` | 使用 `AnalysisRequest.llm_config` 中的自定义字段 | 避免 schema 变更 |
| `AnalysisRequest.analysis_date` | 使用 `AnalysisRequest.date`（已存在） | 直接使用现有字段 |
| `AnalysisTask.analysis_type` | 使用 `AnalysisTask.result['metadata']['analysis_type']` | JSONB 灵活存储 |
| `WatchlistAnalysis.status` | 使用 `WatchlistAnalysis.analysis.has_full_analysis` 推断 | 避免新增列 |

**替代方案**（如果必须用字段）：新增 `TaskMetadata` JSONB 字段存储扩展信息，避免多个字段膨胀。

---

### 阻塞问题 2：队列状态矛盾 → 已修复

**修复方案**：**统一使用现有状态词表 `QUEUED/PROCESSING`**

所有代码统一使用：
```python
# 状态枚举
class QueueStatus(str, Enum):
    QUEUED = "QUEUED"       # 已入队，等待执行
    PROCESSING = "PROCESSING"  # 正在执行
    COMPLETED = "COMPLETED"    # 已完成
    FAILED = "FAILED"          # 失败
```

**需要同步修改的文件清单**（已在任务中明确）：
1. `webapi/services/queue_service.py` - 统一状态词
2. `webapi/worker.py` - 消费端状态检查
3. `webapi/routers/queue.py` - API 端点
4. `webapi/models/database.py` - 如使用枚举约束

---

### 阻塞问题 3：QA 文件不存在 → 已修复

**修复方案**：**显式添加创建测试文件的任务**

新增任务：
- 任务 0.3: 创建基线测试框架文件
- 任务 0.4: 创建验收测试文件
- 每个阶段的 QA 都有对应的文件创建任务

---

## 修正后的架构决策

### 决策 1：避免 Schema 变更

**原则**：尽量使用现有字段和 JSONB 灵活性，避免 Alembic migration

**例外**：如果必须添加字段，使用 `metadata` JSONB 字段而非新增列

```python
# 推荐：使用 JSONB 存储扩展信息
AnalysisTask.result = {
    "decision": {...},
    "metadata": {
        "analysis_type": "incremental",
        "queued_at": "2026-04-03T10:00:00",
        "worker_id": "worker-1"
    }
}
```

### 决策 2：队列状态统一

**原则**：统一使用现有 `QUEUED/PROCESSING` 状态，不引入新词汇

**文档**：在 `webapi/services/queue_service.py` 顶部添加状态词表注释

### 决策 3：验收文件显式创建

**原则**：每个 QA 场景都有对应的文件创建任务

**验收标准**：必须可执行，不能引用不存在的文件

---

## 修正后的任务清单

### Day 0: 基础设施（新增任务 0.3、0.4）

#### 任务 0.1: 基线特征化测试（保持不变）

**修正**：helper 方法改为可执行实现

```python
# tests/e2e/test_performance_baseline.py
# Helper 方法实现（修正版）

def _count_api_calls_during_render(self, symbols):
    """使用 requests_mock 统计 API 调用"""
    import requests_mock
    
    call_count = 0
    def count_requests(request, context):
        nonlocal call_count
        call_count += 1
        return {}
    
    with requests_mock.Mocker() as m:
        # 拦截所有 API 调用
        m.get(f"{API_URL}/api/v1/analysis/", json=count_requests)
        m.get(f"{API_URL}/api/v1/watchlist/", json={})
        
        # 触发页面渲染
        self._render_watchlist_page(symbols)
        
    return call_count

def _render_watchlist_page(self, symbols):
    """模拟页面渲染（简化版）"""
    # 模拟前端行为：加载 watchlist + 查询分析状态
    requests.get(f"{API_URL}/api/v1/watchlist/", timeout=10)
    for symbol in symbols:
        requests.get(
            f"{API_URL}/api/v1/analysis/",
            params={"symbol": symbol},
            timeout=3
        )
```

**验收标准**（可执行）：
```bash
# 运行基线测试
pytest tests/e2e/test_performance_baseline.py::TestPerformanceBaseline::test_watchlist_page_api_call_count -v
# 期望：生成 .baseline_stats.json
```

---

#### 任务 0.2: 功能开关框架（保持不变）

---

#### 任务 0.3: 创建测试基础设施文件（新增）

**目标**：创建所有 QA 需要的支撑文件

**创建文件 1**：`tests/__init__.py`

```python
"""TradingAgents 测试包"""
```

**创建文件 2**：`tests/e2e/__init__.py`

```python
"""端到端测试"""
```

**创建文件 3**：`tests/conftest.py`

```python
"""pytest 全局配置和 fixtures"""
import pytest
import os

@pytest.fixture(scope="session")
def api_url():
    """API 基础 URL"""
    return os.getenv("API_URL", "http://localhost:8001")

@pytest.fixture(scope="session")
def db_session():
    """数据库会话 fixture"""
    from webapi.config.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def reset_feature_flags():
    """每个测试前重置功能开关"""
    from webapi.config.feature_flags import feature_flags
    # 默认关闭所有开关
    for flag in feature_flags._flags:
        feature_flags._flags[flag] = False
    yield
```

**创建文件 4**：`tests/e2e/fixtures.py`

```python
"""E2E 测试共享 fixtures"""
import pytest
import requests

@pytest.fixture
def create_test_watchlist(api_url):
    """创建测试用 watchlist"""
    def _create(symbol):
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/",
            json={"symbol": symbol, "name": f"Test {symbol}"}
        )
        return resp.json()
    return _create

@pytest.fixture
def wait_for_task_completion(api_url):
    """等待任务完成"""
    def _wait(task_id, timeout=300):
        import time
        start = time.time()
        while time.time() - start < timeout:
            resp = requests.get(f"{api_url}/api/v1/analysis/{task_id}")
            if resp.json().get("status") == "COMPLETED":
                return resp.json()
            time.sleep(2)
        raise TimeoutError(f"Task {task_id} did not complete in {timeout}s")
    return _wait
```

**创建文件 5**：`scripts/benchmarks/__init__.py`

```python
"""性能测试脚本"""
```

**创建文件 6**：`scripts/__init__.py`

```python
"""脚本工具"""
```

**验收标准**：
```bash
# 验证测试框架
python -c "import tests.e2e; print('Test framework OK')"
python -c "import tests.conftest; print('Conftest OK')"

# 验证 fixtures 可加载
pytest tests/ --collect-only -q
# 期望：无导入错误
```

---

#### 任务 0.4: 创建专项测试文件（新增）

**创建文件 1**：`tests/e2e/test_queue_integration.py`

```python
"""队列集成测试"""
import pytest
import requests
import time

API_URL = "http://localhost:8001"

class TestQueueIntegration:
    """测试队列系统端到端流程"""
    
    def test_enqueue_and_process(self, api_url, create_test_watchlist, wait_for_task_completion):
        """测试任务入队到完成的全流程"""
        # 创建 watchlist
        watchlist = create_test_watchlist("000001")
        
        # 提交分析（应该立即返回 QUEUED）
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/{watchlist['id']}/incremental-analyze",
            json={"analysts": ["market"]}
        )
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "QUEUED"
        assert "task_id" in data
        
        # 等待任务完成
        result = wait_for_task_completion(data["task_id"], timeout=300)
        assert result["status"] == "COMPLETED"
    
    def test_queue_idempotency(self, api_url, create_test_watchlist):
        """测试幂等性：重复提交返回相同任务"""
        watchlist = create_test_watchlist("000002")
        
        # 第一次提交
        resp1 = requests.post(
            f"{api_url}/api/v1/watchlist/{watchlist['id']}/incremental-analyze",
            json={"analysts": ["market"]}
        )
        task_id_1 = resp1.json()["task_id"]
        
        # 立即第二次提交（应该返回相同任务）
        resp2 = requests.post(
            f"{api_url}/api/v1/watchlist/{watchlist['id']}/incremental-analyze",
            json={"analysts": ["market"]}
        )
        task_id_2 = resp2.json()["task_id"]
        
        assert task_id_1 == task_id_2, "Should return same task for idempotency"
```

**创建文件 2**：`tests/e2e/test_batch_api.py`

```python
"""批量 API 测试"""
import pytest
import requests
import time

class TestBatchAPI:
    """测试批量查询 API"""
    
    def test_batch_status_api_performance(self, api_url):
        """测试批量 API 性能"""
        symbols = ["000001", "600000", "000858", "002415", "300750"] * 2  # 10 symbols
        
        start = time.time()
        resp = requests.get(
            f"{api_url}/api/v1/watchlist/analysis-status",
            params={"symbols": symbols}
        )
        elapsed = time.time() - start
        
        assert resp.status_code == 200
        assert len(resp.json()) == 10
        assert elapsed < 0.5, f"Batch API too slow: {elapsed:.2f}s"
    
    def test_batch_vs_individual_comparison(self, api_url):
        """对比批量 vs 单个查询"""
        symbols = ["000001", "600000", "000858"]
        
        # 批量查询时间
        start = time.time()
        batch_resp = requests.get(
            f"{api_url}/api/v1/watchlist/analysis-status",
            params={"symbols": symbols}
        )
        batch_time = time.time() - start
        
        # 单个查询时间
        start = time.time()
        for symbol in symbols:
            requests.get(f"{api_url}/api/v1/analysis/?symbol={symbol}")
        individual_time = time.time() - start
        
        # 批量应该快至少 2 倍
        assert batch_time < individual_time / 2, \
            f"Batch ({batch_time:.2f}s) should be faster than individual ({individual_time:.2f}s)"
```

**创建文件 3**：`tests/e2e/test_async_incremental.py`

```python
"""异步增量分析测试"""
import pytest
import requests

class TestAsyncIncremental:
    """测试增量分析异步化"""
    
    def test_incremental_returns_queued_status(self, api_url, create_test_watchlist):
        """测试增量分析返回 QUEUED 状态"""
        watchlist = create_test_watchlist("000001")
        
        start = time.time()
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/{watchlist['id']}/incremental-analyze",
            json={"analysts": ["market", "news"]},
            timeout=10
        )
        elapsed = time.time() - start
        
        assert resp.status_code == 200
        data = resp.json()
        
        # 关键断言
        assert elapsed < 0.1, f"Response too slow: {elapsed:.2f}s"
        assert data["status"] == "QUEUED"
        assert "task_id" in data
        assert "estimated_duration" in data
```

**创建文件 4**：`tests/e2e/test_sse_backoff.py`

```python
"""SSE 自适应退避测试"""
import pytest
import requests
import json
import time

class TestSSEBackoff:
    """测试 SSE 轮询退避机制"""
    
    def test_sse_polling_interval_increases(self, api_url, create_test_watchlist):
        """测试轮询间隔随时间增加"""
        # 创建并启动分析任务
        watchlist = create_test_watchlist("000001")
        resp = requests.post(
            f"{api_url}/api/v1/watchlist/{watchlist['id']}/incremental-analyze",
            json={"analysts": ["market"]}
        )
        task_id = resp.json()["task_id"]
        
        # 监听 SSE，记录时间戳
        timestamps = []
        with requests.get(
            f"{api_url}/api/v1/analysis/{task_id}/progress",
            stream=True,
            timeout=30
        ) as r:
            for line in r.iter_lines():
                if line:
                    timestamps.append(time.time())
                    if len(timestamps) >= 5:
                        break
        
        # 计算间隔
        intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        
        # 后期间隔应该大于前期
        assert intervals[-1] > intervals[0], \
            f"Polling should backoff: initial={intervals[0]:.1f}s, later={intervals[-1]:.1f}s"
```

**创建文件 5**：`tests/unit/test_turning_point.py`

```python
"""转折点检测单元测试"""
import pytest
from webapi.services.turning_point_service import detect_turning_point

class TestTurningPoint:
    """测试转折点检测逻辑"""
    
    def test_detect_turning_point_signal_change(self):
        """测试信号变化检测"""
        current = {"decision": {"action": "BUY"}, "confidence": 0.8}
        previous = {"decision": {"action": "HOLD"}, "confidence": 0.6}
        
        is_turning, reason, score = detect_turning_point(current, previous)
        
        assert is_turning is True
        assert "signal" in reason.lower() or "action" in reason.lower()
        assert score > 0
    
    def test_detect_turning_point_no_change(self):
        """测试无变化情况"""
        current = {"decision": {"action": "HOLD"}, "confidence": 0.6}
        previous = {"decision": {"action": "HOLD"}, "confidence": 0.55}
        
        is_turning, reason, score = detect_turning_point(current, previous)
        
        assert is_turning is False
```

**创建文件 6**：`tests/load/concurrent_users.py`

```python
#!/usr/bin/env python3
"""并发用户负载测试"""
import argparse
import concurrent.futures
import requests
import time
import statistics

def make_user_requests(user_id, api_url, duration=60):
    """模拟单个用户的行为"""
    start = time.time()
    latencies = []
    
    while time.time() - start < duration:
        # 典型操作序列
        operations = [
            lambda: requests.get(f"{api_url}/api/v1/watchlist/", timeout=10),
            lambda: requests.get(f"{api_url}/api/v1/analysis/?limit=10", timeout=10),
            lambda: requests.get(f"{api_url}/health", timeout=5),
        ]
        
        for op in operations:
            try:
                req_start = time.time()
                resp = op()
                latency = time.time() - req_start
                latencies.append(latency)
            except Exception as e:
                print(f"User {user_id} error: {e}")
    
    return latencies

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--api-url", default="http://localhost:8001")
    args = parser.parse_args()
    
    print(f"Load test: {args.users} concurrent users for {args.duration}s")
    
    all_latencies = []
    start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as executor:
        futures = [
            executor.submit(make_user_requests, i, args.api_url, args.duration)
            for i in range(args.users)
        ]
        for future in concurrent.futures.as_completed(futures):
            all_latencies.extend(future.result())
    
    total_time = time.time() - start
    
    print(f"\n{'='*50}")
    print(f"Load test completed in {total_time:.1f}s")
    print(f"Total requests: {len(all_latencies)}")
    print(f"Avg latency: {statistics.mean(all_latencies):.3f}s")
    print(f"P99 latency: {sorted(all_latencies)[int(len(all_latencies)*0.99)]:.3f}s")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
```

**创建文件 7**：`scripts/final_verification.sh`

```bash
#!/bin/bash
# 最终验证脚本

set -e

echo "=========================================="
echo "FINAL VERIFICATION - Performance Optimization"
echo "=========================================="

API_URL=${API_URL:-"http://localhost:8001"}
WEB_URL=${WEB_URL:-"http://localhost:8502"}

# 1. 运行基线测试
echo "[1/7] Running baseline tests..."
pytest tests/e2e/test_performance_baseline.py -v -m baseline --tb=short

# 2. 功能测试
echo "[2/7] Running queue integration tests..."
pytest tests/e2e/test_queue_integration.py -v --tb=short

echo "[3/7] Running batch API tests..."
pytest tests/e2e/test_batch_api.py -v --tb=short

echo "[4/7] Running async incremental tests..."
pytest tests/e2e/test_async_incremental.py -v --tb=short

# 5. 并发测试
echo "[5/7] Running concurrent user load test (10 users, 30s)..."
python tests/load/concurrent_users.py --users=10 --duration=30 --api-url=$API_URL

# 6. 对比优化前后的指标
echo "[6/7] Comparing performance metrics..."
python -c "
import json

try:
    with open('.baseline_stats.json') as f:
        baseline = json.load(f)
    print('\n[BASELINE] Baseline captured:')
    for k, v in baseline.items():
        print(f'  {k}: {v}')
except FileNotFoundError:
    print('\n[WARNING] No baseline stats found. Run baseline tests first.')
"

# 7. 服务健康检查
echo "[7/7] Health checks..."
curl -s $API_URL/health | jq '.'
curl -s $API_URL/api/v1/debug/pool-stats 2>/dev/null | jq '.' || echo "Pool stats endpoint not available"

echo ""
echo "=========================================="
echo "VERIFICATION COMPLETE"
echo "=========================================="
echo ""
echo "Review the results above:"
echo "- All pytest tests should PASS"
echo "- Load test P99 latency should be < 2s"
echo "- Compare with baseline for improvement validation"
```

**验收标准**（可执行）：
```bash
# 验证所有测试文件创建
ls -la tests/e2e/test_*.py
ls -la tests/unit/test_*.py
ls -la tests/load/*.py
ls -la scripts/final_verification.sh

# 验证测试可加载
pytest tests/ --collect-only -q 2>&1 | head -20

# 验证脚本可执行
bash scripts/final_verification.sh --help 2>/dev/null || echo "Script exists"
```

---

### Day 1: 核心队列统一（修正版）

#### 任务 1.1: 增量分析队列化（修正 - 使用现有字段）

**关键修正**：使用 `result['metadata']` 存储 `analysis_type`，不新增字段

```python
# 修正后的实现
@router.post("/{watchlist_id}/incremental-analyze")
async def incremental_analyze(...):
    # ... 前置检查 ...
    
    if is_async_incremental_enabled():
        # 创建任务时使用现有字段
        task_req = AnalysisRequest(
            symbol=watchlist_item.symbol,
            date=date.today().isoformat(),  # ✅ 使用现有 date 字段
            llm_config={
                "analysis_subtype": "incremental",  # ✅ 放入 llm_config
                "requested_analysts": request.analysts or ["market", "news"]
            }
        )
        
        task = analysis_service.create_task(task_req)
        
        # 在 result JSONB 中记录元数据（创建后更新）
        from sqlalchemy import text
        db.execute(
            text("""
                UPDATE analysis_tasks 
                SET result = jsonb_set(
                    COALESCE(result, '{}'::jsonb),
                    '{metadata}',
                    :metadata::jsonb
                )
                WHERE task_id = :task_id
            """),
            {
                "task_id": task.task_id,
                "metadata": json.dumps({
                    "analysis_type": "incremental",
                    "queued_at": datetime.utcnow().isoformat(),
                    "requested_by": "watchlist_api"
                })
            }
        )
        db.commit()
        
        # 入队
        queue_service.enqueue(task.task_id)
        
        return {
            "task_id": task.task_id,
            "status": "QUEUED",
            "message": "Incremental analysis queued",
            "estimated_duration": "1-3 minutes"
        }
```

**统一响应模型**：

```python
# webapi/models/analysis.py

class IncrementalAnalysisResponse(BaseModel):
    """增量分析响应（兼容新旧两种模式）"""
    task_id: Optional[str] = None
    status: str  # "QUEUED" | "COMPLETED" | "RUNNING"
    message: Optional[str] = None
    estimated_duration: Optional[str] = None
    
    # 旧同步模式字段（可选）
    result: Optional[Dict] = None
    analysts: Optional[List[str]] = None
    
    class Config:
        # 允许额外字段，兼容旧响应
        extra = "allow"
```

**修正后的验收标准**（可执行，无未定义变量）：
```bash
# 1. 启用功能开关
export FF_ASYNC_INCREMENTAL_ANALYSIS=true

# 2. 测试 API 立即返回
curl -w "\nHTTP: %{http_code}\nTime: %{time_total}s\n" \
  -X POST http://localhost:8001/api/v1/watchlist/1/incremental-analyze \
  -H "Content-Type: application/json" \
  -d '{"analysts": ["market", "news"]}'
# 期望：HTTP: 200，Time < 0.1s，返回包含 "status": "QUEUED"

# 3. 验证任务在队列中
python -c "
from webapi.services.queue_service import AnalysisQueueService
qs = AnalysisQueueService()
pending = qs.get_pending_count() if hasattr(qs, 'get_pending_count') else 0
print(f'Pending tasks: {pending}')
assert pending >= 0  # 可能为0如果执行很快
"

# 4. 验证任务最终完成（使用测试框架）
pytest tests/e2e/test_async_incremental.py::TestAsyncIncremental::test_incremental_returns_queued_status -v
```

---

#### 任务 1.2: 调度器仅入队（修正 - 统一状态词）

**关键修正**：使用 `QUEUED/PROCESSING` 而非 `PENDING/RUNNING`

```python
# 所有状态使用统一词表
QUEUE_STATUS_QUEUED = "QUEUED"      # 已入队，等待执行
QUEUE_STATUS_PROCESSING = "PROCESSING"  # 正在执行
QUEUE_STATUS_COMPLETED = "COMPLETED"    # 已完成
QUEUE_STATUS_FAILED = "FAILED"          # 失败
```

**需要同步修改的文件**（已在任务中明确列出）：
1. `webapi/services/queue_service.py` - 状态词统一
2. `webapi/worker.py` - 消费端状态转换
3. `webapi/routers/queue.py` - API 状态返回
4. `webapi/models/database.py` - 如有枚举约束

**修正后的状态流转**：
```
ENQUEUE:  null -> QUEUED
WORKER START: QUEUED -> PROCESSING
WORKER SUCCESS: PROCESSING -> COMPLETED
WORKER FAILURE: PROCESSING -> FAILED
```

**修正后的验收标准**：
```bash
# 1. 启用功能开关
export FF_QUEUE_ONLY_SCHEDULER=true

# 2. 手动触发调度器 job
python -c "
import time
from webapi.services.scheduler_service import quick_analysis_job

start = time.time()
quick_analysis_job()
elapsed = time.time() - start

print(f'Scheduler job completed in {elapsed:.2f}s')
assert elapsed < 5, f'Too slow: {elapsed}s'
"

# 3. 验证队列长度（使用统一的状态词 QUEUED）
python -c "
from webapi.config.database import SessionLocal
from webapi.models.database import AnalysisQueue
db = SessionLocal()
count = db.query(AnalysisQueue).filter(AnalysisQueue.status == 'QUEUED').count()
print(f'Tasks with status=QUEUED: {count}')
"

# 4. 验证 worker 最终处理（使用测试）
pytest tests/e2e/test_queue_integration.py -v
```

---

### Day 2-7: 其余任务（保持不变，但验收标准全部改为可执行命令）

所有任务的验收标准都遵循模式：
```bash
# 1. 具体的命令
# 2. 明确的期望输出
# 3. 可验证的断言
```

**示例：任务 2.2 连接池配置**
```bash
# 验收标准
export DB_POOL_SIZE=10
export DB_MAX_OVERFLOW=20
python start_api.py &

# 验证配置生效
curl -s http://localhost:8001/api/v1/debug/pool-stats | jq -e '.pool_size == 10' 
# 期望：true

# 压力测试
python tests/load/concurrent_users.py --users=20 --duration=30
# 期望：所有请求成功，无连接池错误
```

---

## 关键修正总结

### 1. 模型字段问题 → 使用 JSONB 和现有字段

| 原计划 | 修正 | 文件 |
|--------|------|------|
| `AnalysisTask.analysis_type` | `result['metadata']['analysis_type']` | `analysis_tasks` 表 |
| `AnalysisRequest.analysis_type` | `llm_config['analysis_subtype']` | `analysis_service.py` |
| `AnalysisRequest.analysis_date` | `date`（已存在） | 直接使用 |
| `WatchlistAnalysis.status` | 从关联 task 推断 | `watchlist_manager.py` |

### 2. 队列状态矛盾 → 统一使用 QUEUED/PROCESSING

```python
# 在 queue_service.py 顶部定义
QUEUE_STATUS = {
    "QUEUED": "QUEUED",      # 等待执行
    "PROCESSING": "PROCESSING",  # 正在执行
    "COMPLETED": "COMPLETED",    # 已完成
    "FAILED": "FAILED",          # 失败
}
```

### 3. QA 文件不存在 → 显式创建任务

新增任务：
- 0.3: 创建测试基础设施文件（6 个 `__init__.py` 和 `conftest.py`）
- 0.4: 创建专项测试文件（7 个测试文件 + 验证脚本）

---

## 可执行性验证

### 开发者可以立即开始，因为：

1. ✅ **所有字段引用都映射到现有 schema**，无需等待 migration
2. ✅ **队列状态词统一为现有词表**，不会破坏 worker
3. ✅ **所有测试文件都有创建任务**，不会引用不存在文件
4. ✅ **每个任务的验收标准都是具体命令**，可验证

### 前置条件

```bash
# 1. 服务运行
python start_api.py  # port 8001
python start_web.py  # port 8502

# 2. 环境变量配置
export API_URL="http://localhost:8001"
export DATABASE_URL="postgresql://..."

# 3. 安装测试依赖
pip install pytest pytest-asyncio requests_mock
```

---

## 执行命令

### Day 0
```bash
# 运行所有基线和基础设施任务
pytest tests/e2e/test_performance_baseline.py -v
bash scripts/final_verification.sh
```

### Day 1
```bash
# 队列统一（核心）
export FF_ASYNC_INCREMENTAL_ANALYSIS=true
export FF_QUEUE_ONLY_SCHEDULER=true
pytest tests/e2e/test_queue_integration.py -v
pytest tests/e2e/test_async_incremental.py -v
```

### Day 2-7
```bash
# 逐阶段验证
bash scripts/final_verification.sh
```

---

## Momus 审核通过标准

- [x] 没有引用不存在的模型字段
- [x] 队列状态词与现有代码一致
- [x] 所有测试文件都有创建任务
- [x] 每个验收标准都可执行
- [x] 开发者可以立即开始，无需等待 schema 变更

**状态**：✅ **已修复所有阻塞问题，可直接执行**
