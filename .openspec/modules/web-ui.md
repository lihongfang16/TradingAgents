# Streamlit 前端 (Web UI)

> 类型: 全新 | 层级: 接口 | 上游对应: 无

## 概述

Streamlit前端是基于Streamlit框架构建的独立Web应用程序。上游TradingAgents库未提供Web界面，本模块从零构建了完整的可视化分析平台，支持股票分析仪表盘、关注列表管理、历史记录查看、以及实时进度展示。

**重要设计决策**: `web/`目录**不**包含`__init__.py`文件，这意味着它不是一个Python包，而是一个独立的Streamlit应用程序。这种设计避免了与主包的结构耦合，允许直接通过`streamlit run`命令启动。

## 架构

### 组件结构

```
web/                           # 注意：无__init__.py，非Python包
├── app.py                     # Streamlit主入口
├── config.py                  # 前端配置
├── components/                # UI组件目录
│   ├── __init__.py
│   ├── sidebar.py             # 侧边栏导航
│   ├── analysis_form.py       # 分析表单组件
│   ├── progress_view.py       # 进度展示组件
│   ├── result_card.py         # 结果卡片组件
│   └── watchlist_view.py      # 关注列表视图
├── data/                      # 本地数据（缓存/回退）
│   └── history.json           # 历史记录本地缓存
├── utils/                     # 前端工具函数
│   ├── __init__.py
│   └── api_client.py          # API客户端封装
└── pages/                     # 多页面路由
    ├── 01_分析.py
    ├── 02_关注列表.py
    └── 03_历史记录.py
```

### 核心类/函数

| 符号 | 类型 | 位置 | 功能描述 |
|------|------|------|----------|
| `main()` | 函数 | `app.py` | Streamlit应用入口 |
| `render_sidebar()` | 函数 | `components/sidebar.py` | 侧边栏导航渲染 |
| `AnalysisForm` | 类 | `components/analysis_form.py` | 分析配置表单 |
| `ProgressView` | 类 | `components/progress_view.py` | 实时进度显示组件 |
| `APIClient` | 类 | `utils/api_client.py` | 后端API封装客户端 |

### 数据流

```
用户操作 → Streamlit组件
                ↓
        APIClient → REST API调用
                ↓
        后端服务处理 → 返回结果
                ↓
        Streamlit重新渲染 → 更新UI
                ↓
        （SSE连接）实时进度推送 → ProgressView更新
```

## 与上游的关系

| 方面 | 说明 |
|------|------|
| 继承 | 无直接继承 |
| 新增 | 完整的Web UI层，包括组件库、API客户端、页面路由 |
| 修改 | 无 |
| 依赖关系 | 通过API层（webapi）间接调用分析引擎，零上游代码依赖 |

**架构原则**: Web UI仅通过HTTP API与后端通信，不直接导入任何`tradingagents/`模块代码。这确保了严格的关注点分离。

## 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| API基础URL | `API_BASE_URL` | http://localhost:8000 | 后端API地址 |
| 页面标题 | `STREAMLIT_PAGE_TITLE` | TradingAgents A股分析 | 浏览器标签页标题 |
| 主题模式 | `STREAMLIT_THEME` | light | light/dark |
| 自动刷新间隔 | `AUTO_REFRESH_INTERVAL` | 5 | 进度轮询间隔（秒） |

### 启动方式

```bash
# 通过启动脚本
python start_web.py

# 或直接通过Streamlit
streamlit run web/app.py --server.port 8501

# Docker环境
docker-compose up web
```

## 接口

### 页面路由

| 路径 | 页面 | 描述 |
|------|------|------|
| `/` | 首页/分析 | 主分析页面 |
| `/01_分析` | 分析 | 新建分析任务 |
| `/02_关注列表` | 关注列表 | 管理关注股票 |
| `/03_历史记录` | 历史记录 | 查看过往分析 |

### 组件接口

#### AnalysisForm

```python
form = AnalysisForm()
config = form.render()  # 返回分析配置字典
```

#### ProgressView

```python
progress = ProgressView(task_id="xxx")
progress.render()  # 自动连接SSE并更新进度
```

### API客户端方法

| 方法 | 描述 |
|------|------|
| `create_analysis(config)` | 创建分析任务 |
| `get_task(task_id)` | 获取任务详情 |
| `get_progress_stream(task_id)` | 获取SSE流 |
| `get_result(task_id)` | 获取分析结果 |
| `list_watchlist()` | 获取关注列表 |
| `add_watchlist(symbol)` | 添加关注 |

## 依赖

### 外部依赖

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| streamlit | >=1.28.0 | Web应用框架 |
| streamlit-echarts | >=0.4.0 | ECharts图表组件 |
| pandas | >=2.0.0 | 数据展示 |
| requests | >=2.28.0 | HTTP客户端 |
| plotly | >=5.18.0 | 交互式图表 |

### 内部依赖

- 无直接内部依赖（通过HTTP API通信）

### 数据文件

| 文件 | 说明 |
|------|------|
| `web/data/history.json` | 本地历史缓存，**非**数据源（PostgreSQL为源） |

**注意**: `history.json`仅作为离线回退使用，所有持久化数据存储于PostgreSQL。

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| SSE在Streamlit中重连 | 已知 | 页面切换后SSE连接可能断开，需手动刷新 |
| 大结果集渲染性能 | 已知 | 超长历史记录列表可能影响渲染性能 |
| 移动端适配 | 待优化 | 当前主要针对桌面端优化 |
| 图表交互 | 已知 | 部分ECharts交互在Streamlit中有延迟 |

## 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-08 | 1.0.0 | 基础Streamlit应用框架 |
| 2026-03-15 | 1.5.0 | 新增多页面路由 |
| 2026-03-20 | 2.0.0 | 集成实时进度SSE |
| 2026-03-26 | 2.1.0 | 优化移动端显示 |

