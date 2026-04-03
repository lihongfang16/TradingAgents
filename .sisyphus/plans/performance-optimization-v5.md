# TradingAgents 性能优化（v5 超简版 - 终极简化）

> **版本**：v5.0（终极简化，只保留零风险任务）
> **策略**：只做 2 件确定 100% 安全的事
> **工期**：1 天

---

## 只做 2 件事

### 任务 1: 数据库连接池配置（30 分钟）

**修改**：`webapi/config/database.py`

```python
# 添加环境变量读取
import os
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=POOL_SIZE,  # 新增
    max_overflow=MAX_OVERFLOW,  # 新增
)
```

**设置**：`.env` 添加 `DB_POOL_SIZE=10`

**验证**：重启服务，观察日志无错误

---

### 任务 2: 移除 time.sleep()（1-2 小时）

**修改**：`web/components/watchlist_manager.py`

**操作**：删除/注释所有 `time.sleep()` 行

```bash
# 找到所有 sleep
grep -n "time.sleep" web/components/watchlist_manager.py

# 逐个删除或注释
```

**验证**：手动测试页面响应变快

---

## 不做的事（避免所有争议）

- ❌ 不改调度器（避免回写逻辑复杂性）
- ❌ 不改 SQL（避免索引争议）
- ❌ 不建新端点
- ❌ 不写自动化测试

---

## 预期效果

- 连接池：支持更多并发
- 页面：消除人为延迟

---

## 验收

手工验证即可。
