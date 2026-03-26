# 编码规约

## Python 代码风格

### 基础规范

- **行长度**: 最大 100 字符
- **缩进**: 4 个空格（不使用 Tab）
- **编码**: UTF-8
- **换行**: LF（Unix 风格）

### 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块 | 小写，下划线分隔 | `analysis_service.py` |
| 类 | 大驼峰 | `AnalysisService`, `TradingAgentsGraph` |
| 函数/方法 | 小写，下划线分隔 | `create_task()`, `get_task()` |
| 变量 | 小写，下划线分隔 | `task_id`, `created_at` |
| 常量 | 全大写 | `DEFAULT_CONFIG`, `MAX_RETRIES` |
| 私有属性 | 单下划线前缀 | `_tasks`, `_db_session` |

### 导入排序

```python
# 1. 标准库
import os
from datetime import datetime

# 2. 第三方库
import sqlalchemy
from fastapi import FastAPI

# 3. 本地模块
from webapi.models.database import AnalysisTask
from tradingagents.default_config import DEFAULT_CONFIG
```

### 类型注解

- 函数参数和返回值必须添加类型注解
- 使用 `typing` 模块的泛型
- 复杂类型使用 TypeAlias

```python
from typing import Optional, Dict, List
from datetime import datetime

def get_task(task_id: str) -> Optional[AnalysisTask]:
    ...

def list_tasks(
    symbol: Optional[str] = None,
    status: Optional[str] = None
) -> List[AnalysisTask]:
    ...
```

## 注释要求

### 文档字符串

所有公共模块、类、方法必须包含文档字符串。

```python
def create_task(
    symbol: str,
    analysts: List[str],
    llm_provider: str = "openai"
) -> AnalysisTask:
    """Create a new analysis task.
    
    Args:
        symbol: Stock symbol to analyze (e.g., "000001")
        analysts: List of analysts to run (e.g., ["market", "technical"])
        llm_provider: LLM provider to use (default: "openai")
    
    Returns:
        The created AnalysisTask instance
    
    Raises:
        ValueError: If symbol is empty or invalid
    """
    ...
```

### 行内注释

- 解释 "为什么" 而不是 "做什么"
- 复杂逻辑前添加注释
- 使用 `#` 后跟一个空格

```python
# Use database transaction to ensure atomicity
with db_session.begin():
    task.status = "RUNNING"
    db_session.commit()
```

### 类型注释

```python
# JSONB field for flexible result storage
result: Mapped[dict] = mapped_column(JSONB, default=dict)
```

## 代码组织

### 模块结构

```
webapi/
├── __init__.py
├── main.py              # 应用入口
├── config/              # 配置文件
│   ├── __init__.py
│   └── database.py      # 数据库配置
├── models/              # 数据模型
│   ├── __init__.py
│   ├── analysis.py      # Pydantic 模型
│   └── database.py      # SQLAlchemy 模型
├── routers/             # API 路由
│   ├── __init__.py
│   └── analysis.py      # 分析相关端点
└── services/            # 业务逻辑
    ├── __init__.py
    └── analysis_service.py
```

### 类设计原则

1. **单一职责**: 每个类只负责一件事
2. **开闭原则**: 对扩展开放，对修改关闭
3. **依赖注入**: 使用构造函数注入依赖

```python
class AnalysisService:
    """Service for managing analysis tasks."""
    
    def __init__(self, db_session: Session):
        self._db = db_session
    
    def create_task(self, request: AnalysisRequest) -> AnalysisTask:
        """Create a new analysis task."""
        ...
```

## 数据库规范

### 表命名

- 使用复数形式
- 小写，下划线分隔

```python
# Good
analysis_tasks
user_preferences
market_data

# Bad
analysistask
UserPreference
marketData
```

### 字段命名

- 使用小写，下划线分隔
- 时间戳字段统一命名

```python
created_at: Mapped[datetime]  # 创建时间
updated_at: Mapped[datetime]  # 更新时间
completed_at: Mapped[Optional[datetime]]  # 完成时间
```

### 索引规范

- 外键自动创建索引
- 查询频繁的字段添加索引
- 索引命名: `ix_<table>_<column>`

```python
__table_args__ = (
    Index('ix_analysis_tasks_symbol', 'symbol'),
    Index('ix_analysis_tasks_status', 'status'),
    Index('ix_analysis_tasks_created_at', 'created_at'),
)
```

## 错误处理

### 异常使用

- 使用标准异常类型
- 自定义异常继承自 Exception
- 提供有意义的错误信息

```python
class TaskNotFoundError(Exception):
    """Raised when a task is not found."""
    pass

class DatabaseError(Exception):
    """Raised when database operation fails."""
    pass
```

### API 错误响应

```python
from fastapi import HTTPException

@router.get("/{task_id}")
async def get_task(task_id: str):
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found"
        )
    return task
```

## 测试规范

### 测试结构

```python
import pytest

class TestAnalysisService:
    """Test cases for AnalysisService."""
    
    def test_create_task_success(self, db_session):
        """Test creating a task with valid data."""
        ...
    
    def test_get_task_not_found(self, db_session):
        """Test getting a non-existent task."""
        ...
```

### 测试命名

- 测试类: `Test<被测类名>`
- 测试方法: `test_<场景>_<期望结果>`

## Git 提交规范

### 提交信息格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

### 类型定义

| 类型 | 用途 |
|------|------|
| feat | 新功能 |
| fix | Bug 修复 |
| docs | 文档更新 |
| style | 代码格式（不影响功能） |
| refactor | 重构 |
| test | 测试相关 |
| chore | 构建/工具/依赖 |

### 示例

```
feat(api): Add DELETE /analysis/{task_id} endpoint

- Add delete_task method to AnalysisService
- Add DELETE endpoint to analysis router
- Return 204 No Content on success

Closes #123
```

## 环境配置

### 环境变量

- 使用 `.env` 文件管理配置
- `.env.example` 提供配置模板
- 敏感信息不提交到版本控制

```bash
# .env.example
DATABASE_URL=postgresql://trading:password@localhost:5432/trading_db
OPENAI_API_KEY=your_openai_key_here
```

### 配置读取

```python
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://trading:password@localhost:5432/trading_db"
)
```
