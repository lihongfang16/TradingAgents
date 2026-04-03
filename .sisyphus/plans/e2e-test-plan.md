# TradingAgents 端到端测试项目计划

## 目标
创建完整的端到端测试套件，覆盖 API 和 Web UI 的所有功能，确保系统稳定性和正确性。

## 测试范围

### 1. API 端点测试
- **Health Check**: `GET /health`
- **创建分析**: `POST /api/v1/analysis/`
- **获取分析列表**: `GET /api/v1/analysis/`
- **获取单个分析**: `GET /api/v1/analysis/{task_id}`
- **获取进度**: `GET /api/v1/analysis/{task_id}/progress`

### 2. Web UI 测试 (Playwright)
- **首页加载**: 验证页面正确渲染
- **新建分析表单**: 
  - 股票代码输入
  - 分析师选择
  - 深度选择
  - 提交表单
- **历史记录页面**:
  - 列表加载
  - 查看详情
  - 删除记录
- **分析详情页**:
  - 显示决策结果
  - 显示进度条
  - 返回按钮

### 3. 集成测试
- 完整流程: 提交分析 → 等待完成 → 查看结果 → 删除记录

## 项目结构

```
tests/e2e/
├── conftest.py           # pytest fixtures and config
├── pytest.ini            # pytest configuration
├── requirements-test.txt # test dependencies
├── api/                  # API tests
│   ├── test_health.py
│   ├── test_analysis.py
│   └── test_integration.py
├── ui/                   # Web UI tests
│   ├── test_homepage.py
│   ├── test_analysis_form.py
│   └── test_history.py
└── fixtures/             # Test data
    └── sample_analysis.py
```

## 测试策略

### API 测试策略
1. 使用 `requests` 库发送 HTTP 请求
2. 验证状态码、响应结构、数据完整性
3. 错误处理测试（无效输入、404等）

### UI 测试策略
1. 使用 Playwright 进行浏览器自动化
2. 截图对比（可选）
3. 元素交互验证
4. 表单提交和页面导航

### 数据管理
- 使用 fixtures 提供测试数据
- 测试后清理数据（删除测试记录）
- 环境变量配置测试 URL

## 依赖安装

```bash
pip install pytest pytest-asyncio requests playwright pytest-playwright
playwright install chromium
```

## 运行命令

```bash
# 运行所有测试
pytest tests/e2e/

# 仅运行 API 测试
pytest tests/e2e/ -m api

# 仅运行 UI 测试
pytest tests/e2e/ -m ui

# 生成 HTML 报告
pytest tests/e2e/ --html=report.html
```

## 环境要求

1. 本地需要运行：
   - API 服务 (http://localhost:8000)
   - Web 服务 (http://localhost:8501)

2. 或者远程服务器：
   - 设置环境变量 `TEST_API_URL=http://10.8.0.1:8000`
   - 设置环境变量 `TEST_WEB_URL=http://10.8.0.1:8501`

## 成功标准

- [ ] 所有 API 端点返回预期结果
- [ ] UI 测试通过无错误
- [ ] 集成测试完成完整流程
- [ ] 测试报告生成成功
