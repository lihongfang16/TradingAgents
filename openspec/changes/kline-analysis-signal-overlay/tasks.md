## 1. Backend API - Analysis History

- [ ] 1.1 Add `get_analysis_history()` method to WatchlistAnalysis model
- [ ] 1.2 Create Pydantic schema `WatchlistAnalysisHistoryResponse`
- [ ] 1.3 Implement `GET /api/v1/watchlist/{id}/analysis-history` endpoint
- [ ] 1.4 Add query parameter `limit` with default value 50
- [ ] 1.5 Add ownership validation (403 if not owner)
- [ ] 1.6 Add 404 handling for non-existent watchlist item
- [ ] 1.7 Test API endpoint with curl

## 2. Frontend - Data Fetching

- [ ] 2.1 Add `get_analysis_history(stock_id: int)` function in watchlist_manager.py
- [ ] 2.2 Add error handling with retry logic
- [ ] 2.3 Cache analysis history in session_state
- [ ] 2.4 Add refresh mechanism after trigger_quick_analysis

## 3. Frontend - K-Line Chart Enhancement

- [ ] 3.1 Modify `render_candlestick_chart()` signature to accept `analysis_data` parameter
- [ ] 3.2 Add signal-to-Kline mapping function (timestamp matching)
- [ ] 3.3 Implement BUY signal marker (green upward arrow + confidence label)
- [ ] 3.4 Implement SELL signal marker (red downward arrow + confidence label)
- [ ] 3.5 Implement HOLD signal marker (yellow horizontal line + confidence label)
- [ ] 3.6 Add "尚无AI信号" caption when no analysis data

## 4. Frontend - Trade Trajectory Visualization

- [ ] 4.1 Implement trade pair detection (BUY→SELL, SELL→BUY)
- [ ] 4.2 Add profit/loss calculation logic
- [ ] 4.3 Draw green solid line for profitable trades
- [ ] 4.4 Draw red dashed line for loss trades
- [ ] 4.5 Add hover tooltip with trade details (entry, exit, P&L)
- [ ] 4.6 Ensure HOLD signals don't create connections

## 5. Frontend - Error Handling

- [ ] 5.1 Add error banner component for analysis API errors
- [ ] 5.2 Add retry button for network errors
- [ ] 5.3 Display specific error messages from API
- [ ] 5.4 Add loading spinner during analysis fetch

## 6. Frontend - Integration

- [ ] 6.1 Update `render_monitoring_panel()` to fetch and pass analysis history
- [ ] 6.2 Update multi-stock charts to show signals
- [ ] 6.3 Update detail view chart to show trajectory
- [ ] 6.4 Add signal marker click handler to scroll to analysis detail

## 7. Testing & Verification

- [ ] 7.1 Test API with various watchlist items
- [ ] 7.2 Test K-line chart with single signal
- [ ] 7.3 Test K-line chart with multiple signals
- [ ] 7.4 Test trajectory lines (profit/loss cases)
- [ ] 7.5 Test error states (API failure, network error)
- [ ] 7.6 Verify UI responsiveness
- [ ] 7.7 End-to-end test: trigger analysis → see signal on K-line
