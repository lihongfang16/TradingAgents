# 自选股多股票价格走势图功能计划

## TL;DR
> 在自选股监控面板中添加多股票价格走势图功能，底部显示带checkbox的股票列表，勾选的股票以4列布局并列显示价格曲线图。

**Deliverables**:
- 添加 `get_stock_intraday_data()` 函数获取实时价格数据
- 修改 `render_monitoring_panel()` 支持多选和并列显示
- 底部checkbox区域列出所有自选股
- 一行最多4个图表并列显示

**Estimated Effort**: Medium
**Parallel Execution**: NO (单文件顺序修改)

---

## Context

### 当前实现
- `render_monitoring_panel()` (line 526-611) 只显示单股票详情
- 价格走势使用硬编码mock数据 (line 589-594)
- 使用 `st.selectbox` 单选股票

### 数据结构
- `watchlist` 列表包含所有自选股，每项有 `id`, `symbol`, `name`, `last_price` 等字段
- `AshareProvider.get_kline(symbol, period="1m")` 可获取日内分时数据

### UI参考
- 已有 `st.checkbox` 使用模式 (line 512, 720, 727)
- 已有 `st.columns(4)` 布局模式 (line 551, 739)

---

## Work Objectives

### Core Objective
实现多股票价格走势图展示，支持用户通过checkbox选择要显示的股票，最多同时显示4个图表。

### Concrete Deliverables
1. **数据获取函数**: `get_stock_intraday_data(symbol)` 返回DataFrame
2. **多选UI**: 底部checkbox区域列出所有股票
3. **图表展示**: 4列布局，每列一个股票的line_chart
4. **状态管理**: 使用 `session_state` 保存用户选择

### Definition of Done
- [ ] 输入6位股票代码自动解析名称 (已实现)
- [ ] 底部checkbox区域显示所有自选股
- [ ] 勾选的股票实时显示价格走势图
- [ ] 一行最多4个图表，超过自动换行
- [ ] 每个图表显示股票名称和当前价格

### Must NOT Have
- 不修改数据获取底层逻辑
- 不改变现有的单股票详情视图（作为可选项保留）
- 不添加外部依赖

---

## Execution Strategy

### Wave 1: 添加数据获取函数
**任务1**: 在文件顶部导入区域后添加 `get_stock_intraday_data()` 函数
- 使用 `AshareProvider.get_kline(symbol, period="1m", limit=240)` 获取日内数据
- 失败时回退到 `get_realtime_quote()` 返回单点数据
- 返回 DataFrame 包含 `time` 和 `price` 列

### Wave 2: 修改监控面板主函数
**任务2**: 重写 `render_monitoring_panel()` 函数
1. 保留原有的单股票详情视图（可折叠或通过tab切换）
2. 添加多选股票图表展示区域
3. 底部添加checkbox选择区域
4. 使用 `st.session_state` 保存选中的股票ID列表

### Wave 3: 实现图表网格布局
**任务3**: 实现4列图表布局
- 每行4个图表使用 `st.columns(4)`
- 每个图表使用 `st.line_chart(df.set_index('time')['price'])`
- 图表上方显示股票名称和当前价格
- 处理数据获取失败的 gracefully降级

---

## TODOs

- [x] 1. 添加数据获取函数 get_stock_intraday_data()

  **What to do**:
  - 在import区域后添加新函数
  - 导入 `AshareProvider` 获取实时价格数据
  - 处理异常返回None
  
  **Must NOT do**:
  - 不修改现有函数
  - 不添加新依赖

  **References**:
  - `tradingagents/dataflows/ashare_provider.py:386` - get_realtime_quote
  - `tradingagents/dataflows/ashare_provider.py:300` - get_kline
  
  **Acceptance Criteria**:
  - [x] 函数能正确获取股票日内数据
  - [x] 返回值是DataFrame或None
  - [x] 处理异常不崩溃

- [x] 2. 修改 render_monitoring_panel() 添加多选状态管理

  **What to do**:
  - 添加 `session_state` 键 `monitoring_selected_stocks` 存储选中的股票ID
  - 初始化时默认选中前4个股票（如果有）
  - 在函数开头添加checkbox选择区域
  
  **Must NOT do**:
  - 不删除原有单股票详情视图代码
  - 不改变现有session_state键

  **References**:
  - `watchlist_manager.py:526` - render_monitoring_panel 函数起始
  - `watchlist_manager.py:512` - checkbox使用示例
  
  **Acceptance Criteria**:
  - [x] 刷新页面后保留用户选择
  - [x] checkbox状态正确反映session_state

- [x] 3. 实现底部checkbox选择区域

  **What to do**:
  - 在图表区域下方添加 `st.subheader("📊 选择要显示的股票")`
  - 使用 `st.columns(6)` 或流式布局显示checkbox
  - 每个checkbox格式: `{symbol} {name}`
  - 最多显示全部自选股（从watchlist获取）
  
  **Must NOT do**:
  - 不限制可选数量（只限制显示数量）
  - 不使用多选下拉框

  **References**:
  - `analysis_form.py:60-64` - checkbox分组示例
  
  **Acceptance Criteria**:
  - [x] 所有自选股都显示checkbox
  - [x] 勾选状态实时更新session_state
  - [x] UI美观，名称显示完整

- [x] 4. 实现4列图表网格布局

  **What to do**:
  - 获取选中的股票列表
  - 每4个股票一组使用 `st.columns(4)`
  - 每个column中:
    - 显示股票名称和当前价格（st.metric或st.write）
    - 调用 `get_stock_intraday_data()` 获取数据
    - 使用 `st.line_chart()` 显示价格曲线
  - 处理数据获取失败显示占位符
  
  **Must NOT do**:
  - 不一行显示超过4个图表
  - 不显示无数据的股票（或显示占位符）

  **References**:
  - `history_manager.py:949` - columns(4)使用示例
  - `watchlist_manager.py:601` - line_chart使用示例
  
  **Acceptance Criteria**:
  - [x] 一行最多4个图表
  - [x] 图表宽度自适应
  - [x] 每个图表有标题和价格
  - [x] 数据失败有友好提示

- [x] 5. 集成测试和验证

  **What to do**:
  - 确保函数导入正确
  - 测试多选/取消选择功能
  - 验证4列布局正确
  - 测试数据获取失败场景
  
  **Acceptance Criteria**:
  - [x] 无语法错误
  - [x] 功能完整可用
  - [x] UI美观整齐

---

## Final Verification Wave

- [x] **代码审查**: 检查是否有语法错误，import是否正确
- [x] **功能测试**: 添加几个自选股，测试多选功能
- [x] **布局验证**: 验证4列布局和checkbox区域样式
- [x] **边界测试**: 测试无自选股、单个股票、超过4个股票的情况

---

## Commit Strategy

**Single Commit**:
```
feat(watchlist): 多股票价格走势图功能

- 添加 get_stock_intraday_data() 获取实时价格数据
- 修改 render_monitoring_panel() 支持多股票展示
- 底部添加checkbox选择区域
- 实现4列图表布局，一行最多4个
```

---

## Success Criteria

### Verification Commands
```bash
# 启动Web服务
python start_web.py

# 访问自选股页面，验证:
# 1. 底部有checkbox区域
# 2. 可以勾选多个股票
# 3. 图表按4列显示
# 4. 价格数据正确显示
```

### Final Checklist
- [ ] get_stock_intraday_data() 函数正常工作
- [ ] checkbox区域显示所有自选股
- [ ] 勾选后图表实时更新
- [ ] 4列布局正确，自动换行
- [ ] 每个图表有正确的标题和价格
- [ ] 无控制台报错
