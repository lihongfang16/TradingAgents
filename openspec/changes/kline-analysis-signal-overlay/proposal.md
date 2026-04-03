## Why

当前自选股K线图只显示价格数据，AI分析信号（BUY/SELL/HOLD）只在表格中显示为文本，没有与K线图关联。用户无法直观看到信号产生时的价格位置和时机，也无法追踪连续的交易信号形成交易轨迹。这降低了分析结果的可读性和实用性。

## What Changes

- **新增后端API**：`GET /api/v1/watchlist/{id}/analysis-history` 获取自选股分析历史时间序列
- **增强K线图渲染**：在K线图上叠加信号标记（箭头+颜色+置信度）
- **买卖连线可视化**：用线条连接连续的买卖信号，形成交易轨迹
  - 盈利交易：绿色实线连接
  - 亏损交易：红色虚线连接
- **错误状态提示**：分析失败时显示明确错误信息，网络错误显示重试按钮
- **实时更新**：触发分析后自动刷新K线图显示最新信号

## Capabilities

### New Capabilities
- `watchlist-analysis-history-api`: 后端API提供自选股分析历史查询
- `kline-signal-overlay`: K线图信号标记叠加显示
- `trade-trajectory-visualization`: 买卖信号连线形成交易轨迹

### Modified Capabilities
- `watchlist-monitoring`: 修改监控面板K线图渲染逻辑，支持分析数据叠加

## Impact

- **后端**：
  - `webapi/routers/watchlist.py`: 新增 analysis-history 接口
  - `webapi/services/analysis_service.py`: 查询分析历史逻辑
  - `webapi/models/database.py`: WatchlistAnalysis 模型查询方法
  
- **前端**：
  - `web/components/watchlist_manager.py`: 修改 `render_candlestick_chart()` 支持信号叠加
  - 新增分析历史获取函数
  - 错误状态UI增强
  
- **API契约**：
  - 新增端点：`GET /api/v1/watchlist/{id}/analysis-history`
  - 响应格式：分析记录列表 `{timestamp, signal, confidence, price}`
