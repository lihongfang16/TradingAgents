# TradingAgents 性能优化（v7 最终修正版）

> **版本**：v7.0（修复 Oracle 发现的所有问题）
> **任务**：2 个安全任务
> **工期**：半天

---

## 任务 1：数据库连接池配置

### 修改内容

**文件**：`webapi/config/database.py`

```python
# 现有代码（约第 11 行）：
# engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# 修改为：
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
)
```

### 验证

```bash
# 1. 环境变量已设置
cat .env | grep DB_POOL
# 输出：DB_POOL_SIZE=10

# 2. 服务重启后正常
curl http://localhost:8001/health
# 返回：{"status": "healthy"}
```

---

## 任务 2：选择性移除 time.sleep()

### 分类处理（经 Oracle 验证）

**可安全删除的（6 处）**：

| 行号 | 用途 | 处理方式 |
|------|------|----------|
| 633 | 增量分析后延迟 | 删除 |
| 1053 | 添加股票后延迟 | 删除 |
| 1204 | 全量分析后延迟 | 删除 |
| 1277 | 启动监控后延迟 | 删除 |
| 1284 | 暂停监控后延迟 | 删除 |
| 1303 | 批量分析后延迟 | 删除 |
| 1654 | 保存设置后延迟 | 删除 |

**必须保留的（2 处）**：

| 行号 | 用途 | 原因 |
|------|------|------|
| 1299 | 批量请求间隔 | **速率限制**，防 API 洪水 |
| 1864 | 自动刷新轮询 | **功能必需**，防无限循环 |

### 实施步骤

```bash
# 1. 只删除安全的 7 处
grep -n "time.sleep" web/components/watchlist_manager.py | grep -E "633:|1053:|1204:|1277:|1284:|1303:|1654:"
# 逐个删除

# 2. 保留 1299 和 1864（不删除）
grep -n "time.sleep" web/components/watchlist_manager.py | grep -E "1299:|1864:"
# 应仍显示这 2 行
```

### 验证

```bash
# 确认剩余 2 处（1299, 1864）
grep -c "time.sleep" web/components/watchlist_manager.py
# 期望输出：2

# 手工测试：页面响应变快，无卡顿，自动刷新正常
```

---

## 修正摘要（对比 v6）

| 问题 | v6 | v7 修正 |
|------|-----|---------|
| import os 重复 | 说添加，实际已存在 | 删除该指令 |
| 行数估计 | 说"3~5行" | 实际 9 行，分类处理 |
| 1299 行 | 未识别为速率限制 | **明确保留** |
| 1864 行 | 未识别为轮询间隔 | **明确保留** |
| 验证目标 | grep -c → 0（危险） | grep -c → 2（正确） |
| pkill 命令 | Linux only | 改为通用重启说明 |

---

## 安全声明

- ✅ 1299 行：`time.sleep(0.2)` 保留，防止批量 API 洪水
- ✅ 1864 行：`time.sleep(10)` 保留，防止自动刷新无限循环
- ✅ 只删除真正 cosmetic 的 7 处延迟
- ✅ 所有变更可验证、可回滚

---

## Momus/Oracle 自检

- [x] 所有文件路径已验证存在
- [x] 所有函数/字段已验证存在
- [x] 无 schema 变更
- [x] 无新端点
- [x] 验收标准可执行且安全
- [x] 识别并保留了功能性 sleep
- [x] 修正了行数估计错误

**状态**：已修复 Oracle 发现的所有问题，可执行。