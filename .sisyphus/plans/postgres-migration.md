# WSL2 + PostgreSQL 数据库架构迁移计划

## TL;DR

> **目标**: 将系统从内存+JSON文件存储迁移到 PostgreSQL 数据库
> 
> **适用环境**: 
> - Windows 开发: WSL2 + PostgreSQL
> - Linux 测试: 原生 PostgreSQL
> 
> **主要改动**:
> - 后端: AnalysisService 改用数据库存储
> - 后端: 新增 DELETE /api/v1/analysis/{task_id} 端点
> - 前端: 删除操作改为调用 API
> - 迁移: JSON文件数据导入 PostgreSQL
> 
> **预计工作量**: Medium (1-2天)
> **并行执行**: YES (数据库配置 + 后端开发 + 前端开发可并行)

---

## Context

### 当前架构问题
- 分析任务存储在内存 Dict (`AnalysisService._tasks`)，API重启后丢失
- 历史记录使用 JSON 文件 (`web/data/history.json`)，高并发有竞态风险
- 删除操作慢：每次删除都要调用 API 获取全部记录

### 目标架构
- **开发环境**: Windows + WSL2 + PostgreSQL
- **测试环境**: Linux + 原生 PostgreSQL
- **存储方式**: PostgreSQL 替代内存+JSON
- **删除方式**: 数据库 DELETE 操作，毫秒级响应

### 技术选型理由
- **PostgreSQL**: 支持结构化查询 + JSONB 非结构化存储
- **SQLAlchemy**: Python 最流行的 ORM，支持异步
- **Alembic**: 数据库迁移工具
- **WSL2**: Windows 开发环境与 Linux 生产环境完全一致

---

## Work Objectives

### Core Objective
将 TradingAgents A-share 系统从内存+JSON文件存储架构迁移到 PostgreSQL 数据库架构，实现数据的持久化存储、高效查询和快速删除。

### Concrete Deliverables
1. PostgreSQL 数据库配置脚本（WSL2 + Linux）
2. SQLAlchemy ORM 模型定义
3. 后端 AnalysisService 改用数据库存储
4. 后端新增 DELETE /api/v1/analysis/{task_id} 端点
5. 前端删除操作调用 API
6. 历史数据迁移脚本（JSON → PostgreSQL）
7. 数据库连接配置（支持环境变量）

### Definition of Done
- [ ] WSL2 中 PostgreSQL 运行正常，Windows 可连接
- [ ] Linux 测试机 PostgreSQL 运行正常
- [ ] 创建分析任务后，数据写入数据库
- [ ] 删除分析任务后，数据库记录被删除（<100ms）
- [ ] API重启后，历史数据仍然可访问
- [ ] 现有历史数据已迁移到数据库

### Must Have
- PostgreSQL 数据库配置（WSL2 + Linux）
- SQLAlchemy 模型定义
- 后端改用数据库存储
- DELETE API 端点
- 前端调用删除 API

### Must NOT Have (Guardrails)
- 不改变现有业务逻辑
- 不删除现有 JSON 文件（保留作为备份）
- 不修改分析引擎核心代码
- 不引入 Redis/MongoDB 等额外组件

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (PostgreSQL)
- **Automated tests**: Tests-after (数据库操作需要手动验证)
- **Framework**: pytest + psycopg2

### QA Policy
每个任务完成后需执行验证脚本，确保数据库操作正常。

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (基础配置 + OpenSpec):
├── Task 1: 初始化 OpenSpec 基础规约
├── Task 2: WSL2 PostgreSQL 安装脚本
├── Task 3: Linux PostgreSQL 安装脚本
└── Task 4: 添加依赖 (requirements.txt)

Wave 1 (数据库基础):
├── Task 5: 创建数据库配置目录和文件
├── Task 6: SQLAlchemy ORM 模型
└── Task 7: Alembic 初始化和 Schema 创建

Wave 2 (后端开发):
├── Task 8: AnalysisService 改用数据库
└── Task 9: DELETE API 端点

Wave 3 (前端 + 配置):
├── Task 10: 前端删除调用 API
├── Task 11: JSON 数据迁移脚本
└── Task 12: 环境配置 (.env.example)

Wave 4 (验证):
├── Task 13: 功能测试 (创建/查询/删除)
└── Task 14: 性能测试 (删除速度)

Wave 5 (收尾):
└── Task 15: OpenSpec 最终更新

Wave FINAL (交付审查):
├── Task F1: 功能验证
├── Task F2: 性能验证
└── Task F3: 跨平台验证
```

### Dependency Matrix
- **1-4**: — — 5
- **5**: 4 — 6
- **6**: 5 — 7
- **7**: 6 — 8, 11, 13, 14
- **8**: 7 — 9, 13
- **9**: 8 — 10, 13
- **10**: 9 — 13
- **12**: (可并行) — 13
- **13**: 7, 9, 10, 12 — 14, F1
- **14**: 13 — F2
- **15**: 1-14 — F3

### Agent Dispatch Summary
- **Wave 0**: writing(1) + quick(3) × 4
- **Wave 1**: quick(1) + unspecified-high(2) × 3
- **Wave 2**: unspecified-high × 2
- **Wave 3**: unspecified-high(2) + quick(1) × 3
- **Wave 4**: unspecified-high × 2
- **Wave 5**: writing × 1
- **Wave FINAL**: unspecified-high(2) + quick(1) × 3

---

## TODOs

- [ ] 1. 初始化 OpenSpec 基础规约

  **What to do**:
  创建 OpenSpec 目录结构和基础规约文件：
  - `.openspec/SPEC.md` - 规约总览和索引
  - `.openspec/conventions.md` - 编码规约
  - `.openspec/decisions/template.md` - ADR 模板
  - `.openspec/decisions/001-use-postgresql.md` - 使用 PostgreSQL 的决策
  - `.openspec/decisions/002-wsl2-for-windows-dev.md` - WSL2 开发环境决策
  - `.openspec/rfcs/001-database-migration.md` - 数据库迁移 RFC
  - `.openspec/archived/README.md` - 归档说明

  **Must NOT do**:
  - 不写具体实现代码
  - 不写业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: []
  - **Reason**: 文档编写，需要清晰的结构和表达

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 0 (与数据库配置并行)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `README.md` - 项目基本信息
  - `webapi/` - 技术架构参考
  - OpenSpec 标准格式参考

  **Acceptance Criteria**:
  - [ ] `.openspec/` 目录结构完整
  - [ ] SPEC.md 包含项目概述和规约索引
  - [ ] decisions/001-use-postgresql.md 记录选型理由
  - [ ] decisions/002-wsl2-for-windows-dev.md 记录开发环境决策
  - [ ] rfcs/001-database-migration.md 包含完整迁移计划
  - [ ] conventions.md 包含编码规范

  **QA Scenarios**:
  ```
  Scenario: OpenSpec 结构完整
    Tool: Bash
    Preconditions: 无
    Steps:
      1. ls -la .openspec/
      2. ls -la .openspec/decisions/
      3. ls -la .openspec/rfcs/
    Expected Result: 所有文件存在，无报错
    Evidence: .sisyphus/evidence/task-1-openspec-structure.txt
  ```

  **Commit**: YES
  - Message: `docs(openspec): Initialize OpenSpec with database migration RFC`
  - Files: `.openspec/`

- [ ] 2. WSL2 PostgreSQL 安装脚本

  **What to do**:
  创建 `scripts/setup_wsl_postgres.sh`，一键安装和配置 WSL2 中的 PostgreSQL：
  - 安装 PostgreSQL 16
  - 创建 trading 用户和 trading_db 数据库
  - 配置监听和访问权限
  - 设置防火墙规则

  **Must NOT do**:
  - 不修改项目代码
  - 不处理数据迁移

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Shell 脚本编写，标准安装流程

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 1, 3, 4 并行)
  - **Parallel Group**: Wave 0 (基础配置)
  - **Blocks**: Task 12 (功能测试)
  - **Blocked By**: None

  **References**:
  - PostgreSQL 16 官方安装文档
  - WSL2 网络配置最佳实践

  **Acceptance Criteria**:
  - [ ] 脚本可在 WSL2 Ubuntu 中直接运行
  - [ ] 运行后 PostgreSQL 服务自动启动
  - [ ] Windows 可通过 localhost:5432 连接
  - [ ] trading 用户和数据库已创建

  **QA Scenarios**:
  ```
  Scenario: WSL2 PostgreSQL 安装成功
    Tool: Bash (在 WSL2 中)
    Preconditions: 全新 WSL2 环境
    Steps:
      1. sudo bash scripts/setup_wsl_postgres.sh
      2. sudo service postgresql status
      3. psql -h localhost -U trading -d trading_db -c "SELECT 1"
    Expected Result: 所有命令成功，无报错
    Evidence: .sisyphus/evidence/task-2-wsl-install.txt
  ```

  **Commit**: YES
  - Message: `chore(scripts): Add WSL2 PostgreSQL setup script`
  - Files: `scripts/setup_wsl_postgres.sh`

- [ ] 3. Linux PostgreSQL 安装脚本

  **What to do**:
  创建 `scripts/setup_linux_postgres.sh`，适用于 Linux 测试/生产环境：
  - 检测 Ubuntu/Debian/CentOS 发行版
  - 安装 PostgreSQL 16
  - 创建 trading 用户和 trading_db 数据库
  - 配置安全访问（仅本地）
  - 可选：创建备份脚本

  **Must NOT do**:
  - 不配置远程访问（安全考虑）
  - 不自动创建 systemd 服务（使用默认）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Shell 脚本编写，多发行版适配

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 1, 2, 4 并行)
  - **Parallel Group**: Wave 0
  - **Blocks**: Task 12
  - **Blocked By**: None

  **References**:
  - PostgreSQL 官方各发行版安装指南

  **Acceptance Criteria**:
  - [ ] 支持 Ubuntu 22.04/24.04
  - [ ] 运行后 PostgreSQL 服务运行
  - [ ] trading 用户和数据库已创建

  **QA Scenarios**:
  ```
  Scenario: Linux PostgreSQL 安装成功
    Tool: Bash (在 Linux 测试机)
    Preconditions: 全新 Ubuntu 环境
    Steps:
      1. sudo bash scripts/setup_linux_postgres.sh
      2. sudo systemctl status postgresql
      3. sudo -u postgres psql -c "\du" | grep trading
    Expected Result: 所有命令成功，trading 用户存在
    Evidence: .sisyphus/evidence/task-3-linux-install.txt
  ```

  **Commit**: YES
  - Message: `chore(scripts): Add Linux PostgreSQL setup script`
  - Files: `scripts/setup_linux_postgres.sh`

- [ ] 4. 更新依赖 requirements.txt

  **What to do**:
  添加数据库相关依赖：
  - `psycopg2-binary>=2.9.9` - PostgreSQL 驱动
  - `sqlalchemy>=2.0.0` - ORM
  - `alembic>=1.13.0` - 数据库迁移工具
  - `asyncpg>=0.29.0` - 异步 PostgreSQL 驱动（可选）

  **Must NOT do**:
  - 不删除现有依赖
  - 不升级其他依赖版本

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: 简单依赖添加

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 1-3 并行)
  - **Parallel Group**: Wave 0
  - **Blocks**: Task 6
  - **Blocked By**: None

  **Acceptance Criteria**:
  - [ ] requirements.txt 包含所有数据库依赖
  - [ ] 依赖版本合理（不冲突）

  **QA Scenarios**:
  ```
  Scenario: 依赖安装成功
    Tool: Bash
    Preconditions: Python 3.11 虚拟环境
    Steps:
      1. pip install -r requirements.txt
      2. python -c "import sqlalchemy; import psycopg2; print('OK')"
    Expected Result: 安装成功，导入无报错
    Evidence: .sisyphus/evidence/task-4-requirements.txt
  ```

  **Commit**: YES
  - Message: `chore(deps): Add PostgreSQL and SQLAlchemy dependencies`
  - Files: `requirements.txt`

- [ ] 5. 创建数据库配置目录和文件

  **What to do**:
  新建 `webapi/config/` 目录并创建 `webapi/config/database.py`：
  - 创建 `webapi/config/__init__.py`（空文件）
  - 创建 `webapi/config/database.py`：
    - 从环境变量读取 DATABASE_URL
    - 创建 SQLAlchemy engine
    - 创建 SessionLocal
    - 提供 get_db() 依赖函数（FastAPI 兼容）

  **Must NOT do**:
  - 不写硬编码密码
  - 不写 ORM 模型（在 models/database.py 中）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: 新建目录和标准配置

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 4)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 6, 7
  - **Blocked By**: Task 4

  **References**:
  - FastAPI + SQLAlchemy 官方文档
  - `webapi/` 现有目录结构

  **Acceptance Criteria**:
  - [ ] `webapi/config/` 目录存在
  - [ ] `webapi/config/__init__.py` 存在
  - [ ] `webapi/config/database.py` 配置正确
  - [ ] 可从环境变量读取 DATABASE_URL

  **QA Scenarios**:
  ```
  Scenario: 数据库配置可导入
    Tool: Python REPL
    Preconditions: DATABASE_URL 设置
    Steps:
      1. from webapi.config.database import engine, SessionLocal
      2. print(engine.url)
    Expected Result: 导入成功，URL 正确
    Evidence: .sisyphus/evidence/task-5-config-import.txt
  ```

  **Commit**: YES
  - Message: `feat(config): Add database configuration module`
  - Files: `webapi/config/__init__.py`, `webapi/config/database.py`

- [ ] 6. 创建 SQLAlchemy ORM 模型

  **What to do**:
  创建 `webapi/models/database.py`：
  - AnalysisTask 模型（映射 analysis_tasks 表）
  - 字段：task_id, symbol, status, created_at, updated_at, completed_at, result (JSONB), decision, confidence
  - 索引：symbol, status, created_at
  - 模型方法：to_dict(), from_dict()

  **Must NOT do**:
  - 不写业务逻辑
  - 不创建表（在 Task 7 中）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 需要理解现有数据结构

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 5)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7, 9
  - **Blocked By**: Task 5

  **References**:
  - `webapi/models/analysis.py` - 现有 Pydantic 模型
  - `webapi/config/database.py` - Base 导入
  - SQLAlchemy 2.0 文档
  - PostgreSQL JSONB 最佳实践

  **Acceptance Criteria**:
  - [ ] AnalysisTask 模型完整定义
  - [ ] 字段类型正确（包含 JSONB）
  - [ ] 索引配置合理
  - [ ] 可从 Base 导入

  **QA Scenarios**:
  ```
  Scenario: 模型可导入
    Tool: Python REPL
    Preconditions: 无
    Steps:
      1. from webapi.models.database import Base, AnalysisTask
      2. print(AnalysisTask.__table__.columns.keys())
    Expected Result: 导入成功，显示所有字段
    Evidence: .sisyphus/evidence/task-6-model-import.txt
  ```

  **Commit**: YES
  - Message: `feat(models): Add SQLAlchemy ORM models for PostgreSQL`
  - Files: `webapi/models/database.py`

- [ ] 7. Alembic 初始化和 Schema 创建

  **What to do**:
  初始化 Alembic 并创建数据库表：
  - 运行 `alembic init alembic` 初始化
  - 配置 `alembic.ini` 和 `alembic/env.py`
  - 创建初始 migration：`alembic revision --autogenerate -m "Initial schema"`
  - 创建 `scripts/init_database.py` 一键初始化脚本
  - 脚本功能：创建表 + 验证连接

  **Must NOT do**:
  - 不导入数据（在 Task 12 中）
  - 不删除现有数据

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 数据库迁移工具配置

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 6)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8, 10, 13, 14
  - **Blocked By**: Task 6

  **References**:
  - Alembic 官方文档
  - `webapi/config/database.py`
  - `webapi/models/database.py`

  **Acceptance Criteria**:
  - [ ] Alembic 初始化完成
  - [ ] 初始 migration 文件生成
  - [ ] 运行 migration 后表创建成功
  - [ ] `scripts/init_database.py` 可用

  **QA Scenarios**:
  ```
  Scenario: 数据库表创建成功
    Tool: Bash + psql
    Preconditions: PostgreSQL 运行，配置正确
    Steps:
      1. alembic upgrade head
      2. psql -d trading_db -c "\dt"
    Expected Result: analysis_tasks 表存在
    Evidence: .sisyphus/evidence/task-7-schema-create.txt
  ```

  **Commit**: YES
  - Message: `feat(db): Add Alembic migrations and init script`
  - Files: `alembic/`, `alembic.ini`, `scripts/init_database.py`

- [ ] 8. 重写 AnalysisService 使用数据库

  **What to do**:
  修改 `webapi/services/analysis_service.py`：
  - 改用 SQLAlchemy 替代内存 Dict
  - create_task(): 写入数据库
  - get_task(): 从数据库查询
  - list_tasks(): 数据库查询（支持过滤）
  - run_analysis(): 更新数据库状态
  - 删除方法：添加 delete_task()（真正从数据库删除）

  **Must NOT do**:
  - 不改变业务逻辑（分析流程）
  - 不修改 API 接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 核心业务逻辑修改

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 10, 13
  - **Blocked By**: Task 7

  **References**:
  - `webapi/services/analysis_service.py` 现有实现
  - `webapi/models/database.py`
  - `webapi/config/database.py`
  - SQLAlchemy CRUD 最佳实践

  **Acceptance Criteria**:
  - [ ] 所有方法改用数据库存储
  - [ ] API 接口保持不变
  - [ ] 单元测试通过（如果有）

  **QA Scenarios**:
  ```
  Scenario: CRUD 操作正常
    Tool: Python REPL
    Preconditions: PostgreSQL 运行，表已创建
    Steps:
      1. task = analysis_service.create_task(request)
      2. fetched = analysis_service.get_task(task.task_id)
      3. analysis_service.delete_task(task.task_id)
      4. deleted = analysis_service.get_task(task.task_id)
    Expected Result: 创建成功，查询返回，删除后查不到
    Evidence: .sisyphus/evidence/task-8-service-crud.txt
  ```

  **Commit**: YES
  - Message: `refactor(service): Migrate AnalysisService to PostgreSQL`
  - Files: `webapi/services/analysis_service.py`

- [ ] 9. 添加 DELETE API 端点

  **What to do**:
  修改 `webapi/routers/analysis.py`：
  - 添加 `@router.delete("/{task_id}")` 端点
  - 调用 analysis_service.delete_task()
  - 返回 204 No Content 或 404 Not Found

  **Must NOT do**:
  - 不改其他端点
  - 不添加权限验证（当前项目无认证）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: FastAPI 路由开发

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 11
  - **Blocked By**: Task 8

  **References**:
  - FastAPI DELETE 端点最佳实践
  - HTTP 状态码规范

  **Acceptance Criteria**:
  - [ ] DELETE /api/v1/analysis/{task_id} 可用
  - [ ] 存在返回 204
  - [ ] 不存在返回 404

  **QA Scenarios**:
  ```
  Scenario: DELETE API 工作正常
    Tool: Bash (curl)
    Preconditions: API 运行，有测试任务
    Steps:
      1. curl -X DELETE http://localhost:8000/api/v1/analysis/{task_id}
      2. curl http://localhost:8000/api/v1/analysis/{task_id}
    Expected Result: 删除返回 204，查询返回 404
    Evidence: .sisyphus/evidence/task-9-delete-api.txt
  ```

  **Commit**: YES
  - Message: `feat(api): Add DELETE /analysis/{task_id} endpoint`
  - Files: `webapi/routers/analysis.py`

- [ ] 10. 更新前端删除逻辑

  **What to do**:
  修改 `web/components/history_manager.py`：
  - delete_from_history() 改为调用 API
  - 删除成功后刷新列表
  - 处理错误情况（显示错误提示）

  **Must NOT do**:
  - 不改其他 UI 逻辑
  - 不删除本地文件逻辑（保留回退）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 前端 API 调用修改

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 9)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 13
  - **Blocked By**: Task 9

  **References**:
  - `web/components/history_manager.py` 现有删除逻辑
  - requests 库 DELETE 方法

  **Acceptance Criteria**:
  - [ ] 点击删除按钮调用 API
  - [ ] 删除成功后刷新列表
  - [ ] 删除速度 < 1秒

  **QA Scenarios**:
  ```
  Scenario: 前端删除快速响应
    Tool: Playwright / 手动测试
    Preconditions: Web UI 运行
    Steps:
      1. 打开历史记录页面
      2. 点击某条记录的删除按钮
      3. 计时删除响应时间
    Expected Result: 删除完成 < 1秒，记录从列表消失
    Evidence: .sisyphus/evidence/task-10-frontend-delete.png
  ```

  **Commit**: YES
  - Message: `feat(ui): Update delete to use API instead of local file`
  - Files: `web/components/history_manager.py`

- [ ] 11. 创建 JSON 数据迁移脚本

  **What to do**:
  创建 `scripts/migrate_json_to_postgres.py`：
  - 读取 `web/data/history.json`
  - 连接到 PostgreSQL
  - 将记录插入 analysis_tasks 表
  - 处理重复 task_id（跳过或更新）
  - 显示迁移进度

  **Must NOT do**:
  - 不删除原始 JSON 文件（备份）
  - 不修改源数据

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 数据迁移脚本开发

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 7)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: Task 7

  **References**:
  - `web/data/history.json` 结构
  - SQLAlchemy 批量插入

  **Acceptance Criteria**:
  - [ ] 脚本可读取 JSON 文件
  - [ ] 数据正确插入 PostgreSQL
  - [ ] 显示迁移统计（成功/失败数量）

  **QA Scenarios**:
  ```
  Scenario: 数据迁移成功
    Tool: Bash
    Preconditions: history.json 存在且有数据
    Steps:
      1. python scripts/migrate_json_to_postgres.py
      2. psql -c "SELECT COUNT(*) FROM analysis_tasks"
    Expected Result: 迁移成功，数据库记录数与 JSON 一致
    Evidence: .sisyphus/evidence/task-11-migration.txt
  ```

  **Commit**: YES
  - Message: `feat(scripts): Add JSON to PostgreSQL migration script`
  - Files: `scripts/migrate_json_to_postgres.py`

- [ ] 12. 更新环境配置示例

  **What to do**:
  更新 `.env.example`：
  - 添加 DATABASE_URL 示例
  - 保留现有 API key 配置
  - 添加注释说明 WSL2 和 Linux 的区别

  **Must NOT do**:
  - 不提交真实 `.env` 文件
  - 不删除现有配置项

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: 文档更新

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 10-11)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 13
  - **Blocked By**: None

  **Acceptance Criteria**:
  - [ ] DATABASE_URL 示例正确
  - [ ] 包含 WSL2 和 Linux 配置说明

  **QA Scenarios**:
  ```
  Scenario: 配置示例有效
    Tool: Bash
    Preconditions: PostgreSQL 运行
    Steps:
      1. cp .env.example .env
      2. 编辑 DATABASE_URL
      3. python -c "from webapi.config.database import engine; print('OK')"
    Expected Result: 配置加载成功
    Evidence: .sisyphus/evidence/task-12-env-config.txt
  ```

  **Commit**: YES
  - Message: `docs(config): Update .env.example with DATABASE_URL`
  - Files: `.env.example`

- [ ] 13. 功能测试

  **What to do**:
  端到端功能验证：
  - 创建分析任务 → 数据写入数据库
  - 查看历史列表 → 从数据库读取
  - 删除分析任务 → 从数据库删除
  - API重启 → 历史数据仍在

  **Must NOT do**:
  - 不写自动化测试（当前项目无测试框架）
  - 不测试业务分析逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 端到端验证

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 10, 12)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F3
  - **Blocked By**: Task 10, 12

  **References**:
  - 现有 API 端点文档
  - Streamlit 测试流程

  **Acceptance Criteria**:
  - [ ] 创建任务后数据库有记录
  - [ ] 历史列表显示正确
  - [ ] 删除后数据库记录消失
  - [ ] API重启后数据不丢失

  **QA Scenarios**:
  ```
  Scenario: 完整功能流程
    Tool: Bash + curl + psql
    Preconditions: 完整环境运行
    Steps:
      1. curl POST 创建任务
      2. psql 查询确认写入
      3. curl GET 列表确认读取
      4. curl DELETE 删除任务
      5. psql 查询确认删除
      6. 重启 API 服务
      7. curl GET 列表确认数据仍在
    Expected Result: 所有步骤成功
    Evidence: .sisyphus/evidence/task-13-e2e-test.txt
  ```

  **Commit**: NO (测试不产生代码变更)

- [ ] 14. 性能测试

  **What to do**:
  验证删除操作性能：
  - 删除操作响应时间 < 100ms
  - 查询操作响应时间 < 500ms
  - 与之前 JSON 文件方式对比

  **Must NOT do**:
  - 不做压力测试（当前规模不需要）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 性能验证

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖 Task 13)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F3
  - **Blocked By**: Task 13

  **Acceptance Criteria**:
  - [ ] 删除操作 < 100ms
  - [ ] 查询操作 < 500ms

  **QA Scenarios**:
  ```
  Scenario: 删除性能达标
    Tool: Bash (time + curl)
    Preconditions: 有测试数据
    Steps:
      1. time curl -X DELETE http://localhost:8000/api/v1/analysis/{id}
    Expected Result: 耗时 < 100ms
    Evidence: .sisyphus/evidence/task-14-performance.txt
  ```

  **Commit**: NO (测试不产生代码变更)

- [ ] 15. OpenSpec 最终更新

  **What to do**:
  更新 OpenSpec，标记 RFC 为已接受：
  - 更新 `rfcs/001-database-migration.md` 状态为 `Accepted`
  - 添加实施总结到 `decisions/001-use-postgresql.md`
  - 更新 `SPEC.md` 最近变更记录

  **Must NOT do**:
  - 不删除 RFC 文件
  - 不修改其他决策

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: []
  - **Reason**: 文档更新

  **Parallelization**:
  - **Can Run In Parallel**: NO (依赖所有实施任务)
  - **Parallel Group**: Wave Final
  - **Blocks**: F1-F3
  - **Blocked By**: Task 1-14

  **Acceptance Criteria**:
  - [ ] RFC 状态更新为 Accepted
  - [ ] 决策文档包含实施总结
  - [ ] SPEC.md 最新变更记录更新

  **QA Scenarios**:
  ```
  Scenario: OpenSpec 已更新
    Tool: Bash
    Preconditions: 所有任务完成
    Steps:
      1. grep -r "Status: Accepted" rfcs/
      2. cat SPEC.md | head -50
    Expected Result: RFC 状态正确，SPEC 包含最新变更
    Evidence: .sisyphus/evidence/task-15-openspec.txt
  ```

  **Commit**: YES
  - Message: `docs(openspec): Mark RFC-001 as Accepted and update decisions`
  - Files: `.openspec/`

---

## Final Verification Wave

- [ ] F1. **功能验证** — `unspecified-high`
  
  **What to verify**:
  验证所有 CRUD 操作正常，数据持久化
  
  **QA Scenarios**:
  ```
  Scenario: F1 功能验证通过
    Tool: Bash + psql
    Preconditions: 完整环境运行
    Steps:
      1. psql -d trading_db -c "SELECT COUNT(*) FROM analysis_tasks"  (确认表存在)
      2. curl -s http://localhost:8000/api/v1/analysis/ | jq '. | length'  (API 返回列表)
      3. 打开 http://localhost:8501 点击历史记录  (UI 正常显示)
      4. 删除一条记录，刷新页面  (删除持久化)
    Expected Result: 所有步骤成功，无报错
    Evidence: .sisyphus/evidence/F1-functional.txt
  ```
  
- [ ] F2. **性能验证** — `unspecified-high`
  
  **What to verify**:
  验证删除和查询性能达标
  
  **QA Scenarios**:
  ```
  Scenario: F2 性能验证通过
    Tool: Bash (time command)
    Preconditions: 有 10+ 条测试数据
    Steps:
      1. time curl -s http://localhost:8000/api/v1/analysis/ > /dev/null  (查询时间)
      2. time curl -s -X DELETE http://localhost:8000/api/v1/analysis/{id} > /dev/null  (删除时间)
    Expected Result: 查询 < 500ms，删除 < 100ms
    Evidence: .sisyphus/evidence/F2-performance.txt
  ```
  删除操作 < 100ms，查询操作 < 500ms

- [ ] F3. **跨平台验证** — `quick`
  
  **What to verify**:
  Windows(WSL2) 和 Linux 都能正常运行
  
  **QA Scenarios**:
  ```
  Scenario: F3 跨平台验证通过
    Tool: Bash + ssh
    Preconditions: WSL2 和 Linux 测试机都部署好
    Steps:
      1. Windows: curl http://localhost:8000/api/v1/analysis/health  (或健康检查端点)
      2. Linux: ssh user@linux-test "curl http://localhost:8000/api/v1/analysis/"
      3. 两边都创建、查询、删除一条记录
    Expected Result: 两个环境功能完全一致
    Evidence: .sisyphus/evidence/F3-cross-platform.txt
  ```

---

## Commit Strategy

### Wave 1
```
db-setup: Add PostgreSQL setup scripts for WSL2 and Linux
- Add scripts/setup_wsl_postgres.sh
- Add scripts/setup_linux_postgres.sh
- Update requirements.txt with psycopg2-binary, sqlalchemy, alembic
```

### Wave 2
```
db-models: Add SQLAlchemy ORM models
- Add webapi/models/database.py with AnalysisTask model
- Add webapi/config/database.py with engine/session setup
```

### Wave 3
```
db-service: Migrate AnalysisService to PostgreSQL
- Rewrite AnalysisService to use database
- Add DELETE /api/v1/analysis/{task_id} endpoint
```

### Wave 4
```
db-frontend: Update frontend to use delete API
- Update web/components/history_manager.py
- Add data migration script
```

---

## Success Criteria

### 功能验证
```bash
# 测试创建
curl -X POST http://localhost:8000/api/v1/analysis/ \
  -H "Content-Type: application/json" \
  -d '{"symbol": "000001", "analysts": ["market"]}'

# 测试查询
curl http://localhost:8000/api/v1/analysis/

# 测试删除
curl -X DELETE http://localhost:8000/api/v1/analysis/{task_id}
```

### 性能验证
```bash
# 删除操作应 < 100ms
time curl -X DELETE http://localhost:8000/api/v1/analysis/{task_id}
```

### 跨平台验证
- [ ] Windows + WSL2: 功能正常
- [ ] Linux: 功能正常
- [ ] API重启后数据不丢失

---

## Risk Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 数据迁移失败 | 低 | 高 | 保留原始 JSON 备份 |
| 性能下降 | 低 | 中 | 添加索引优化 |
| 环境配置复杂 | 中 | 低 | 提供一键安装脚本 |
| WSL2 连接问题 | 中 | 低 | 提供配置文档 |
