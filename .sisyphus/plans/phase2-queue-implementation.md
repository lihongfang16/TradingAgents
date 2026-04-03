# Phase 2 增强计划：PostgreSQL 队列 + Subprocess

## 目标
直接实施 Metis 建议的 Phase 2 架构，添加 PostgreSQL 队列支持，解决固定并发限制问题。

## 为什么跳过纯 Subprocess（Phase 1）

| 问题 | Phase 1（纯 Subprocess） | Phase 2（PostgreSQL 队列） |
|------|------------------------|---------------------------|
| 并发限制 | Semaphore(3) 硬限制 | 队列 + 可配置 Worker 数量 |
| 任务排队 | 第4个任务阻塞等待 | 所有任务入队，Worker 顺序处理 |
| 任务持久化 | 只在内存中等待 | 持久化到 PostgreSQL |
| 失败重试 | 无 | 可配置重试次数 |
| 优先级 | 无 | 可实现（高/中/低） |
| 监控 | 无队列深度指标 | 可查询队列长度 |

## 架构设计（Phase 2）

```
┌────────────────────────────────────────────────────────────────┐
│                     FastAPI (主进程)                           │
│  ┌────────────────────────────────────────────────────────┐   │
│  │          API Endpoint / Scheduler                      │   │
│  └───────────────────────┬────────────────────────────────┘   │
│                          │                                     │
│                          ▼                                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │       AnalysisService.enqueue_analysis()               │   │
│  │  ────────────────────────────────────────              │   │
│  │  1. 创建 analysis_tasks 记录 (PENDING)                 │   │
│  │  2. 创建 analysis_queue 记录 (QUEUED)                  │   │
│  │  3. 立即返回 task_id                                   │   │
│  └───────────────────────┬────────────────────────────────┘   │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           │ PostgreSQL (共享)
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                    Worker 进程 (可启动多个)                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │       python -m webapi.worker                          │   │
│  │  ────────────────────────────────────────              │   │
│  │  1. 轮询 analysis_queue (状态=QUEUED)                  │   │
│  │  2. 抢占式获取任务 (UPDATE ... RETURNING)              │   │
│  │  3. 启动子进程运行分析                                  │   │
│  │  4. 完成后标记队列完成                                  │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│              子进程: python -m webapi.subprocess_runner        │
│                      (完全隔离，Windows 兼容)                   │
└────────────────────────────────────────────────────────────────┘
```

## 核心改进

1. **队列持久化**: 任务入队后立即持久化，不丢失
2. **Worker 可扩展**: 可启动 1-N 个 Worker 进程
3. **抢占式任务分配**: 多个 Worker 不会重复执行同一任务
4. **队列监控**: 可查询队列长度、等待时间

---

## 实施步骤

### Phase 1: 创建队列表（Alembic 迁移）
**文件**: `alembic/versions/xxxx_add_analysis_queue_table.py`

**队列表结构**:
```python
class AnalysisQueue(Base):
    """PostgreSQL-based task queue for analysis jobs."""
    
    __tablename__ = "analysis_queue"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(36), ForeignKey("analysis_tasks.task_id"), nullable=False)
    
    # 队列状态
    status = Column(String(20), nullable=False, index=True)  # QUEUED, PROCESSING, COMPLETED, FAILED
    
    # 优先级 (数值越大优先级越高)
    priority = Column(Integer, nullable=False, default=0, index=True)
    
    # 重试机制
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    
    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Worker 标识
    worker_id = Column(String(50), nullable=True)  # 哪个 Worker 在处理
    
    # 错误信息
    error_message = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_queue_status_priority', 'status', 'priority', 'created_at'),
        Index('idx_queue_task_id', 'task_id'),
    )
```

**预计时间**: 20分钟

---

### Phase 2: 创建子进程运行器
**文件**: `webapi/subprocess_runner.py`

与之前计划相同，但增加队列状态更新：
```python
#!/usr/bin/env python3
"""Subprocess runner for analysis tasks - Windows compatible."""
import os
import sys

# CRITICAL: 必须在任何其他导入前加载环境变量
from dotenv import load_dotenv
load_dotenv()

# Windows asyncio fix
import platform
if platform.system() == "Windows":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 然后才导入依赖环境变量的模块
from tradingagents.core.analysis_runner import AnalysisRunner
from webapi.config.database import SessionLocal
from webapi.models.database import AnalysisTask, AnalysisQueue

def main():
    task_id = sys.argv[1]
    worker_id = sys.argv[2] if len(sys.argv) > 2 else "unknown"
    
    # 标记队列状态为 PROCESSING
    _update_queue_status(task_id, "PROCESSING", worker_id=worker_id)
    
    try:
        # 获取任务详情
        request = _get_task_request(task_id)
        
        # 创建 runner
        runner = AnalysisRunner(...)
        
        # 执行分析
        result = runner.run()
        
        # 写入结果
        _update_task_result(task_id, result)
        
        # 标记队列完成
        _update_queue_status(task_id, "COMPLETED")
        
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        _update_queue_status(task_id, "FAILED", error=error_msg)
        sys.exit(1)

def _update_queue_status(task_id: str, status: str, worker_id: str = None, error: str = None):
    """更新队列状态"""
    db = SessionLocal()
    try:
        queue_item = db.query(AnalysisQueue).filter(
            AnalysisQueue.task_id == task_id
        ).first()
        
        if queue_item:
            queue_item.status = status
            if worker_id:
                queue_item.worker_id = worker_id
            if error:
                queue_item.error_message = error
            
            if status == "PROCESSING":
                queue_item.started_at = datetime.utcnow()
            elif status in ["COMPLETED", "FAILED"]:
                queue_item.completed_at = datetime.utcnow()
            
            db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    main()
```

**预计时间**: 40分钟

---

### Phase 3: 创建队列服务
**文件**: `webapi/services/queue_service.py`

**核心功能**:
```python
class AnalysisQueueService:
    """PostgreSQL-based analysis task queue."""
    
    def enqueue(self, task_id: str, priority: int = 0) -> bool:
        """将任务加入队列"""
        db = SessionLocal()
        try:
            queue_item = AnalysisQueue(
                task_id=task_id,
                status="QUEUED",
                priority=priority,
                retry_count=0,
                max_retries=3,
            )
            db.add(queue_item)
            db.commit()
            return True
        finally:
            db.close()
    
    def dequeue(self, worker_id: str) -> Optional[str]:
        """
        抢占式获取任务。
        使用 SELECT FOR UPDATE 确保多个 Worker 不会获取同一任务。
        """
        db = SessionLocal()
        try:
            # 原子操作：获取并标记任务
            result = db.execute(
                """
                UPDATE analysis_queue 
                SET status = 'PROCESSING', 
                    worker_id = :worker_id,
                    started_at = NOW()
                WHERE id = (
                    SELECT id FROM analysis_queue 
                    WHERE status = 'QUEUED' 
                    ORDER BY priority DESC, created_at ASC 
                    FOR UPDATE SKIP LOCKED 
                    LIMIT 1
                )
                RETURNING task_id;
                """,
                {"worker_id": worker_id}
            )
            
            row = result.fetchone()
            db.commit()
            
            return row[0] if row else None
        finally:
            db.close()
    
    def get_queue_stats(self) -> dict:
        """获取队列统计信息"""
        db = SessionLocal()
        try:
            stats = db.query(
                AnalysisQueue.status,
                func.count(AnalysisQueue.id)
            ).group_by(AnalysisQueue.status).all()
            
            return {
                status: count for status, count in stats
            }
        finally:
            db.close()
    
    def requeue_failed(self, max_retries: int = 3) -> int:
        """重新入队失败但可重试的任务"""
        db = SessionLocal()
        try:
            result = db.execute(
                """
                UPDATE analysis_queue 
                SET status = 'QUEUED',
                    retry_count = retry_count + 1,
                    error_message = NULL
                WHERE status = 'FAILED' 
                AND retry_count < :max_retries;
                """,
                {"max_retries": max_retries}
            )
            db.commit()
            return result.rowcount
        finally:
            db.close()
```

**预计时间**: 40分钟

---

### Phase 4: 创建 Worker
**文件**: `webapi/worker.py`

```python
#!/usr/bin/env python3
"""
Analysis Worker - PostgreSQL Queue Consumer

Usage:
    python -m webapi.worker --worker-id worker-1
    python -m webapi.worker --worker-id worker-2  # 启动多个
"""
import argparse
import os
import sys
import time
import uuid
from datetime import datetime

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# Windows asyncio fix
import platform
if platform.system() == "Windows":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from webapi.services.queue_service import AnalysisQueueService

class AnalysisWorker:
    def __init__(self, worker_id: str, poll_interval: float = 1.0):
        self.worker_id = worker_id
        self.poll_interval = poll_interval
        self.queue_service = AnalysisQueueService()
        self.running = False
    
    def start(self):
        """启动 Worker"""
        logger.info(f"Worker {self.worker_id} started")
        self.running = True
        
        while self.running:
            try:
                # 尝试获取任务
                task_id = self.queue_service.dequeue(self.worker_id)
                
                if task_id:
                    logger.info(f"Worker {self.worker_id} processing task {task_id}")
                    self._process_task(task_id)
                else:
                    # 无任务，等待
                    time.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}")
                time.sleep(self.poll_interval)
    
    def _process_task(self, task_id: str):
        """处理单个任务"""
        import subprocess
        
        try:
            # 启动子进程运行分析
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m", "webapi.subprocess_runner",
                    task_id,
                    self.worker_id
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            # 等待完成（带超时）
            stdout, stderr = proc.communicate(timeout=600)  # 10分钟超时
            
            if proc.returncode != 0:
                logger.error(f"Task {task_id} failed: {stderr.decode()}")
                # 子进程已更新队列状态为 FAILED
            else:
                logger.info(f"Task {task_id} completed successfully")
                
        except subprocess.TimeoutExpired:
            logger.error(f"Task {task_id} timed out")
            proc.kill()
            # 更新队列状态
            self.queue_service.mark_failed(task_id, "Timeout after 600s")
        except Exception as e:
            logger.error(f"Task {task_id} error: {e}")
            self.queue_service.mark_failed(task_id, str(e))
    
    def stop(self):
        """停止 Worker"""
        logger.info(f"Worker {self.worker_id} stopping...")
        self.running = False

def main():
    parser = argparse.ArgumentParser(description="TradingAgents Analysis Worker")
    parser.add_argument("--worker-id", default=str(uuid.uuid4())[:8], help="Worker identifier")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Queue poll interval (seconds)")
    args = parser.parse_args()
    
    worker = AnalysisWorker(args.worker_id, args.poll_interval)
    
    # 处理信号
    import signal
    def signal_handler(signum, frame):
        worker.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    worker.start()

if __name__ == "__main__":
    main()
```

**预计时间**: 40分钟

---

### Phase 5: 修改 analysis_service.py
**文件**: `webapi/services/analysis_service.py`

**核心变更**:
```python
from webapi.services.queue_service import AnalysisQueueService

class AnalysisService:
    def __init__(self):
        self.queue_service = AnalysisQueueService()
    
    async def run_analysis(
        self, 
        task_id: str, 
        request: AnalysisRequest,
        on_complete: Optional[Callable] = None,
        priority: int = 0  # 新增：优先级
    ) -> AnalysisResponse:
        """
        提交分析任务到队列。
        
        注意：此方法总是立即返回，任务在后台由 Worker 处理。
        """
        # 创建任务记录
        task_resp = self.get_task(task_id)
        if task_resp is None:
            task_resp = self.create_task(request)
            task_id = task_resp.task_id
        
        # 更新状态为 PENDING
        self._update_task_status(task_id, "PENDING")
        
        # 加入队列
        self.queue_service.enqueue(task_id, priority=priority)
        
        # 立即返回
        return AnalysisResponse(
            task_id=task_id,
            status="PENDING",
            message="Analysis queued for processing"
        )
    
    def run_analysis_sync(self, task_id: str, request: AnalysisRequest) -> AnalysisResponse:
        """
        同步执行分析（调度器使用）。
        此方法会阻塞直到分析完成。
        """
        import time
        
        # 提交到队列
        self.queue_service.enqueue(task_id, priority=10)  # 高优先级
        
        # 轮询等待完成
        max_wait = 600  # 10分钟
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            task = self.get_task(task_id)
            if task.status in ["COMPLETED", "FAILED"]:
                return task
            time.sleep(0.5)
        
        raise TimeoutError(f"Analysis {task_id} did not complete within {max_wait}s")
```

**预计时间**: 30分钟

---

### Phase 6: 更新调度器
**文件**: `webapi/services/scheduler_service.py`

**变更**: 使用 `run_analysis_sync()` 代替直接调用

```python
async def full_analysis_job(self):
    """完整分析任务 - 等待完成"""
    for stock in watchlist:
        request = AnalysisRequest(...)
        task_id = str(uuid.uuid4())
        
        # 使用同步方法，等待完成
        result = self.analysis_service.run_analysis_sync(task_id, request)
        
        # 处理结果
        self._process_result(result)
```

**预计时间**: 15分钟

---

### Phase 7: 更新启动脚本
**文件**: `start_all.py`

**变更**: 同时启动 API + Worker

```python
def main():
    # ... 启动 API ...
    
    # 启动 Worker（默认 2 个）
    worker_count = int(os.getenv("WORKER_COUNT", "2"))
    for i in range(worker_count):
        worker_proc = subprocess.Popen(
            [sys.executable, "-m", "webapi.worker", "--worker-id", f"worker-{i+1}"],
            cwd=script_dir,
        )
        processes.append(worker_proc)
```

**预计时间**: 15分钟

---

### Phase 8: 添加队列监控 API
**文件**: `webapi/routers/queue.py`（新增）

```python
from fastapi import APIRouter
from webapi.services.queue_service import AnalysisQueueService

router = APIRouter(prefix="/api/v1/queue", tags=["queue"])

@router.get("/stats")
async def get_queue_stats():
    """获取队列统计"""
    service = AnalysisQueueService()
    return service.get_queue_stats()

@router.post("/retry-failed")
async def retry_failed_tasks():
    """重试失败任务"""
    service = AnalysisQueueService()
    count = service.requeue_failed()
    return {"requeued": count}
```

**预计时间**: 15分钟

---

## 文件变更清单

### 新增文件 (5个)
1. `alembic/versions/xxxx_add_analysis_queue_table.py` - 队列表迁移
2. `webapi/subprocess_runner.py` - 子进程运行器
3. `webapi/services/queue_service.py` - 队列服务
4. `webapi/worker.py` - Worker 主程序
5. `webapi/routers/queue.py` - 队列监控 API

### 修改文件 (3个)
1. `webapi/services/analysis_service.py` - 集成队列
2. `webapi/services/scheduler_service.py` - 使用同步方法
3. `webapi/server.py` - 注册队列路由
4. `start_all.py` - 启动 Worker

---

## 配置更新

`.env` 新增：
```bash
# Worker Configuration
WORKER_COUNT=2              # 启动的 Worker 数量
WORKER_POLL_INTERVAL=1.0    # 轮询间隔（秒）
MAX_CONCURRENT_ANALYSES=5   # 最大并发（通过启动多个 Worker 实现）
```

---

## 使用方式

### 启动服务
```bash
# 方式1：一键启动（API + Worker）
python start_all.py

# 方式2：分开启动
python start_api.py        # API 服务
python -m webapi.worker --worker-id worker-1  # Worker 1
python -m webapi.worker --worker-id worker-2  # Worker 2
```

### 监控队列
```bash
# 查看队列统计
curl http://localhost:8000/api/v1/queue/stats

# 重试失败任务
curl -X POST http://localhost:8000/api/v1/queue/retry-failed
```

---

## 成功标准

1. ✅ 任务入队后立即返回（< 100ms）
2. ✅ Worker 自动消费队列任务
3. ✅ 可启动多个 Worker 并行处理
4. ✅ 队列统计 API 正常工作
5. ✅ 失败任务可重试
6. ✅ Windows 环境无 `[Errno 22]` 错误

---

## 执行命令

```bash
/start-work phase2-queue-implementation
```
