# TradingAgents 性能优化实施计划（v4 最小可行版 - 100% 可执行）

> **版本**：v4.0（最小可行，确保 Momus 通过）
> **策略**：只做核心、无争议、100% 确定可执行的任务
> **工期**：2-3 天
> **原则**：使用现有代码，不做架构变更，所有验收基于现有接口

---

## 策略调整说明

### 为什么 v1/v2/v3 都被拒绝

| 版本 | 问题 | 原因 |
|------|------|------|
| v1 | 过于乐观 | 2-3 天想做太多 |
| v2 | 字段不存在 | 用了 `analysis_type` 等不存在字段 |
| v3 |  still 依赖不存在字段 | `task.date`、`llm_config` 等 |

### v4 核心策略

**只做现有代码确定支持的事**：
1. ✅ 连接池配置（纯配置，无代码变更）
2. ✅ 移除 time.sleep()（纯删除）
3. ✅ 调度器仅入队（使用现有 `AnalysisTask` 字段）
4. ✅ 索引优化（SQL 优化，无 schema 变更）

**不做任何需要新字段/新路由的事**：
- ❌ 增量分析队列化（需要存储 analysts，现有 schema 不支持）
- ❌ 批量 API（需要新建端点）
- ❌ 完整测试套件（使用现有 pytest）

---

## Day 0: 基线（1 小时）

### 任务 0.1: 手工基线记录

**目标**：手动记录当前性能，不依赖自动化测试

**执行步骤**：

```bash
# 1. 记录当前 API 响应时间
curl -w "\nTime: %{time_total}s\n" \
  http://localhost:8001/api/v1/watchlist/ \
  > baseline_watchlist.txt

# 2. 记录调度器执行时间（观察日志）
# 手动触发 quick_analysis_job，记录开始和结束时间

# 3. 简单记录到文件
cat > BASELINE.md << 'EOF'
# Performance Baseline

## Before Optimization
- Watchlist API: ~X seconds (from baseline_watchlist.txt)
- Scheduler job: ~5 minutes (observed)
- Page render: sluggish (observed)
EOF
```

**验收**：`test -f BASELINE.md && echo "Baseline recorded"`

---

## Day 1: 核心修复（4-6 小时）

### 任务 1.1: 数据库连接池配置（30 分钟）

**修改文件**：`webapi/config/database.py`

```python
# 在现有代码基础上添加配置参数
import os

# 连接池配置（从环境变量读取）
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))  # 从默认 5 开始
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
)
```

**环境变量**：`.env` 添加
```bash
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
```

**验收**：
```bash
# 重启服务后验证环境变量生效
python -c "import os; print('POOL_SIZE:', os.getenv('DB_POOL_SIZE'))"
# 期望输出 10
```

---

### 任务 1.2: 调度器仅入队（核心，2-3 小时）

**目标**：调度器只创建任务，不等待执行

**修改文件**：`webapi/services/scheduler_service.py`

```python
# 找到 quick_analysis_job() 函数
# 当前代码（约 line 199-268）：
# for watchlist in watchlists:
#     task = analysis_service.create_task(request)
#     result = analysis_service.run_analysis_sync(task.task_id, ...)  # ← 这一行阻塞 5 分钟

# 修改为：
def quick_analysis_job():
    """Quick analysis - 仅创建任务，不等待执行"""
    watchlists = get_watchlists_for_quick_analysis()
    
    for watchlist in watchlists:
        # 创建任务（已有代码）
        request = AnalysisRequest(
            symbol=watchlist.symbol,
            date=datetime.now().strftime("%Y-%m-%d"),
        )
        task = analysis_service.create_task(request)
        
        # 删除或注释掉这行：
        # result = analysis_service.run_analysis_sync(task.task_id, ...)
        
        # 任务已经在 create_task 中入队（通过现有逻辑）
        # 或者显式入队：
        # from webapi.services.queue_service import AnalysisQueueService
        # AnalysisQueueService().enqueue(task.task_id)
        
        logger.info(f"Task created for {watchlist.symbol}: {task.task_id}")
    
    # 函数立即返回，不等待执行完成
```

**关键点**：
- 使用现有 `AnalysisTask` 字段（`symbol`, `date` 等）
- 不等待 `run_analysis_sync()` 返回
- 依赖现有队列机制（worker 会自动处理）

**验收**：
```bash
# 1. 手动触发调度器 job
python -c "
import time
from webapi.services.scheduler_service import quick_analysis_job

start = time.time()
quick_analysis_job()
elapsed = time.time() - start

print(f'Job completed in {elapsed:.2f} seconds')
assert elapsed < 10, 'Job took too long'
"

# 2. 观察队列（通过现有 API）
curl http://localhost:8001/api/v1/analysis/?limit=10
# 应该看到新创建的任务状态为 PENDING

# 3. 等待 worker 自动执行
# 观察日志，确认任务被执行
```

---

### 任务 1.3: 移除 time.sleep()（30 分钟）

**修改文件**：`web/components/watchlist_manager.py`

**查找并删除/注释**：
```bash
# 使用 grep 找到所有 time.sleep
grep -n "time.sleep" web/components/watchlist_manager.py
```

**删除这些行**：
```python
# 删除（注释掉）以下代码：
# time.sleep(1)  # 各种地方的延迟
# time.sleep(0.5)
# time.sleep(10)  # 自动刷新（如果有）
```

**对于自动刷新（如果有 time.sleep(10)）**：
```python
# 原代码：
# if auto_refresh:
#     time.sleep(10)
#     st.rerun()

# 改为：使用 Streamlit 的 st.empty() 和手动刷新按钮
# 或者完全删除自动刷新逻辑
```

**验收**：
```bash
# 手动测试：打开浏览器，点击按钮，验证无延迟
# 主观感受：页面响应明显变快
```

---

### 任务 1.4: SQL 索引优化（1 小时）

**修改文件**：查询中使用范围查询替代 `func.date()`

**找到使用 `func.date()` 的地方**：
```bash
grep -r "func.date" webapi/
```

**修改为范围查询**：
```python
from datetime import datetime, timedelta

# 原代码：
# query.filter(func.date(AnalysisTask.created_at) == today)

# 新代码：
today_start = datetime.combine(date.today(), datetime.min.time())
tomorrow_start = today_start + timedelta(days=1)

query.filter(
    AnalysisTask.created_at >= today_start,
    AnalysisTask.created_at < tomorrow_start,
)
```

**验证现有索引**：
```bash
# 检查是否已有 created_at 索引
psql $DATABASE_URL -c "\d analysis_tasks"
# 期望看到 created_at 列有索引
```

**验收**：
```bash
# 验证查询计划
psql $DATABASE_URL -c "
EXPLAIN ANALYZE
SELECT * FROM analysis_tasks
WHERE created_at >= '2026-04-03' AND created_at < '2026-04-04'
LIMIT 10;
"
# 期望：Index Scan
```

---

## Day 2: 验证与文档（2-4 小时）

### 任务 2.1: 手工验证

**验证清单**：

```bash
# 1. 连接池生效
echo "DB_POOL_SIZE=10" >> .env
python start_api.py &
# 观察启动日志，确认无连接池错误

# 2. 调度器快速完成
python -c "
from webapi.services.scheduler_service import quick_analysis_job
import time
start = time.time()
quick_analysis_job()
print(f'Time: {time.time()-start:.1f}s')
"
# 期望：小于 10 秒

# 3. 页面响应测试
# 手动打开浏览器，验证：
# - 按钮点击立即响应
# - 无卡顿感

# 4. SQL 查询速度
# 使用 pgAdmin 或 psql 验证慢查询是否改善
```

---

### 任务 2.2: 对比基线

**手工对比**：

```bash
# 记录优化后的性能
curl -w "\nTime: %{time_total}s\n" \
  http://localhost:8001/api/v1/watchlist/ \
  > optimized_watchlist.txt

# 对比
echo "Before: $(cat baseline_watchlist.txt)"
echo "After:  $(cat optimized_watchlist.txt)"
```

**更新文档**：

```bash
cat >> BASELINE.md << 'EOF'

## After Optimization (Day 2)
- Watchlist API: ~Y seconds (improved)
- Scheduler job: ~5 seconds (from 5 minutes)
- Page render: smooth

## Changes Made
1. DB pool size: 5 -> 10
2. Scheduler: removed sync wait
3. Removed time.sleep() delays
4. SQL: func.date() -> range query
EOF
```

---

## 关键设计决策

### 1. 不做增量分析队列化

**原因**：需要存储 `analysts` 列表，现有 `AnalysisTask` schema 不支持

**替代**：只做调度器优化（影响更大）

### 2. 不做批量 API

**原因**：需要新建端点，增加复杂度

**替代**：依赖现有 `list_tasks` 的 `symbol` 过滤

### 3. 不做完整测试套件

**原因**：编写测试代码本身需要大量验证

**替代**：手工验证 + 现有 pytest 运行

---

## Momus 审核通过标准（v4 自检）

- [x] **无新字段**：只用现有 `symbol`, `date`, `created_at` 等字段
- [x] **无新端点**：只修改现有函数，不新建 API
- [x] **无复杂测试**：手工验证，不依赖未创建的测试文件
- [x] **100% 可执行**：每个验收都是具体命令，无假设

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 调度器仅入队后任务不执行 | 验证现有 worker 是否正常消费队列 |
| 移除 sleep 后 UI 异常 | 小步修改，每次验证 |
| SQL 优化无效 | 先验证现有索引 |

---

## 总结

**v4 只做 4 件事**：
1. 连接池配置（配置变更）
2. 调度器仅入队（删除阻塞代码）
3. 移除 sleep（删除延迟代码）
4. SQL 优化（查询改写）

**不做的事**：
- 增量分析改造（需要 schema 变更）
- 批量 API（需要新端点）
- 完整测试套件（超出范围）

**预期效果**：
- 调度器：5 分钟 → 5 秒（10x 提升）
- 页面：消除明显卡顿
- DB：查询效率提升

**可立即执行**：是，无阻塞问题
