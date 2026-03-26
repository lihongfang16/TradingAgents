# ADR-001: 使用 PostgreSQL 作为主要数据库

## 标题

使用 PostgreSQL 替代内存+JSON文件存储

## 状态

- [x] Proposed
- [x] Accepted
- [ ] Implemented
- [ ] Rejected
- [ ] Deprecated

## 背景

当前 TradingAgents A-share 系统使用以下存储方案：
- 分析任务存储在内存 Dict (`AnalysisService._tasks`)，API 重启后数据丢失
- 历史记录使用 JSON 文件 (`web/data/history.json`)，高并发有竞态风险
- 删除操作需要遍历整个 JSON 文件，响应缓慢

随着系统规模扩大，这种架构面临以下问题：
1. **数据持久化**: API 重启导致任务状态丢失
2. **并发安全**: JSON 文件写入存在竞态条件
3. **查询性能**: 大量数据时查询效率低下
4. **删除性能**: 每次删除需要读写整个文件

## 决策

我们决定 **使用 PostgreSQL 作为主要数据存储**，替代现有的内存+JSON文件架构。

## 备选方案

### 备选方案 A: MongoDB

- **描述**: 使用 MongoDB 作为文档数据库
- **优点**:
  - 原生 JSON 支持，与当前数据结构兼容
  - 水平扩展能力强
  - 查询灵活
- **缺点**:
  - 需要额外安装和学习成本
  - 事务支持相对较弱
  - 与 SQLAlchemy 集成不如 PostgreSQL 成熟
- **结论**: 拒绝。项目团队更熟悉 SQL 数据库，PostgreSQL 的事务支持更好。

### 备选方案 B: SQLite

- **描述**: 使用 SQLite 作为嵌入式数据库
- **优点**:
  - 零配置，开箱即用
  - 单文件存储，易于备份
  - 无需单独的数据库服务
- **缺点**:
  - 并发写入性能差
  - 不适合高并发场景
  - 缺乏高级功能（如 JSONB）
- **结论**: 拒绝。考虑到未来可能的并发需求，SQLite 无法满足。

### 备选方案 C: 保持现状（内存+JSON）

- **描述**: 继续使用现有的存储方案
- **优点**:
  - 无需改动
  - 实现简单
- **缺点**:
  - 数据丢失风险
  - 性能问题
  - 无法支持多实例部署
- **结论**: 拒绝。当前方案已经制约了系统发展。

### 备选方案 D: PostgreSQL（选定）

- **描述**: 使用 PostgreSQL 关系型数据库
- **优点**:
  - 成熟稳定，广泛使用
  - 强大的 JSONB 支持（结构化+非结构化数据）
  - 完整的事务支持
  - 与 SQLAlchemy 集成良好
  - 支持复杂查询和索引
- **缺点**:
  - 需要单独的数据库服务
  - Windows 开发需要 WSL2 配置
- **结论**: 接受。PostgreSQL 在可靠性、功能性和团队熟悉度上都是最佳选择。

## 影响

### 正面影响
- 数据持久化存储，API 重启不丢失
- 支持并发访问，无竞态条件
- 删除操作从秒级降至毫秒级
- 支持复杂查询和数据分析
- 为未来多实例部署奠定基础

### 负面影响
- 增加系统复杂度（需要管理数据库服务）
- Windows 开发需要配置 WSL2
- 需要编写数据迁移脚本

### 需要采取的行动
- [x] 编写 PostgreSQL 安装脚本（WSL2 + Linux）
- [ ] 创建 SQLAlchemy ORM 模型
- [ ] 配置 Alembic 迁移工具
- [ ] 重写 AnalysisService 使用数据库
- [ ] 编写 JSON 数据迁移脚本
- [ ] 更新环境配置文档

## 相关文档

- [RFC-001: 数据库迁移计划](../rfcs/001-database-migration.md)
- [WSL2 开发环境决策](./002-wsl2-for-windows-dev.md)

## 技术选型详情

### 核心组件

| 组件 | 选型 | 版本 | 说明 |
|------|------|------|------|
| 数据库 | PostgreSQL | 16+ | 主要数据存储 |
| ORM | SQLAlchemy | 2.0+ | Python ORM 框架 |
| 迁移工具 | Alembic | 1.13+ | 数据库版本管理 |
| 驱动 | psycopg2-binary | 2.9+ | PostgreSQL Python 驱动 |

### 数据库 Schema 概览

```sql
-- analysis_tasks 表
CREATE TABLE analysis_tasks (
    task_id VARCHAR(36) PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    result JSONB,
    decision VARCHAR(10),
    confidence FLOAT
);

-- 索引
CREATE INDEX ix_analysis_tasks_symbol ON analysis_tasks(symbol);
CREATE INDEX ix_analysis_tasks_status ON analysis_tasks(status);
CREATE INDEX ix_analysis_tasks_created_at ON analysis_tasks(created_at);
```

## 决策记录

| 日期 | 事件 | 负责人 |
|------|------|--------|
| 2026-03-26 | 决策提出 | 开发团队 |
| 2026-03-26 | 决策接受 | 开发团队 |
| 2026-03-26 | 实施中 | 开发团队 |
