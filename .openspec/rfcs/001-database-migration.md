# RFC-001: 数据库架构迁移

## 摘要

将 TradingAgents A-share 系统从内存+JSON文件存储架构迁移到 PostgreSQL 数据库架构，实现数据的持久化存储、高效查询和快速删除。

## 状态

- [x] Proposed
- [ ] Accepted
- [ ] Implemented
- [ ] Rejected

## 动机

当前系统面临以下存储问题：

1. **数据丢失风险**: 分析任务存储在内存 (`AnalysisService._tasks`)，API 重启后全部丢失
2. **并发安全问题**: 历史记录使用 JSON 文件 (`web/data/history.json`)，高并发写入存在竞态条件
3. **性能瓶颈**: 删除操作需要遍历整个 JSON 文件，响应时间在秒级
4. **扩展限制**: 无法支持多实例部署，无法做数据分析

## 目标

### 主要目标
- 实现分析任务的持久化存储
- 删除操作响应时间 < 100ms
- API 重启后历史数据可访问
- 开发与生产环境一致（WSL2 + Linux）

### 非目标
- 不改变现有业务逻辑
- 不修改分析引擎核心代码
- 不引入 Redis/MongoDB 等额外组件

## 方案详情

### 技术选型

| 组件 | 选型 | 说明 |
|------|------|------|
| 数据库 | PostgreSQL 16 | 支持 JSONB，成熟稳定 |
| ORM | SQLAlchemy 2.0 | Python 最流行的 ORM |
| 迁移工具 | Alembic | 数据库版本管理 |
| 驱动 | psycopg2-binary | PostgreSQL Python 驱动 |

### 数据库 Schema

```sql
-- analysis_tasks 表
CREATE TABLE analysis_tasks (
    task_id VARCHAR(36) PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    result JSONB,
    decision VARCHAR(10),
    confidence FLOAT,
    error TEXT
);

-- 索引
CREATE INDEX ix_analysis_tasks_symbol ON analysis_tasks(symbol);
CREATE INDEX ix_analysis_tasks_status ON analysis_tasks(status);
CREATE INDEX ix_analysis_tasks_created_at ON analysis_tasks(created_at);
```

### 架构变更

#### 当前架构

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   API 请求   │────▶│ AnalysisService │────▶│  内存 Dict   │
└──────────────┘     └─────────────────┘     └──────────────┘
                              │
                              ▼
                       ┌──────────────┐
                       │ history.json │
                       └──────────────┘
```

#### 目标架构

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   API 请求   │────▶│ AnalysisService │────▶│  PostgreSQL  │
└──────────────┘     └─────────────────┘     └──────────────┘
                              │                     ▲
                              ▼                     │
                       ┌──────────────┐             │
                       │ SQLAlchemy   │─────────────┘
                       └──────────────┘
```

### API 变更

#### 新增端点

```http
DELETE /api/v1/analysis/{task_id}
```

响应：
- `204 No Content` - 删除成功
- `404 Not Found` - 任务不存在

#### 现有端点不变

- `POST /api/v1/analysis/` - 创建分析任务
- `GET /api/v1/analysis/` - 获取任务列表
- `GET /api/v1/analysis/{task_id}` - 获取任务详情

### 部署架构

#### 开发环境（Windows + WSL2）

```
┌─────────────────────────────────────────┐
│              Windows 10/11               │
│  ┌──────────────┐  ┌──────────────────┐ │
│  │ Python 后端   │  │   Streamlit UI   │ │
│  │ Port: 8000   │  │   Port: 8501     │ │
│  └──────────────┘  └──────────────────┘ │
│         │                               │
│         │ localhost:5432                │
│         ▼                               │
│  ┌──────────────────────────────────┐   │
│  │     WSL2 (Ubuntu 22.04)          │   │
│  │  ┌────────────────────────────┐  │   │
│  │  │   PostgreSQL 16            │  │   │
│  │  │   Port: 5432               │  │   │
│  │  └────────────────────────────┘  │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

#### 测试/生产环境（Linux）

```
┌─────────────────────────────────────────┐
│           Linux Server                  │
│  ┌──────────────┐  ┌──────────────────┐ │
│  │ Python 后端   │  │   Streamlit UI   │ │
│  │ Port: 8000   │  │   Port: 8501     │ │
│  └──────────────┘  └──────────────────┘ │
│         │                               │
│         │ localhost:5432                │
│         ▼                               │
│  ┌────────────────────────────┐         │
│  │   PostgreSQL 16            │         │
│  │   Port: 5432               │         │
│  └────────────────────────────┘         │
└─────────────────────────────────────────┘
```

## 实施计划

### 阶段 1: 基础配置（并行）

| 任务 | 描述 | 预计时间 |
|------|------|----------|
| 初始化 OpenSpec | 创建规约目录和文档 | 30分钟 |
| WSL2 安装脚本 | 创建 WSL2 PostgreSQL 安装脚本 | 1小时 |
| Linux 安装脚本 | 创建 Linux PostgreSQL 安装脚本 | 1小时 |
| 更新依赖 | 添加 psycopg2-binary, sqlalchemy, alembic | 15分钟 |

### 阶段 2: 数据库基础

| 任务 | 描述 | 预计时间 | 依赖 |
|------|------|----------|------|
| 数据库配置 | 创建 webapi/config/database.py | 30分钟 | 依赖更新 |
| ORM 模型 | 创建 SQLAlchemy 模型 | 1小时 | 数据库配置 |
| Alembic 初始化 | 初始化迁移工具 | 30分钟 | ORM 模型 |

### 阶段 3: 后端开发

| 任务 | 描述 | 预计时间 | 依赖 |
|------|------|----------|------|
| 重写 AnalysisService | 改用数据库存储 | 2小时 | Alembic 初始化 |
| DELETE 端点 | 添加删除 API | 30分钟 | AnalysisService |

### 阶段 4: 前端 + 配置

| 任务 | 描述 | 预计时间 | 依赖 |
|------|------|----------|------|
| 前端删除逻辑 | 调用 API 删除 | 30分钟 | DELETE 端点 |
| 数据迁移脚本 | JSON 到 PostgreSQL | 1小时 | Alembic 初始化 |
| 环境配置 | 更新 .env.example | 15分钟 | - |

### 阶段 5: 验证

| 任务 | 描述 | 预计时间 | 依赖 |
|------|------|----------|------|
| 功能测试 | 完整 CRUD 流程 | 1小时 | 前端 + 迁移 |
| 性能测试 | 删除 < 100ms 验证 | 30分钟 | 功能测试 |

### 总预计工作量

**约 1-2 天**（考虑并行任务）

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 数据迁移失败 | 低 | 高 | 保留原始 JSON 备份；脚本支持重复运行 |
| 性能不达预期 | 低 | 中 | 添加数据库索引；可进一步优化查询 |
| 环境配置复杂 | 中 | 低 | 提供一键安装脚本；详细配置文档 |
| WSL2 网络问题 | 中 | 低 | 提供配置文档；Windows 可直连 localhost |

## 数据迁移

### 迁移脚本

创建 `scripts/migrate_json_to_postgres.py`：

1. 读取 `web/data/history.json`
2. 连接到 PostgreSQL
3. 将记录插入 `analysis_tasks` 表
4. 处理重复 `task_id`（跳过或更新）
5. 显示迁移进度统计

### 迁移策略

- **保留原始文件**: 迁移后 JSON 文件作为备份保留
- **增量迁移**: 支持多次运行，处理新增数据
- **验证步骤**: 迁移后对比记录数量

## 验收标准

### 功能验收

- [ ] WSL2 中 PostgreSQL 运行正常，Windows 可连接
- [ ] Linux 测试机 PostgreSQL 运行正常
- [ ] 创建分析任务后，数据写入数据库
- [ ] 查看历史列表从数据库读取
- [ ] 删除分析任务后，数据库记录被删除（<100ms）
- [ ] API 重启后，历史数据仍然可访问
- [ ] 现有历史数据已迁移到数据库

### 性能验收

- [ ] 删除操作响应时间 < 100ms
- [ ] 查询操作响应时间 < 500ms
- [ ] 创建操作响应时间 < 500ms

### 跨平台验收

- [ ] Windows + WSL2 环境功能正常
- [ ] Linux 环境功能正常
- [ ] 两个环境使用相同的数据库 Schema

## 相关文档

- [PostgreSQL 选型决策](../decisions/001-use-postgresql.md)
- [WSL2 开发环境决策](../decisions/002-wsl2-for-windows-dev.md)
- [postgres-migration.md](../../.sisyphus/plans/postgres-migration.md) - 详细实施计划

## 决策记录

| 日期 | 事件 | 负责人 |
|------|------|--------|
| 2026-03-26 | RFC 提出 | 开发团队 |
| 2026-03-26 | 评审中 | 开发团队 |

## 附录

### 环境变量配置

```bash
# .env.example
# PostgreSQL 连接（WSL2 和 Linux 相同）
DATABASE_URL=postgresql://trading:password@localhost:5432/trading_db

# WSL2 开发环境说明
# - 使用 localhost:5432 连接 WSL2 中的 PostgreSQL
# - 无需修改 Windows 网络配置

# Linux 测试/生产环境
# - 使用 localhost:5432 连接本地 PostgreSQL
# - 或使用远程数据库地址
```

### 快速启动命令

```bash
# WSL2 环境
sudo bash scripts/setup_wsl_postgres.sh
python scripts/init_database.py
python scripts/migrate_json_to_postgres.py

# Linux 环境
sudo bash scripts/setup_linux_postgres.sh
python scripts/init_database.py
python scripts/migrate_json_to_postgres.py
```
