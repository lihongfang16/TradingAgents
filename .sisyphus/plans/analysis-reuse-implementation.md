# 分析结果复用功能实现计划

> **Version**: 2.0 (Updated per Momus Review)  
> **Review Date**: 2026-03-31  
> **Status**: REVISED (Ready for Implementation)

---

## TL;DR

> **目标**: 实现分析师结果复用机制，减少重复LLM调用，降低成本
>  
> **Momus审查更新**:
> - ✅ 添加 `analysis_date` 列支持多日期缓存
> - ✅ 指定 PostgreSQL Advisory Locks 作为并发控制机制
> - ✅ 详细说明 LangGraph 状态注入机制（Propagator后注入）
> - ✅ 添加部分缓存命中处理策略
> - ✅ 添加事件驱动失效机制（涨跌停/财报等）
> - ✅ 添加 `cache_version` + `lock_session_id` 支持乐观锁
> 
> **核心策略**: 以Analyst级别缓存4个分析报告，差异化TTL（市场15分钟/情绪2小时/新闻2小时/基本面24小时），存储于PostgreSQL
> 
> **技术方案**: 新增`analyst_report_cache`表 + `AnalysisCacheService`服务层 + `AnalysisRunner`集成
> 
> **关键特性**: 
> - 请求级去重（并发控制）
> - 用户可强制刷新（跳过TTL）
> - 仅缓存LLM report，不缓存原始数据
> 
> **预估工作量**: 中等（3-5个任务）

---

## Context

### 原始需求
用户希望在实时监控中复用历史分析结果，实现"部分复用+实盘分析合并"的方案。具体而言：
- 四个Analyst（market/sentiment/news/fundamentals）的结果可复用
- 下游（Researcher/Risk/Trader/Portfolio Manager）必须重算
- 需要根据数据特性设置不同的TTL

### 访谈确认的需求

| 决策项 | 用户选择 |
|--------|----------|
| TTL策略 | 差异化：market(15m)/sentiment(2h)/news(2h)/fundamentals(24h) |
| 存储位置 | PostgreSQL数据库 |
| 刷新机制 | 定时刷新 + 用户强制刷新 |
| 缓存粒度 | Analyst级别 |
| 并发控制 | 请求级去重 |
| 数据范围 | 仅LLM report，不含原始数据 |

### 技术约束
- 遵循"Upstream Isolation Principle"：不修改上游分析引擎核心代码
- 使用现有PostgreSQL，不引入Redis/MongoDB
- 与现有`AnalysisService`/`AnalysisRunner`架构兼容

---

## Work Objectives

### Core Objective
实现Analyst级别分析结果缓存系统，支持差异化TTL、并发去重、用户强制刷新，降低30-50%的LLM调用成本。

### Concrete Deliverables
1. 数据库表 `analyst_report_cache`（Alembic迁移）
2. `AnalysisCacheService` 服务层（CRUD + TTL检查 + 并发锁）
3. `CachedAnalysisRunner`（包装AnalysisRunner，添加缓存逻辑）
4. API端点：GET /cache/status, POST /cache/refresh/{symbol}
5. UI更新：分析按钮添加"强制刷新"选项

### Definition of Done
- [ ] 同一symbol在TTL内第二次分析，复用缓存的analyst reports
- [ ] 用户可通过UI强制刷新，忽略TTL
- [ ] 并发请求同一symbol时，只有一个实际执行LLM调用
- [ ] 缓存命中率可监控（通过API或日志）

### Must Have
- 4个analyst的独立缓存
- 差异化TTL配置（可调整）
- PostgreSQL持久化
- 请求级去重（防止并发重复分析）

### Must NOT Have (Guardrails)
- 不缓存Researcher/Risk/Trader/Portfolio结果（必须重算）
- 不缓存原始股价/新闻数据（只存LLM report）
- 不修改`tradingagents/`核心代码（只修改包装层）
- 不引入Redis等额外存储

---

## Database Schema (Updated per Momus Review)

```sql
CREATE TABLE analyst_report_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    analyst_type VARCHAR(20) NOT NULL,
    analysis_date DATE NOT NULL,              -- NEW: 支持多日期缓存
    report_content TEXT NOT NULL,
    cache_version INT DEFAULT 1,              -- NEW: 乐观锁/版本控制
    lock_session_id VARCHAR(100),             -- NEW: 并发锁会话标识
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    is_valid BOOLEAN DEFAULT TRUE
);

-- 复合索引：支持(symbol, analyst_type, date)查询
CREATE INDEX ix_analyst_report_cache_symbol_analyst_type_date 
    ON analyst_report_cache(symbol, analyst_type, analysis_date);

-- 索引：支持会话锁清理
CREATE INDEX ix_analyst_report_cache_lock_session 
    ON analyst_report_cache(lock_session_id)
    WHERE is_valid = TRUE;

-- 索引：支持过期缓存清理
CREATE INDEX ix_analyst_report_cache_expires 
    ON analyst_report_cache(expires_at)
    WHERE is_valid = TRUE;
```

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES（pytest已配置）
- **Automated tests**: YES (Tests after)
- **Framework**: pytest
- **Agent-Executed QA**: 每个任务包含具体的QA场景

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation - Database + Service):
├── Task 1: Create analyst_report_cache table (Alembic migration)
└── Task 2: Implement AnalysisCacheService (CRUD, TTL, locking)

Wave 2 (Integration - Runner + API):
├── Task 3: Create CachedAnalysisRunner (wrap AnalysisRunner with cache)
└── Task 4: Add API endpoints for cache management

Wave 3 (UI + Polish):
├── Task 5: Add "强制刷新" UI control
└── Task 6: Add cache metrics/monitoring

Wave FINAL (Verification):
├── Task F1: Integration test - verify cache hit/miss
├── Task F2: Concurrency test - verify deduplication
└── Task F3: Oracle review - architecture compliance
```

---

## TODOs

- [ ] 1. 创建 analyst_report_cache 数据库表 (Alembic迁移)

  **What to do**:
  - 创建Alembic迁移文件，添加`analyst_report_cache`表
  - 字段（Momus更新）：id, symbol, analyst_type, **analysis_date**, report_content, **cache_version**, **lock_session_id**, created_at, expires_at, is_valid
  - 添加复合索引：**(symbol, analyst_type, analysis_date)**（支持多日期缓存）
  - 添加索引：lock_session_id（会话锁清理）、expires_at（过期缓存清理）
  - 默认值：TTL根据analyst_type计算（market=15m, sentiment=2h, news=2h, fundamentals=24h）

  **Must NOT do**:
  - 不修改现有analysis_tasks表结构
  - 不删除或修改已有迁移文件

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - 原因：数据库迁移是标准操作，不需要特殊技能

  **Parallelization**:
  - **Can Run In Parallel**: NO（必须先完成才能做Task 2）
  - **Blocks**: Task 2, Task 3
  - **Blocked By**: None

  **References**:
  - `alembic/versions/2c3d4e5f6g7h_add_price_and_error_message_to_watchlist_analysis.py` - 参考迁移文件结构
  - `webapi/models/database.py` - 现有模型定义

  **Acceptance Criteria**:
  - [ ] `alembic upgrade head` 成功执行
  - [ ] `alembic downgrade -1` 可回滚
  - [ ] PostgreSQL中表结构正确

  **QA Scenarios**:

  ```
  Scenario: 迁移成功执行
    Tool: Bash (psql)
    Steps:
      1. alembic upgrade head
      2. psql -d tradingagents -c "\dt analyst_report_cache"
    Expected Result: 表存在，列正确
    Evidence: .sisyphus/evidence/task-1-migration-success.txt

  Scenario: 回滚成功
    Tool: Bash
    Steps:
      1. alembic downgrade -1
      2. psql -d tradingagents -c "\dt analyst_report_cache"
    Expected Result: 表不存在（已回滚）
    Evidence: .sisyphus/evidence/task-1-rollback-success.txt
  ```

  **Commit**: YES
  - Message: `feat(db): add analyst_report_cache table with TTL support`
  - Files: `alembic/versions/xxxx_add_analyst_report_cache.py`

---

- [ ] 2. 实现 AnalysisCacheService 服务层

  **What to do**:
  - 创建 `webapi/services/analysis_cache_service.py`
  - 实现CRUD方法（参考Updated DB Schema）：
    - `get_cached_report(symbol, analyst_type, analysis_date)` - 获取缓存，检查TTL和analysis_date
    - `set_cached_report(symbol, analyst_type, analysis_date, report, ttl_seconds, cache_version)` - 设置缓存
    - `invalidate_cache(symbol, analyst_type=None, analysis_date=None)` - 使缓存失效
    - `is_cache_valid(symbol, analyst_type, analysis_date)` - 检查缓存是否有效（TTL + is_valid）
  - **实现并发锁机制（PostgreSQL Advisory Locks）**：
    - `acquire_lock(symbol, analyst_type)` - 获取pg_advisory_lock，使用hash(f"{symbol}:{analyst_type}")作为lock_id
    - `release_lock(symbol, analyst_type)` - 释放pg_advisory_unlock
    - `is_locked(symbol, analyst_type)` - 检查是否有活跃锁
    - **锁粒度**：(symbol, analyst_type)级别，允许同symbol不同analyst并发
  - **实现事件驱动失效**（新增）：
    - `invalidate_on_event(event_type, symbol)` - 涨跌停/财报等事件触发缓存失效
    - 支持事件：'trading_halt', 'limit_up', 'limit_down', 'earnings_report', 'major_news'
    - 不同事件失效不同analyst：limit_up→market/sentiment, earnings→fundamentals

  **Must NOT do**:
  - 不直接调用LLM（只操作数据库）
  - 不修改现有AnalysisService
  - 不使用Redis或应用级锁（必须使用PostgreSQL advisory locks）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - 原因：需要处理并发和锁逻辑

  **Parallelization**:
  - **Can Run In Parallel**: NO（依赖Task 1）
  - **Blocks**: Task 3
  - **Blocked By**: Task 1

  **References**:
  - `webapi/services/analysis_service.py` - 服务模式参考
  - `webapi/models/database.py` - ORM模型

  **Acceptance Criteria**:
  - [ ] 所有方法有类型注解和docstring
  - [ ] 单元测试覆盖：get/set/invalidate/is_valid
  - [ ] **PostgreSQL Advisory Locks测试通过**（验证pg_advisory_lock/unlock调用）
  - [ ] 事件驱动失效测试：模拟limit_up事件后market缓存失效

  **QA Scenarios**:

  ```
  Scenario: 缓存CRUD正常
    Tool: Bash (pytest)
    Steps:
      1. pytest tests/unit/test_cache_service.py -v
    Expected Result: 所有测试通过
    Evidence: .sisyphus/evidence/task-2-unit-tests.txt

  Scenario: PostgreSQL Advisory Locks生效
    Tool: Bash (python script)
    Steps:
      1. python tests/concurrency/test_pg_advisory_locks.py
    Expected Result: 同一(symbol, analyst)并发请求时，pg_advisory_lock成功串行化；不同analyst可并发
    Evidence: .sisyphus/evidence/task-2-pg-locks.txt

  Scenario: 事件驱动缓存失效
    Tool: Bash (python)
    Steps:
      1. 缓存000001.SZ的market report（TTL=24h）
      2. 调用invalidate_on_event('limit_up', '000001.SZ')
      3. 查询缓存状态
    Expected Result: market/sentiment缓存is_valid=False；fundamentals/news仍有效
    Evidence: .sisyphus/evidence/task-2-event-invalidation.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): implement AnalysisCacheService with TTL and locking`
  - Files: `webapi/services/analysis_cache_service.py`, `tests/unit/test_cache_service.py`

---

- [ ] 3. 创建 CachedAnalysisRunner (包装器)

  **What to do**:
  - 创建 `tradingagents/core/cached_analysis_runner.py`
  - 实现 `CachedAnalysisRunner` 类，包装现有的 `AnalysisRunner`
  - **LangGraph状态注入机制**（Momus关键反馈）：
    1. `run(symbol, date, force_refresh=False)` 接收analysis_date参数
    2. 使用`Propagator.create_initial_state(symbol, date)`创建初始state
    3. **检查4个analyst的缓存**（对于该symbol+date）：
       - 调用`AnalysisCacheService.get_cached_report(symbol, analyst, date)`
       - 返回有效缓存的analyst列表`cached_analysts`
    4. **注入缓存到初始state**（关键点）：
       ```python
       for analyst in cached_analysts:
           state[f"{analyst}_report"] = cached_reports[analyst]
       ```
    5. **执行LangGraph**：`graph.invoke(state)`
       - LangGraph节点会检查state字段：如果`market_report`已存在，market_analyst_node不会调用LLM
       - 未缓存的analyst节点正常执行，自动填充state
    6. **保存新结果到缓存**：对于未缓存或重新计算的analyst，调用`set_cached_report()`
  - **部分缓存命中处理**（新增）：
    - 场景：2个analyst缓存有效，2个失效
    - 行为：从DB读取2个缓存→注入state→LangGraph执行（跳过的节点不调用LLM）→保存2个新结果
    - 下游Researcher/Risk/Trader/Portfolio接收完整的4个report
  - 支持 `force_refresh` 参数（force_refresh=True时跳过缓存检查，直接执行完整流程）

  **Must NOT do**:
  - 不修改 `AnalysisRunner` 类本身（遵循Upstream Isolation）
  - 不修改 `TradingAgentsGraph` 或 LangGraph 节点/边结构
  - 不直接调用`propagate()`内部（只包装入口和出口）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - 原因：需要深入理解LangGraph状态流，在正确时机注入缓存；必须验证下游节点在预填充state下行为正确

  **Parallelization**:
  - **Can Run In Parallel**: NO（依赖Task 2）
  - **Blocks**: Task 4
  - **Blocked By**: Task 2

  **References**:
  - `tradingagents/core/analysis_runner.py` - 现有AnalysisRunner（run()方法调用propagate()）
  - `tradingagents/graph/propagation.py` - Propagator.create_initial_state()是注入点
  - `tradingagents/agents/utils/agent_states.py` - AgentState结构（4个*_report字段）
  - `tradingagents/graph/trading_graph.py` - TradingAgentsGraph.propagate()是主入口
  - `tradingagents/graph/setup.py` - GraphSetup定义节点和边（验证state字段依赖）

  **Acceptance Criteria**:
  - [ ] CachedAnalysisRunner.run() 返回与AnalysisRunner相同的格式(state, signal)
  - [ ] **注入后下游节点行为验证**：Researcher/Risk/Trader/Portfolio使用预填充的report产生正确结果
  - [ ] TTL内的第二次调用复用缓存（LLM调用次数减少：4→0或4→2等）
  - [ ] 部分缓存命中时（2/4），未缓存的analyst正常执行，已缓存的跳过
  - [ ] force_refresh=True时忽略缓存，完整执行所有4个analyst
  - [ ] 缓存miss时正常执行完整流程，结果保存到新缓存

  **QA Scenarios**:

  ```
  Scenario: 全缓存命中跳过所有analyst
    Tool: Bash (python script)
    Preconditions: 已缓存全部4个analyst
    Steps:
      1. 运行CachedAnalysisRunner（缓存hit）
      2. 监控LLM调用次数（mock或日志）
    Expected Result: 0次analyst LLM调用；Researcher/Risk/Trader/Portfolio正常执行
    Evidence: .sisyphus/evidence/task-3-full-cache-hit.txt

  Scenario: 部分缓存命中（2/4）
    Tool: Bash (python)
    Preconditions: market/sentiment缓存有效，news/fundamentals过期
    Steps:
      1. 运行CachedAnalysisRunner
      2. 监控各analyst LLM调用
    Expected Result: 2次LLM调用（news/fundamentals）；market/sentiment使用缓存
    Evidence: .sisyphus/evidence/task-3-partial-cache-hit.txt

  Scenario: 强制刷新忽略缓存
    Tool: Bash (python)
    Steps:
      1. 运行分析（缓存存在）
      2. 调用runner.run(force_refresh=True)
    Expected Result: 4次analyst LLM调用（完整执行）
    Evidence: .sisyphus/evidence/task-3-force-refresh.txt

  Scenario: 下游节点使用缓存数据正确性验证
    Tool: Bash (python)
    Preconditions: 缓存market_report内容="推荐买入"
    Steps:
      1. 运行CachedAnalysisRunner
      2. 检查Researcher debate输出是否引用"推荐买入"
    Expected Result: Researcher输出包含缓存中的分析内容
    Evidence: .sisyphus/evidence/task-3-downstream-correctness.txt
  ```

  **Commit**: YES
  - Message: `feat(runner): add CachedAnalysisRunner with selective cache injection`
  - Files: `tradingagents/core/cached_analysis_runner.py`, `tests/integration/test_cached_runner.py`

---

- [ ] 4. 添加缓存管理API端点

  **What to do**:
  - 创建 `webapi/routers/cache.py`
  - 实现端点（支持analysis_date参数）：
    - `GET /api/v1/cache/status/{symbol}?date=YYYY-MM-DD` - 查询缓存状态（哪些analyst有缓存、是否有效、过期时间）
    - `POST /api/v1/cache/refresh/{symbol}?date=YYYY-MM-DD` - 强制刷新指定symbol+date的缓存
    - `DELETE /api/v1/cache/{symbol}?date=YYYY-MM-DD&analyst_type=market` - 清除指定symbol[+date][+analyst]的缓存
    - `GET /api/v1/cache/stats` - 缓存统计（命中率、条目数、各analyst分布等）
    - `POST /api/v1/cache/invalidate-event` - 接收事件通知，触发相关缓存失效
  - 在 `main.py` 或现有router中注册

  **Must NOT do**:
  - 不修改现有的analysis/watchlist router
  - 不暴露内部缓存key结构

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - 原因：标准FastAPI端点实现

  **Parallelization**:
  - **Can Run In Parallel**: NO（依赖Task 3）
  - **Blocks**: Task 5
  - **Blocked By**: Task 3

  **References**:
  - `webapi/routers/watchlist.py` - router模式参考
  - `webapi/models/analysis.py` - Pydantic schema参考

  **Acceptance Criteria**:
  - [ ] 所有端点返回正确的HTTP状态码
  - [ ] 响应符合Pydantic schema
  - [ ] 集成测试通过（curl调用）

  **QA Scenarios**:

  ```
  Scenario: 查询缓存状态（指定日期）
    Tool: Bash (curl)
    Steps:
      1. curl "http://localhost:8000/api/v1/cache/status/000001.SZ?date=2026-03-31"
    Expected Result: JSON返回各analyst的缓存状态（created_at, expires_at, is_valid）
    Evidence: .sisyphus/evidence/task-4-cache-status.json

  Scenario: 强制刷新API（指定日期和analyst）
    Tool: Bash (curl)
    Steps:
      1. curl -X POST "http://localhost:8000/api/v1/cache/refresh/000001.SZ?date=2026-03-31&analyst=fundamentals"
    Expected Result: 200 OK，指定analyst缓存被清除
    Evidence: .sisyphus/evidence/task-4-force-refresh.txt

  Scenario: 事件驱动失效API
    Tool: Bash (curl)
    Steps:
      1. curl -X POST http://localhost:8000/api/v1/cache/invalidate-event \
         -H "Content-Type: application/json" \
         -d '{"event_type": "limit_up", "symbol": "000001.SZ"}'
    Expected Result: 200 OK，相关analyst缓存被标记为is_valid=False
    Evidence: .sisyphus/evidence/task-4-event-invalidation.txt
  ```

  **Commit**: YES
  - Message: `feat(api): add cache management endpoints`
  - Files: `webapi/routers/cache.py`, `webapi/models/cache.py`

---

- [ ] 5. UI添加强制刷新控制

  **What to do**:
  - 修改 `web/components/watchlist_manager.py`
  - 在分析按钮旁添加强制刷新checkbox：
    ```python
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("开始分析", key=f"analyze_{symbol}"):
            # 调用分析API
    with col2:
        force_refresh = st.checkbox("强制刷新", key=f"force_{symbol}", 
                                    help="忽略缓存，重新执行全部分析")
    ```
  - 调用分析API时传递 `force_refresh` 参数（通过query param或JSON body）
  - （可选）显示缓存状态图标（如果API提供缓存状态查询）

  **Must NOT do**:
  - 不破坏现有的UI布局

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocks**: Task F1
  - **Blocked By**: Task 4

  **Commit**: YES
  - Message: `feat(ui): add force refresh control`
  - Files: `web/components/watchlist_manager.py`

---

- [ ] 6. 添加缓存监控日志

  **What to do**:
  - 在AnalysisCacheService中添加缓存命中日志：
    - `log_cache_hit(symbol, analyst_type, hit_type)` - hit_type: 'full', 'partial', 'miss'
    - 记录到Python logger（结构化JSON格式便于分析）
  - 添加缓存统计方法：
    - `get_cache_stats()` - 返回命中率、条目数、各analyst分布
    - `get_hit_rate(symbol=None, analyst_type=None, time_range='24h')` - 查询命中率
  - 在API端点 `GET /api/v1/cache/stats` 中暴露统计信息
  - 添加Prometheus-style metrics（可选）：cache_hits_total, cache_misses_total

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - 原因：标准日志和统计实现

  **Parallelization**:
  - **Can Run In Parallel**: YES（与Task 5并行）
  - **Blocks**: None
  - **Blocked By**: Task 4

  **Commit**: YES
  - Message: `feat(cache): add metrics and logging`
  - Files: `webapi/services/analysis_cache_service.py`, `webapi/models/cache.py`（新增stats schema）

---

## Final Verification Wave

- [ ] F1. **集成测试** - 验证全缓存命中、部分缓存命中、缓存miss三种场景
- [ ] F2. **并发测试** - 验证PostgreSQL Advisory Locks正确串行化同一(symbol, analyst)请求
- [ ] F3. **事件驱动失效测试** - 模拟limit_up/earnings_report事件，验证相关缓存失效
- [ ] F4. **下游节点正确性验证** - 验证Researcher/Risk/Trader/Portfolio在预填充state下行为正确
- [ ] F5. **Oracle架构审查** - 验证Upstream Isolation（未修改tradingagents/核心代码）

---

## Risk Matrix (Per Momus Review)

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| **LangGraph注入后下游节点行为异常** | 中 | 严重 | F4验证：预填充state后运行完整集成测试，对比有无缓存的输出一致性 |
| **PostgreSQL Advisory Locks死锁** | 低 | 严重 | 使用try/finally确保锁释放；异常时自动rollback |
| **部分缓存命中产生不一致结果** | 高 | 中 | 先实现"全有或全无"策略；验证通过后再启用部分命中 |
| **日期边界缓存问题** | 中 | 中 | 使用(symbol, analyst, date)复合键；跨日期时强制刷新 |

---

## Commit Strategy

- **Task 1**: `feat(db): add analyst_report_cache table`
- **Task 2**: `feat(cache): implement AnalysisCacheService`
- **Task 3**: `feat(runner): add CachedAnalysisRunner`
- **Task 4**: `feat(api): add cache management endpoints`
- **Task 5**: `feat(ui): add force refresh control`
- **Task 6**: `feat(cache): add metrics and logging`

---

## Success Criteria

### 功能正确性
- [ ] 同一(symbol, date, analyst_type)在TTL内第二次分析复用缓存（LLM调用减少）
- [ ] 部分缓存命中时（2/4），仅执行未缓存的analyst，其余使用缓存
- [ ] 用户可通过UI强制刷新（force_refresh=True）
- [ ] 事件驱动失效正确工作（limit_up→market/sentiment失效，earnings→fundamentals失效）

### 并发安全
- [ ] PostgreSQL Advisory Locks正确串行化同一(symbol, analyst)的并发请求
- [ ] 不同symbol或不同analyst的并发请求互不阻塞
- [ ] 锁在异常情况下正确释放（避免死锁）

### 架构合规
- [ ] 未修改 `tradingagents/core/analysis_runner.py` 以外的任何上游代码
- [ ] 未修改 `tradingagents/graph/` 中的任何文件
- [ ] 未修改 `tradingagents/agents/` 中的任何文件
- [ ] 未引入Redis/MongoDB等额外存储

### 性能目标
- [ ] 缓存命中时LLM调用减少50-75%（4个analyst中跳过已缓存的）
- [ ] 缓存查询延迟 < 10ms（PostgreSQL索引命中）
- [ ] 缓存写入不影响分析流程响应时间（异步写入）
