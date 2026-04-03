# CLI 交互层 (CLI Interface)

> 类型: 扩展 | 层级: 接口 | 上游对应: 有

## 概述

CLI交互层基于Typer和Rich构建，提供交互式命令行界面。上游TradingAgents库已具备基础CLI功能，本模块在保留上游核心逻辑的同时，扩展了A股符号支持、进度显示优化、以及状态管理增强。

关键扩展包括：A股6位代码自动识别、交互式股票选择器、分析日期选择器、LLM提供商切换、研究深度配置，以及基于MessageBuffer的状态管理。代码量约1537行，是下游改进最显著的接口模块之一。

## 架构

### 组件结构

```
cli/
├── main.py                      # CLI主入口（1537行）
├── config.py                    # CLI配置
├── utils.py                     # CLI工具函数
└── __init__.py
```

### 核心类/函数

| 符号 | 类型 | 位置 | 功能描述 |
|------|------|------|----------|
| `MessageBuffer` | 类 | `main.py` | 消息状态管理，支持Rich实时渲染 |
| `interactive_select_stock()` | 函数 | `main.py` | 交互式股票选择（支持A股搜索） |
| `display_progress()` | 函数 | `main.py` | 增强进度显示（多代理进度条） |
| `run_analysis()` | 函数 | `main.py` | 分析执行主函数 |
| `app` | Typer实例 | `main.py` | CLI命令注册入口 |

### 数据流

```
用户输入 → Typer解析 → 交互式提示（Rich）
                    ↓
            构建分析配置 → 调用AnalysisRunner
                    ↓
            MessageBuffer ← 实时收集代理输出
                    ↓
            Rich Live Display ← 动态刷新界面
```

## 与上游的关系

| 方面 | 说明 |
|------|------|
| 继承 | 保留上游分析调用逻辑 |
| 新增 | A股符号支持、交互式选择器、MessageBuffer状态管理、增强进度显示 |
| 修改 | 优化了用户交互流程，增加配置向导 |
| 文件位置 | 与上游CLI位于不同目录（上游可能在`tradingagents/cli/`），无直接冲突 |

**功能对比**:

| 功能 | 上游 | 下游 |
|------|------|------|
| 基础分析命令 | ✓ | ✓ |
| A股符号输入 | ✗ | ✓ |
| 交互式股票选择 | ✗ | ✓ |
| 实时进度显示 | 基础 | 增强（Rich） |
| 消息状态管理 | ✗ | ✓（MessageBuffer） |
| 日期选择器 | ✗ | ✓ |

## 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 默认LLM提供商 | `CLI_DEFAULT_LLM` | openai | 交互模式默认LLM |
| 默认研究深度 | `CLI_DEFAULT_DEPTH` | standard | standard/deep/fast |
| 历史记录文件 | `CLI_HISTORY_FILE` | ~/.tradingagents/history.json | 交互历史存储 |
| 主题样式 | `CLI_THEME` | default | Rich主题名称 |

### 启动方式

```bash
# 安装后全局命令
tradingagents

# 源码直接运行
python -m cli.main

# 带参数运行
python -m cli.main analyze --symbol 000001 --exchange SZSE
```

## 接口

### 命令列表

| 命令 | 子命令 | 描述 |
|------|--------|------|
| `analyze` | - | 执行单股票分析 |
| `watchlist` | `add` | 添加股票到关注列表 |
| `watchlist` | `list` | 显示关注列表 |
| `watchlist` | `remove` | 从关注列表移除 |
| `config` | `show` | 显示当前配置 |
| `config` | `set` | 修改配置项 |
| `history` | - | 查看分析历史 |

### 交互式选项

| 选项 | 类型 | 说明 |
|------|------|------|
| `--interactive` / `-i` | 标志 | 启用交互式模式 |
| `--symbol` | 文本 | 股票代码（支持A股6位数字） |
| `--exchange` | 选择 | 交易所（SSE/SZSE/BSE） |
| `--date` | 日期 | 分析日期 |
| `--depth` | 选择 | 研究深度（fast/standard/deep） |
| `--llm-provider` | 选择 | LLM提供商 |

### 进度显示

CLI使用Rich库提供多行动态进度显示：

```
┌─────────────────────────────────────┐
│ 分析任务: 000001.SZ                 │
│ 总体进度: [████████░░░░░░░░░░] 50%  │
├─────────────────────────────────────┤
│ Researcher    [████████░░░░] 80%    │
│ Analyst-A     [██████░░░░░░] 60%    │
│ Analyst-B     [████████░░░░] 80%    │
│ Risk Manager  [░░░░░░░░░░░░] 0%     │
└─────────────────────────────────────┘
```

## 依赖

### 外部依赖

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| typer | >=0.9.0 | CLI框架 |
| rich | >=13.0.0 | 终端富文本渲染 |
| click | >=8.0.0 | Typer底层依赖 |
| prompt-toolkit | >=3.0.0 | 交互式输入 |

### 内部依赖

- `tradingagents/core/analysis_runner.py` — 分析执行器
- `tradingagents/default_config.py` — 默认配置
- `webapi/services/` — 可选API服务集成

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| Windows终端兼容 | 已知 | 部分旧版Windows终端Rich渲染异常，建议使用Windows Terminal |
| 长分析任务中断 | 已知 | Ctrl+C中断可能留下残留状态，需重启CLI |
| 交互模式历史 | 待优化 | 历史记录仅保存成功完成的分析 |
| 并发分析限制 | 设计如此 | CLI设计为单任务，不支持并发分析 |

## 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-05 | 1.0.0 | 基础CLI框架（Typer） |
| 2026-03-12 | 1.5.0 | 集成Rich，优化显示效果 |
| 2026-03-18 | 2.0.0 | 新增A股符号支持与交互式选择器 |
| 2026-03-24 | 2.1.0 | MessageBuffer状态管理重构 |

