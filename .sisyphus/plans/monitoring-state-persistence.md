# 自选股监控状态持久化 - 工作计划

## 背景
当前自选股监控状态（开始/暂停）仅存储在 Streamlit session state 和内存中，页面刷新后状态丢失。用户需要刷新后仍保持监控状态。

## 方案选择
**方案 B：全局监控开关 + WatchlistConfig 表**
- 新建 `WatchlistConfig` 表存储全局配置
- 所有自选股共享同一个监控开关状态
- 调度器启动时从数据库恢复状态

## 实施范围

### 1. 数据库层（webapi/models/database.py）
**新增表：WatchlistConfig**
```python
class WatchlistConfig(Base):
    """Global watchlist configuration table."""
    __tablename__ = "watchlist_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(50), nullable=False, unique=True, index=True)
    config_value = Column(Text, nullable=True)  # JSON存储
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**初始配置项：**
- `monitoring_active`: "true"/"false" - 全局监控开关
- `monitoring_started_at`: ISO时间字符串 - 监控开始时间
- `monitoring_interval`: "5" - 监控间隔分钟数

**是否需要 Alembic 迁移：** 是（新增表）

---

### 2. API 层（webapi/routers/watchlist.py）

**新增 Pydantic 模型：**
```python
class MonitoringStateResponse(BaseModel):
    is_active: bool
    started_at: Optional[str]
    interval_minutes: int

class MonitoringStateUpdate(BaseModel):
    is_active: bool
```

**新增端点：**

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/watchlist/monitoring/state` | 获取当前监控状态 |
| POST | `/api/v1/watchlist/monitoring/state` | 更新监控状态（开/关） |
| POST | `/api/v1/watchlist/monitoring/start` | 开始监控（快捷端点） |
| POST | `/api/v1/watchlist/monitoring/stop` | 停止监控（快捷端点） |

**逻辑说明：**
- `GET /state`：查询 WatchlistConfig 表返回 monitoring_active 状态
- `POST /state`：更新 WatchlistConfig，同时控制调度器启停
- 调度器状态与数据库状态保持同步

---

### 3. 调度器服务（webapi/services/scheduler_service.py）

**修改点：**
1. `start()` 方法：添加 `persist=True` 参数，启动时写入数据库
2. `stop()` 方法：添加 `persist=True` 参数，停止时更新数据库
3. 新增 `restore_state()` 方法：启动时检查数据库状态，如果 monitoring_active=true 则自动启动调度器

**关键代码逻辑：**
```python
def restore_state(self):
    """Restore scheduler state from database on startup."""
    from webapi.models.database import SessionLocal, WatchlistConfig
    db = SessionLocal()
    try:
        config = db.query(WatchlistConfig).filter(
            WatchlistConfig.config_key == "monitoring_active"
        ).first()
        if config and config.config_value == "true":
            logger.info("[SCHEDULER] Restoring monitoring state: ACTIVE")
            self.start(persist=False)  # 不重复写入数据库
        else:
            logger.info("[SCHEDULER] Restoring monitoring state: INACTIVE")
    finally:
        db.close()
```

---

### 4. FastAPI 生命周期集成（webapi/server.py）

**新增任务：在 FastAPI startup 事件中初始化调度器**

当前 `webapi/server.py` 没有启动调度器，需要添加：

```python
from webapi.services.scheduler_service import WatchlistScheduler

scheduler = WatchlistScheduler()

@app.on_event("startup")
async def startup_event():
    """Initialize scheduler on startup."""
    scheduler.restore_state()  # 从数据库恢复监控状态

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown scheduler on exit."""
    if scheduler.is_running:
        scheduler.stop()
```

**移除假的 `_scheduler_state`**：
- `webapi/routers/watchlist.py` 第 326-340 行的假状态需要替换为真实调度器引用

---

### 5. 前端层（web/components/watchlist_manager.py）

**修改点 1：初始化时从 API 获取状态**
```python
def initialize_monitoring_state():
    """Fetch monitoring state from API on page load."""
    try:
        response = requests.get(f"{API_URL}/api/v1/watchlist/monitoring/state")
        if response.status_code == 200:
            data = response.json()
            st.session_state.monitoring_active = data.get("is_active", False)
            st.session_state.monitoring_started_at = data.get("started_at")
    except Exception as e:
        logger.error(f"Failed to fetch monitoring state: {e}")
        # Fallback to session state default
        if "monitoring_active" not in st.session_state:
            st.session_state.monitoring_active = False
```

**修改点 2：点击开始/停止时调用 API**
```python
# 新代码  
if st.button("▶️ 开始监控"):
    try:
        response = requests.post(f"{API_URL}/api/v1/watchlist/monitoring/start")
        if response.status_code == 200:
            st.session_state.monitoring_active = True
            st.success("监控已启动")
        else:
            st.error("启动监控失败")
    except Exception as e:
        st.error(f"请求失败: {e}")
```

---

### 6. 数据库初始化（scripts/init_database.py 或 Alembic）

**新增初始配置：**
```python
# 在数据库初始化时插入默认配置
def init_watchlist_config(db: Session):
    defaults = [
        {"config_key": "monitoring_active", "config_value": "false"},
        {"config_key": "monitoring_interval", "config_value": "5"},
    ]
    for item in defaults:
        exists = db.query(WatchlistConfig).filter(
            WatchlistConfig.config_key == item["config_key"]
        ).first()
        if not exists:
            db.add(WatchlistConfig(**item))
    db.commit()
```

---

## 执行步骤（建议顺序）

### Wave 1：数据库与模型
- [x] **Task 1**：新增 WatchlistConfig 表模型  
  **QA**: `alembic upgrade head` 后，用 `psql -c "\dt"` 确认 `watchlist_config` 表存在；查询表确认有 `monitoring_active=false` 默认行

- [x] **Task 2**：创建 Alembic 迁移脚本  
  **QA**: `alembic revision --autogenerate -m "add watchlist_config table"` 成功生成 migration 文件；文件包含 create_table 和 drop_table 逻辑

- [x] **Task 3**：运行迁移，验证表创建成功  
  **QA**: `alembic upgrade head` 无报错；`psql -c "SELECT * FROM watchlist_config"` 返回空表或默认数据

### Wave 2：API 层
- [x] **Task 4**：新增 Pydantic 模型和 API 端点  
  **QA**: `curl http://localhost:8000/api/v1/watchlist/monitoring/state` 返回 `{"is_active": false, "started_at": null, "interval_minutes": 5}`；POST 更新后再次 GET 返回更新值

- [x] **Task 5**：修改 scheduler_service.py 支持 restore_state  
  **QA**: 在 Python REPL 中 `from webapi.services.scheduler_service import scheduler; scheduler.restore_state()` 不报错；数据库 `monitoring_active=true` 时调度器自动启动

- [x] **Task 6**：FastAPI 生命周期集成（startup/shutdown）  
  **QA**: 启动 API `python -m webapi.server` 查看日志包含 "[SCHEDULER] Restoring monitoring state"；startup 事件成功执行

### Wave 3：前端层
- [x] **Task 7**：修改 watchlist_manager.py 初始化逻辑  
  **QA**: 刷新 Streamlit 页面，`initialize_monitoring_state()` 被调用；Chrome DevTools Network 面板看到对 `/monitoring/state` 的 GET 请求

- [x] **Task 8**：修改按钮点击事件调用 API  
  **QA**: 点击"开始监控"按钮，Network 面板看到 POST `/monitoring/start`；返回 200 后按钮变为"⏸️ 暂停监控"

### Wave 4：集成验证
- [x] **Task 9**：端到端测试（刷新页面验证状态保持）  
  **QA**: 
  1. 点击"开始监控"
  2. 刷新浏览器页面（F5）
  3. 验证按钮仍显示"⏸️ 暂停监控"而非"▶️ 开始监控"
  4. 查看数据库 `SELECT config_value FROM watchlist_config WHERE config_key='monitoring_active'` 返回 "true"

- [x] **Task 10**：服务器重启恢复测试  
  **QA**:
  1. 确保监控状态为运行中
  2. 重启 API 服务器（Ctrl+C 再启动）
  3. 查看启动日志包含 "[SCHEDULER] Restoring monitoring state: ACTIVE"
  4. 调度器自动恢复运行

- [x] **Task 11**：Git commit  
  **QA**: `git status` 显示修改的文件；`git log -1` 显示提交信息包含 "feat: persistent monitoring state"

---

## 依赖关系

```
Task 1 (Model) ──┬──► Task 2 (Migration) ──┬──► Task 3 (Run migration)
                                                    │
Task 4 (API) ◄──────────────────────────────────────┘
    │
    ├──► Task 5 (Scheduler restore_state)
    │           │
    │           └──► Task 6 (FastAPI lifecycle)
    │                       │
    └──► Task 7-8 (Frontend) ◄── 依赖 API 端点可用
                │
                └──► Task 9-10 (E2E tests)
                            │
                            └──► Task 11 (Commit)
```

## 关键风险与注意事项

1. **并发问题**：多个用户同时操作监控开关怎么办？
   - 方案：使用数据库行级锁（`SELECT FOR UPDATE`）或乐观锁（version 字段）
   - 简化：先不考虑并发，乐观处理

2. **服务器重启**：调度器重启后如何恢复？
   - 方案：`scheduler.restore_state()` 在 FastAPI `startup` 事件中调用

3. **Streamlit 多用户**：Streamlit 是无状态服务，每个用户 session 独立
   - 方案：状态存在后端数据库，前端定期轮询保持同步

4. **向后兼容**：现有代码依赖 `st.session_state.monitoring_active`
   - 方案：保留 session state，但初始化时从 API 填充，保持兼容

5. **假的 _scheduler_state**：`webapi/routers/watchlist.py` 第 326-340 行需要替换
   - 方案：移除假状态，改为调用真实 `scheduler.is_running`

---

## 工作量估算

| 组件 | 预计时间 | 复杂度 |
|------|---------|--------|
| 数据库模型 + 迁移 | 20 min | 低 |
| API 端点 | 30 min | 中 |
| FastAPI 生命周期集成 | 15 min | 中 |
| 调度器修改 | 20 min | 中 |
| 前端修改 | 30 min | 中 |
| 测试验证 | 25 min | - |
| **总计** | **~2.5 小时** | - |

---

## 立即执行？

请确认：
1. **方案 B 确认**：全局开关（所有股票一起监控/暂停）符合需求？
2. **Alembic 迁移**：可以接受数据库迁移？
3. **开始执行**：我立即按此计划实施

如确认，回复 **"开始执行"** 或 **"/start-work"**，我将立即开始 Task 1。