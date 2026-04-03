# TaskTiger 实施计划

## 目标
使用 TaskTiger 替代当前的线程执行方案，彻底解决 Windows + asyncio `[Errno 22]` 问题。

## 背景
- **问题**: Windows 下 `asyncio.to_thread()` 和 `run_in_executor()` 导致 `[Errno 22] Invalid argument`
- **根因**: Python asyncio 线程在 Windows 环境下的已知问题
- **解决方案**: TaskTiger 的 **Per-task fork** 模式 - 每个任务在独立子进程中执行

## 技术方案

### 核心设计
```
FastAPI (主进程) → TaskTiger (Redis 队列) → Worker (子进程 fork)
                                          ↓
                              AnalysisRunner (同步执行)
                                          ↓
                              PostgreSQL (结果写入)
```

### 为什么 TaskTiger
1. ✅ **Per-task fork** - 每个分析任务独立进程，彻底隔离 Windows 线程问题
2. ✅ **内存泄漏防护** - 子进程结束后资源完全释放
3. ✅ **硬时间限制** - 可设置分析任务超时
4. ✅ **任务去重** - 避免重复分析
5. ✅ **零上游代码改动** - 只修改 webapi 层

---

## 实施步骤

### Phase 1: 依赖安装
**文件**: `requirements.txt`, `requirements-web.txt`

**操作**: 添加 tasktiger 依赖
```
tasktiger>=0.18.0
```

**预计时间**: 5分钟

---

### Phase 2: TaskTiger 配置
**新建文件**: `webapi/config/tasktiger_config.py`

**内容**:
- Redis 连接配置（复用现有 Redis 配置）
- TaskTiger 实例初始化
- 队列名称定义

**预计时间**: 15分钟

---

### Phase 3: 任务定义
**新建文件**: `webapi/tasks/analysis_tasks.py`

**内容**:
- `run_analysis_task()` - TaskTiger 装饰器包装的分析任务
- 进程安全的数据库写入
- 进度更新逻辑

**预计时间**: 30分钟

---

### Phase 4: 修改 AnalysisService
**修改文件**: `webapi/services/analysis_service.py`

**变更**:
1. 移除 `ThreadPoolExecutor` 初始化
2. 修改 `run_analysis()` 方法使用 TaskTiger
3. 保持现有 API 接口不变
4. 更新进度回调机制（通过 Redis/DB）

**预计时间**: 45分钟

---

### Phase 5: Worker 启动脚本
**新建文件**: `start_worker.py`

**内容**:
- TaskTiger Worker 启动入口
- Windows 进程安全设置
- 信号处理

**预计时间**: 20分钟

---

### Phase 6: 更新 start_all.py
**修改文件**: `start_all.py`

**变更**:
1. 添加 TaskTiger Worker 进程启动
2. 三进程协调（API + Web + Worker）
3. 统一信号处理

**预计时间**: 20分钟

---

### Phase 7: 配置更新
**修改文件**: `.env`

**新增配置**:
```bash
# TaskTiger Configuration
TASKTIGER_REDIS_PREFIX='tasktiger'
TASKTIGER_QUEUE_NAME='analysis'
TASKTIGER_WORKER_NUM=2
```

**预计时间**: 5分钟

---

## 文件变更清单

### 修改的文件
1. `requirements.txt` - 添加 tasktiger
2. `requirements-web.txt` - 添加 tasktiger
3. `webapi/services/analysis_service.py` - 替换线程执行为 TaskTiger
4. `start_all.py` - 添加 Worker 进程
5. `.env` - 添加 TaskTiger 配置

### 新建的文件
1. `webapi/config/tasktiger_config.py` - TaskTiger 配置
2. `webapi/tasks/__init__.py` - 任务包初始化
3. `webapi/tasks/analysis_tasks.py` - 分析任务定义
4. `start_worker.py` - Worker 启动脚本

---

## 实施检查清单

### 前置条件
- [ ] Redis 服务已安装并运行
- [ ] 项目依赖已更新
- [ ] 备份现有代码

### 实施步骤
- [ ] Phase 1: 添加依赖
- [ ] Phase 2: 创建 TaskTiger 配置
- [ ] Phase 3: 创建任务定义
- [ ] Phase 4: 修改 AnalysisService
- [ ] Phase 5: 创建 Worker 启动脚本
- [ ] Phase 6: 更新 start_all.py
- [ ] Phase 7: 更新配置

### 测试验证
- [ ] 单个分析任务成功执行
- [ ] 多个并发任务无错误
- [ ] 进度更新正常
- [ ] Windows 环境无 `[Errno 22]` 错误
- [ ] 任务超时处理正常
- [ ] Worker 重启后任务恢复

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Redis 连接失败 | 低 | 高 | 添加连接重试，降级到同步执行 |
| Worker 进程崩溃 | 低 | 中 | TaskTiger 自动重启，监控日志 |
| 任务序列化问题 | 中 | 中 | 使用 JSON 序列化，测试边界情况 |
| Windows 权限问题 | 低 | 中 | 以普通用户权限运行，避免 UAC |

---

## 回滚计划

如果 TaskTiger 方案出现问题：

1. **快速回滚**:
   ```bash
   git checkout webapi/services/analysis_service.py
   git checkout start_all.py
   ```

2. **恢复线程执行**:
   - 代码层面已保留 `_run_sync_analysis()` 方法
   - 只需修改 `run_analysis()` 回退到同步调用

3. **备选方案**:
   - 如果 TaskTiger 失败，回退到直接的 subprocess 方案
   - 或继续研究 hypercorn 替代

---

## 成功标准

1. ✅ Windows 环境下不再出现 `[Errno 22]` 错误
2. ✅ 分析任务可以并发执行（多个 Worker 进程）
3. ✅ 任务进度实时更新到前端
4. ✅ API 服务器响应不受影响（非阻塞）
5. ✅ 任务可以设置超时自动终止
6. ✅ Worker 崩溃后任务可以重试

---

## 参考文档

- TaskTiger GitHub: https://github.com/superbogy/tasktiger
- TaskTiger 文档: https://tasktiger.readthedocs.io/
- FastAPI Background Tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/

---

## 执行命令

启动实施：
```bash
/start-work tasktiger-implementation
```

查看进度：
```bash
/status
```

完成任务：
```bash
/complete
```
