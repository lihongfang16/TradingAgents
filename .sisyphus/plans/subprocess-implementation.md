# Subprocess 实施方案（修订版）

## 基于 Momus 审查意见的更新

**审查结果**: ✅ OKAY - 技术方案正确，可以实施  
**关键修正**:
1. API 路径使用 **非阻塞设计**（立即返回任务ID）
2. 子进程必须 **先加载 .env** 再导入其他模块
3. 简化架构：**移除 subprocess_manager.py**，Semaphore 直接集成到 analysis_service.py

---

## 目标
使用 Python subprocess 替代当前同步执行，彻底解决 Windows `[Errno 22]` 问题，同时保持 API 非阻塞响应。

## 架构设计（修订）

### 双路径设计
```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI (主进程)                        │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────┐    ┌──────────────────────────────┐
│   API 端点路径      │    │    调度器路径                │
│   (非阻塞)          │    │    (同步等待)                │
│                     │    │                              │
│ POST /analysis/     │    │ APScheduler                  │
│ ──────────────────▶ │    │ ──────────────────────────▶  │
│                     │    │                              │
│ 立即返回:           │    │ asyncio.run(                 │
│ {                   │    │   run_analysis(blocking=True)│
│   "task_id": "...", │    │ )                            │
│   "status": "PENDING"    │                              │
│ }                   │    │ 等待完成                     │
│                     │    │                              │
└─────────────────────┘    └──────────────────────────────┘
         │                              │
         └──────────────┬───────────────┘
                        │
         asyncio.create_subprocess_exec()
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│         子进程: python -m webapi.subprocess_runner          │
│                      (完全隔离)                             │
│                                                             │
│  1. load_dotenv() 加载环境变量                              │
│  2. WindowsSelectorEventLoopPolicy                          │
│  3. AnalysisRunner.run()                                    │
│  4. 直接写入 PostgreSQL                                     │
└─────────────────────────────────────────────────────────────┘
```

### 并发控制
- 使用 `asyncio.Semaphore(3)` 限制最多 3 个并发子进程
- 直接集成在 `AnalysisService` 中，无需独立管理器

---

## 关键实现细节（根据 Momus 反馈）

### 1. API 非阻塞设计（修复 Momus 警告 #4）

**问题**: 如果使用 `await proc.communicate()`，API 请求会挂起 3-10 分钟

**解决方案**: 双路径设计

```python
# webapi/services/analysis_service.py

class AnalysisService:
    def __init__(self):
        # 并发控制：最多 3 个分析任务同时运行
        self._semaphore = asyncio.Semaphore(3)
    
    async def run_analysis(
        self, 
        task_id: str, 
        request: AnalysisRequest,
        on_complete: Optional[Callable] = None,
        blocking: bool = False  # 新增参数
    ) -> AnalysisResponse:
        """
        Args:
            blocking: True=调度器使用(等待完成), False=API使用(立即返回)
        """
        # 创建任务记录
        self._update_task_status(task_id, "PENDING")
        
        if blocking:
            # 调度器路径：等待完成
            async with self._semaphore:
                await self._run_subprocess(task_id, request)
            return self.get_task(task_id)
        else:
            # API 路径：后台执行，立即返回
            asyncio.create_task(self._run_analysis_background(task_id, request))
            return AnalysisResponse(
                task_id=task_id,
                status="PENDING",
                message="Analysis started in background"
            )
    
    async def _run_analysis_background(self, task_id: str, request: AnalysisRequest):
        """后台执行（API 路径）"""
        async with self._semaphore:
            await self._run_subprocess(task_id, request)
    
    async def _run_subprocess(self, task_id: str, request: AnalysisRequest):
        """实际子进程执行"""
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m", "webapi.subprocess_runner",
            task_id,
            request.model_dump_json(),  # Pydantic v2
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            # 子进程失败，更新 DB
            self._update_task_status(task_id, "FAILED", error=stderr.decode())
```

### 2. 子进程 .env 加载（修复 Momus 警告 #6）

**问题**: 子进程需要 `DATABASE_URL` 等环境变量

**解决方案**: `load_dotenv()` 必须在任何导入前执行

```python
# webapi/subprocess_runner.py
#!/usr/bin/env python3
"""Subprocess runner for analysis tasks - Windows compatible."""
import os
import sys

# CRITICAL: 必须在任何其他导入前加载环境变量
from dotenv import load_dotenv
load_dotenv()  # 自动查找 .env 文件

# Windows asyncio fix
import platform
if platform.system() == "Windows":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 然后才导入依赖环境变量的模块
from tradingagents.core.analysis_runner import AnalysisRunner
from webapi.config.database import SessionLocal
from webapi.models.database import AnalysisTask

def main():
    task_id = sys.argv[1]
    request_json = sys.argv[2]
    
    import json
    request_data = json.loads(request_json)
    
    # 转换 enum string 回 enum
    from webapi.models.analysis import AnalysisRequest, StockExchange
    request_data['exchange'] = StockExchange(request_data['exchange'])
    request = AnalysisRequest(**request_data)
    
    # 更新状态为 RUNNING
    _update_task_status(task_id, "RUNNING")
    
    try:
        # 创建 runner
        runner = AnalysisRunner(
            symbol=request.symbol,
            date=request.date,
            analysts=request.analysts or ["market", "news", "fundamentals"],
            llm_model=request.deep_model or os.getenv("DEEP_THINK_LLM"),
            llm_provider="openai",  # 映射后的 provider
            base_url=os.getenv("MINIMAX_BASE_URL"),
            api_key=os.getenv("MINIMAX_API_KEY"),
            progress_callback=lambda data: _update_progress(task_id, data),
            max_iterations=300,
        )
        
        # 执行分析
        result = runner.run()
        
        # 写入结果
        _update_task_result(task_id, result, "COMPLETED")
        
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        _update_task_status(task_id, "FAILED", error=error_msg)
        sys.exit(1)

def _update_task_status(task_id: str, status: str, error: str = None):
    """进程安全的 DB 更新"""
    db = SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
        if task:
            task.status = status
            task.updated_at = datetime.utcnow()
            if error:
                task.error = error
            db.commit()
    finally:
        db.close()

def _update_task_result(task_id: str, result: dict, status: str):
    """写入完整结果"""
    db = SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
        if task:
            task.status = status
            task.result = result
            task.completed_at = datetime.utcnow()
            task.updated_at = datetime.utcnow()
            
            # 提取决策
            if result and result.get("signal"):
                signal = result["signal"]
                if isinstance(signal, dict):
                    task.decision = signal.get("decision")
            
            db.commit()
    finally:
        db.close()

def _update_progress(task_id: str, data: dict):
    """进度回调（子进程中）"""
    db = SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
        if task:
            task.progress_pct = data.get("progress", 0)
            task.current_agent = data.get("current_agent", "")
            task.agents_progress = data.get("agents_progress", {})
            task.logs = task.logs or []
            if data.get("log"):
                task.logs.append({
                    "time": datetime.utcnow().isoformat(),
                    "agent": data.get("current_agent"),
                    "message": data["log"]
                })
            db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    main()
```

### 3. 调度器集成（修复 Momus 警告 #4）

**问题**: 调度器使用 `asyncio.run()` 包装，需要正确处理

**解决方案**: 调度器调用时传入 `blocking=True`

```python
# webapi/services/scheduler_service.py

async def full_analysis_job(self):
    """完整分析任务 - 等待完成"""
    watchlist = self._get_watchlist()
    
    tasks = []
    for stock in watchlist:
        request = AnalysisRequest(
            symbol=stock.symbol,
            date=datetime.now().strftime("%Y-%m-%d"),
            # ... 其他参数
        )
        
        # 创建任务并等待完成（blocking=True）
        task_id = str(uuid.uuid4())
        result = await self.analysis_service.run_analysis(
            task_id=task_id,
            request=request,
            blocking=True  # 关键：等待完成
        )
        tasks.append(result)
    
    return tasks

# 调度器包装（保持现有模式）
def run_full_analysis(self):
    """同步入口，供 APScheduler 调用"""
    asyncio.run(self.full_analysis_job())
```

### 4. 并发控制简化

**移除**独立的 `subprocess_manager.py`，直接集成到 `AnalysisService`:

```python
# webapi/services/analysis_service.py

class AnalysisService:
    _instance = None
    
    def __new__(cls):
        # 单例模式确保 Semaphore 全局唯一
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 并发控制：最多 3 个分析任务同时运行
        self._semaphore = asyncio.Semaphore(3)
        self._executor = None  # 移除 ThreadPoolExecutor
        
        logger.info("AnalysisService initialized with max 3 concurrent subprocesses")
```

---

## 实施步骤（修订）

### Phase 1: 创建 subprocess_runner.py
**文件**: `webapi/subprocess_runner.py`

**关键要求**:
1. `load_dotenv()` 必须在任何导入前执行
2. Windows asyncio policy 设置
3. enum string 转 enum 对象
4. 进程安全的 DB 写入
5. 进度回调实现

**参考**: 上面的完整代码示例

**预计时间**: 40分钟

---

### Phase 2: 修改 analysis_service.py
**文件**: `webapi/services/analysis_service.py`

**变更**:
1. 移除 `ThreadPoolExecutor` (line 14, 147)
2. 添加 `asyncio.Semaphore(3)`
3. 修改 `run_analysis()` 支持 `blocking` 参数
4. 添加 `_run_subprocess()` 方法
5. 实现 `_run_analysis_background()` 用于非阻塞路径

**API 端点行为**:
- `POST /analysis/` → `run_analysis(blocking=False)` → 立即返回 PENDING
- 调度器 → `run_analysis(blocking=True)` → 等待完成

**预计时间**: 50分钟

---

### Phase 3: 修复 scheduler_service.py
**文件**: `webapi/services/scheduler_service.py`

**变更**:
1. 修改 `full_analysis_job()` - 传入 `blocking=True`
2. 修改 `quick_analysis_job()` - 传入 `blocking=True`
3. 修改 `high_frequency_batch_job()` - 传入 `blocking=True`

**注意**: 调度器保持 `asyncio.run()` 包装模式

**预计时间**: 20分钟

---

### Phase 4: 测试验证

**测试清单**:

1. **子进程独立测试**
   ```bash
   python -m webapi.subprocess_runner <task_id> '<json_request>'
   ```
   - [ ] 能正确加载 .env
   - [ ] 能连接 PostgreSQL
   - [ ] 能运行 AnalysisRunner
   - [ ] 能写入结果到 DB

2. **API 非阻塞测试**
   - [ ] POST /analysis/ 立即返回（< 100ms）
   - [ ] 返回状态为 PENDING
   - [ ] 后续 GET 能查到进度更新
   - [ ] 最终状态变为 COMPLETED/FAILED

3. **并发测试**
   - [ ] 同时提交 4 个任务，第 4 个等待
   - [ ] 验证 Semaphore 限制生效
   - [ ] 无 `[Errno 22]` 错误

4. **调度器测试**
   - [ ] 定时任务正常触发
   - [ ] 任务完成后才返回（blocking 生效）

5. **Windows 兼容性**
   - [ ] Windows 环境无 `[Errno 22]`
   - [ ] 子进程正确退出，无僵尸进程

**预计时间**: 1小时

---

## 文件变更清单（修订）

### 修改的文件 (2个)
1. `webapi/services/analysis_service.py` - 核心修改，添加非阻塞支持
2. `webapi/services/scheduler_service.py` - 传入 blocking=True

### 新建的文件 (1个)
1. `webapi/subprocess_runner.py` - 子进程入口（含 .env 加载和进度回调）

### 删除的计划文件
- ~~`webapi/services/subprocess_manager.py`~~ - 已移除，功能合并到 analysis_service.py

---

## 关键代码模式总结

### 模式 1: API 非阻塞调用
```python
# 在 router 中
@app.post("/analysis/")
async def create_analysis(request: AnalysisRequest):
    task_id = str(uuid.uuid4())
    # 非阻塞，立即返回
    result = await service.run_analysis(task_id, request, blocking=False)
    return {"task_id": task_id, "status": "PENDING"}
```

### 模式 2: 调度器阻塞调用
```python
# 在 scheduler 中
async def job():
    # 阻塞，等待完成
    result = await service.run_analysis(task_id, request, blocking=True)
    process_result(result)  # 完成后处理
```

### 模式 3: 子进程入口
```python
# subprocess_runner.py
load_dotenv()  # 必须在最前面！
# ... 其他导入
```

---

## 执行命令

```bash
/start-work subprocess-implementation
```

---

## 回滚计划

如果实施失败：

```bash
# 快速回滚
git checkout webapi/services/analysis_service.py
git checkout webapi/services/scheduler_service.py
rm webapi/subprocess_runner.py

# 验证回滚
python -c "from webapi.services.analysis_service import AnalysisService; print('OK')"
```

回滚后系统将恢复到：同步执行，阻塞 API，无 `[Errno 22]` 问题（因为根本没有使用线程）
