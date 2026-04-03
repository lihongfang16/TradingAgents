# 自选股实时监控系统计划

## 需求分析

### 核心功能
1. **自选股管理页面** - 增删改查自选股列表
2. **定时分析任务** - 凌晨全局分析、交易时间快速分析
3. **变盘检测** - 基于AI分析结果检测变盘信号
4. **桌面通知** - 变盘信号实时推送

### 业务规则
- **交易时间**: 9:20-11:30, 13:00-15:00
- **正常监控**: 每5分钟快速分析
- **变盘触发**: AI分析结果出现重大变化（信号转变/置信度突破阈值）
- **高频模式**: 变盘后每2分钟分析，信号稳定后恢复5分钟
- **凌晨任务**: 每日凌晨全局深度分析

### 变盘定义
**变盘** = AI分析结果相比上次发生**实质性变化**：
- 信号转变：BUY→SELL / SELL→BUY / HOLD→BUY/SELL
- 置信度突破：从<70%提升到>85%（强烈信号出现）
- 风险等级变化：从低风险变为高风险（或反之）
- 紧急信号：市场分析师发出"异常波动"警告

---

## 技术架构

### 前端
- 自选股管理页面（Streamlit）
- 实时监控面板
- 变盘信号提醒

### 后端
- 自选股数据模型（PostgreSQL）
- 定时任务调度器（APScheduler）
- 快速分析模式（简化agent参与）
- 实时价格获取（WebSocket/轮询）
- 波动检测算法
- 桌面通知API

### 数据流
```
价格数据 ──→ 定时分析 ──→ 结果存储 ──→ 变盘检测 ──→ 通知推送
                ↑                              ↓
                └──────── 变盘触发高频分析 ←─────┘
```

**关键变化**：
1. 定时分析是核心驱动（不是价格波动）
2. 每次分析后执行"变盘检测"算法
3. 只有检测到变盘才：
   - 发送桌面通知
   - 触发高频分析（2分钟间隔）
   - 记录变盘信号历史

---

## 任务分解

### Phase 1: 数据模型与基础架构
1. 创建 `Watchlist` 数据模型
2. 创建 `WatchlistAnalysis` 任务模型
3. 添加 Alembic 迁移
4. 创建基础 API 端点

### Phase 2: 自选股管理页面
1. 创建 `watchlist_manager.py` 组件
2. 添加股票搜索与添加功能
3. 添加自选股列表展示
4. 添加删除/编辑功能
5. 集成到主导航

### Phase 3: 快速分析模式（使用现有Graph的Fast-Path）

**方案**：不创建新的Graph，而是在现有 `AnalysisRunner` 上添加 `fast_mode` 参数：

1. **修改 `AnalysisRunner.__init__`**
   - 添加 `fast_mode: bool = False` 参数
   - 当 `fast_mode=True` 时，在 `run()` 方法中跳过耗时节点

2. **Fast Mode 实现逻辑**
   ```python
   # 在 analysis_runner.py run() 方法中
   if self.fast_mode:
       # 跳过 bull/bear debate (节省 ~60% 时间)
       # 跳过 detailed risk discussion (节省 ~20% 时间)
       # 只执行: graph_setup → market_analyst → quick_risk_check → trader → portfolio_manager
       # 预计时间: 15-25秒 (vs 完整分析 3-5分钟)
   ```

3. **修改 `_run_sync_analysis`**
   - 添加 `is_quick: bool = False` 参数
   - 传递 `fast_mode=True` 给 `AnalysisRunner`

4. **添加快速分析API端点**
   - `POST /api/v1/watchlist/{id}/quick-analyze`
   - 返回 `AnalysisResponse` 但标记 `analysis_type='quick'`

**QA验证**: 
- 快速分析完成时间 < 30秒
- 返回结果包含 signal, confidence, risk_level
- 结果存储到 `WatchlistAnalysis` 表

### Phase 3b: Quick Analysis Runner（备选方案）

如果现有Graph无法简化，则创建独立的轻量级分析器：
1. 使用简单的 LLM Chain（非Graph）
2. 单轮prompt完成市场+风险+交易分析
3. 响应时间目标 < 10秒

### Phase 4: 定时任务调度
1. 集成 APScheduler
2. 凌晨全局分析任务
3. 交易时间快速分析任务
4. 动态调整分析频率

### Phase 5: 变盘检测与通知
1. 分析结果对比服务
2. 变盘检测算法（基于AI结果对比）
3. 高频模式动态调度
4. 桌面通知系统（Windows/Mac/Linux）

### Phase 6: 实时监控面板
1. 自选股实时行情展示
2. 分析状态指示器
3. 变盘信号历史记录
4. 通知设置管理

---

## 数据模型

### Watchlist 模型
```python
class Watchlist(Base):
    __tablename__ = "watchlist"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)  # 股票代码
    name = Column(String(100))  # 股票名称
    exchange = Column(String(10))  # 交易所
    added_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)  # 是否启用监控
    
    # 变盘检测配置
    turning_detection_enabled = Column(Boolean, default=True)  # 是否启用变盘检测
    confidence_jump_threshold = Column(Float, default=0.15)  # 置信度跳跃阈值(15%)
    
    # 当前状态（来自最后一次分析）
    last_analysis_at = Column(DateTime)
    last_signal = Column(String(10))  # 当前信号: BUY/SELL/HOLD
    last_confidence = Column(Float)  # 当前置信度
    last_risk_level = Column(String(20))  # 当前风险等级
    
    # 运行时状态
    is_high_frequency = Column(Boolean, default=False)  # 是否在高频模式
    high_freq_until = Column(DateTime)  # 高频模式结束时间
    last_price = Column(Float)
    last_change_pct = Column(Float)
    
    # 关联分析任务
    analyses = relationship("WatchlistAnalysis", back_populates="watchlist")
```

### WatchlistAnalysis 模型
```python
class WatchlistAnalysis(Base):
    __tablename__ = "watchlist_analyses"
    
    id = Column(Integer, primary_key=True)
    watchlist_id = Column(Integer, ForeignKey("watchlist.id"))
    analysis_id = Column(String(36), ForeignKey("analysis_tasks.task_id"))
    
    analysis_type = Column(String(20))  # 'full', 'quick', 'turning'
    triggered_by = Column(String(20))  # 'scheduled', 'turning', 'manual'
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    # 分析结果
    signal = Column(String(10))  # BUY, SELL, HOLD
    confidence = Column(Float)
    risk_level = Column(String(20))  # low, medium, high
    
    # 变盘检测（与前一次分析对比）
    is_turning_point = Column(Boolean, default=False)  # 是否为变盘
    turning_reason = Column(Text)  # 变盘原因描述
    importance_score = Column(Float)  # 重要性评分 (0-1)
    
    # 通知状态
    alert_sent = Column(Boolean, default=False)
    alert_sent_at = Column(DateTime)
    
    watchlist = relationship("Watchlist", back_populates="analyses")
```

---

## API 端点

```python
# 自选股管理
POST   /api/v1/watchlist/                     # 添加自选股
GET    /api/v1/watchlist/                      # 获取自选股列表
GET    /api/v1/watchlist/{id}                  # 获取单个自选股详情
PUT    /api/v1/watchlist/{id}                  # 更新自选股设置
DELETE /api/v1/watchlist/{id}                  # 删除自选股

# 分析与监控
POST   /api/v1/watchlist/analyze               # 手动触发分析
POST   /api/v1/watchlist/{id}/quick-analyze    # 触发快速分析 (Fast Mode)
GET    /api/v1/watchlist/analysis              # 获取分析历史
GET    /api/v1/watchlist/alerts                # 获取变盘信号
POST   /api/v1/watchlist/detect-turning        # 执行变盘检测 (输入当前/上一次结果)

# 定时任务
GET    /api/v1/scheduler/status                # 获取调度器状态
POST   /api/v1/scheduler/trigger/{job_id}      # 手动触发任务 (测试用)

# 实时监控
GET    /api/v1/watchlist/realtime              # 获取实时行情
WS     /ws/watchlist                           # WebSocket实时推送
```

---

## 变盘检测算法

def detect_turning_point(
    current_result: Dict,
    previous_result: Dict,
    config: Dict = None
) -> Tuple[bool, str, float]:
    """
    基于AI分析结果检测是否出现变盘信号
    
    Returns:
        (is_turning, reason, importance_score)
        - is_turning: 是否判定为变盘
        - reason: 变盘原因描述
        - importance_score: 重要性评分 (0-1)
    """
    if not current_result or not previous_result:
        return False, "", 0.0
    
    config = config or {}
    confidence_threshold = config.get('confidence_jump', 0.15)  # 置信度跳跃阈值
    
    current_signal = current_result.get('signal', 'UNKNOWN')
    previous_signal = previous_result.get('signal', 'UNKNOWN')
    current_conf = current_result.get('confidence', 0)
    previous_conf = previous_result.get('confidence', 0)
    current_risk = current_result.get('risk_level', 'medium')
    previous_risk = previous_result.get('risk_level', 'medium')
    
    turning_signals = []
    importance = 0.0
    
    # 1. 信号转变检测 (最重要)
    if current_signal != previous_signal and current_signal in ['BUY', 'SELL']:
        if previous_signal in ['SELL', 'BUY'] or (previous_signal == 'HOLD' and current_conf > 0.75):
            turning_signals.append(f"信号转变: {previous_signal} → {current_signal}")
            importance += 0.9
    
    # 2. 置信度突破检测
    conf_jump = current_conf - previous_conf
    if conf_jump >= confidence_threshold and current_conf > 0.8:
        turning_signals.append(f"置信度突破: {previous_conf:.0%} → {current_conf:.0%}")
        importance += 0.6
    
    # 3. 风险等级变化检测
    risk_levels = {'low': 1, 'medium': 2, 'high': 3}
    if risk_levels.get(current_risk, 2) != risk_levels.get(previous_risk, 2):
        if risk_levels.get(current_risk, 2) > risk_levels.get(previous_risk, 2):
            turning_signals.append(f"风险上升: {previous_risk} → {current_risk}")
            importance += 0.4
        else:
            turning_signals.append(f"风险下降: {previous_risk} → {current_risk}")
            importance += 0.3
    
    # 4. 紧急信号检测（市场异常）
    market_alert = current_result.get('market_alert', '')
    if market_alert and '异常' in market_alert:
        turning_signals.append(f"市场警报: {market_alert}")
        importance += 0.95
    
    # 综合判定
    is_turning = importance >= 0.5 or len(turning_signals) >= 2
    
    reason = " | ".join(turning_signals) if turning_signals else "无显著变化"
    
    return is_turning, reason, min(importance, 1.0)


def should_use_high_frequency(
    recent_results: List[Dict],
    stable_threshold: int = 3
) -> bool:
    """
    判定是否应该继续使用高频分析模式
    
    逻辑：
    - 最近N次分析结果都一致（稳定），恢复低频
    - 否则继续高频
    """
    if len(recent_results) < stable_threshold:
        return True  # 数据不足，继续高频
    
    recent_signals = [r.get('signal') for r in recent_results[-stable_threshold:]]
    recent_confs = [r.get('confidence', 0) for r in recent_results[-stable_threshold:]]
    
    # 信号一致且置信度稳定（变化<10%）
    signals_stable = len(set(recent_signals)) == 1
    confs_stable = max(recent_confs) - min(recent_confs) < 0.1
    
    return not (signals_stable and confs_stable)
```

---

## 定时任务配置

```python
# 凌晨全局分析（每天 02:00）
scheduler.add_job(
    full_analysis_job,
    CronTrigger(hour=2, minute=0),
    id="watchlist_full_analysis"
)

# 上午交易时间快速分析（9:20-11:30）
# 正常模式：每5分钟，变盘模式：每2分钟
scheduler.add_job(
    quick_analysis_job,
    CronTrigger(
        hour="9-11",
        minute="20,25,30,35,40,45,50,55",
        day_of_week="mon-fri"
    ),
    id="watchlist_morning_quick"
)

# 下午交易时间快速分析（13:00-15:00）
scheduler.add_job(
    quick_analysis_job,
    CronTrigger(
        hour="13-14",
        minute="0,5,10,15,20,25,30,35,40,45,50,55",
        day_of_week="mon-fri"
    ),
    id="watchlist_afternoon_quick"
)

# 高频分析任务（批量扫描模式）
# 每2分钟检查所有处于高频模式的股票，而不是每只股票一个任务
scheduler.add_job(
    high_frequency_batch_job,  # 批量处理所有高频模式股票
    IntervalTrigger(minutes=2),
    id="watchlist_high_freq_batch",
    max_instances=1
)

# high_frequency_batch_job 实现逻辑:
# def high_frequency_batch_job():
#     # 查询所有 is_high_frequency=True 且未过期的watchlist
#     active_watchlists = db.query(Watchlist).filter(
#         Watchlist.is_high_frequency == True,
#         Watchlist.high_freq_until > datetime.utcnow()
#     ).all()
#     
#     # 串行或并行触发快速分析（根据系统负载决定）
#     for wl in active_watchlists:
#         trigger_quick_analysis(wl.id)
```

**高频模式触发逻辑**：
```python
def on_analysis_complete(watchlist_id: int, result: Dict):
    """每次分析完成后执行的回调"""
    # 1. 获取上一次分析结果
    previous = get_last_analysis_result(watchlist_id)
    
    # 2. 执行变盘检测
    is_turning, reason, importance = detect_turning_point(result, previous)
    
    if is_turning:
        # 3. 发送变盘通知
        send_turning_alert(watchlist_id, result, reason, importance)
        
        # 4. 激活高频模式（如果未激活）
        activate_high_frequency_mode(watchlist_id, duration_minutes=10)
        
        # 5. 记录变盘信号
        save_turning_signal(watchlist_id, result, reason, importance)
    
    # 6. 检查是否应该恢复低频
    if is_high_frequency_mode(watchlist_id):
        recent = get_recent_results(watchlist_id, count=3)
        if should_use_high_frequency(recent, stable_threshold=3):
            continue_high_freq = True
        else:
            deactivate_high_frequency_mode(watchlist_id)

---

## 桌面通知实现

### 变盘通知内容模板

```python
def format_turning_alert(symbol: str, name: str, result: Dict, reason: str, importance: float) -> str:
    """格式化变盘通知内容"""
    signal = result.get('signal', 'UNKNOWN')
    confidence = result.get('confidence', 0)
    
    # 信号表情
    signal_emoji = {'BUY': '🟢', 'SELL': '🔴', 'HOLD': '🟡'}.get(signal, '⚪')
    
    # 重要性指示
    importance_indicator = '🔥' if importance > 0.9 else '⚡' if importance > 0.7 else '📊'
    
    title = f"{importance_indicator} 变盘信号 - {name} ({symbol})"
    message = f"{signal_emoji} {signal} (置信度{confidence:.0%})\n📌 {reason}"
    
    return title, message


# Windows
from win10toast import ToastNotifier
toaster = ToastNotifier()
title, message = format_turning_alert("000001", "平安银行", result, reason, importance)
toaster.show_toast(title, message, duration=15, threaded=True)

# Mac
import os
title, message = format_turning_alert("000001", "平安银行", result, reason, importance)
os.system(f'''
    osascript -e 'display notification "{message}" with title "{title}" sound name "Glass"'
''')

# Linux
import subprocess
title, message = format_turning_alert("000001", "平安银行", result, reason, importance)
subprocess.run([
    "notify-send",
    "-u", "critical" if importance > 0.8 else "normal",
    title,
    message
])
```

---

## 快速分析模式 (Fast Mode)

**实现方式**：通过 `AnalysisRunner` 的 `fast_mode` 参数启用，**不是**创建新的3-agent Graph。

### Fast Mode 机制
```python
# 在 analysis_runner.py 中
class AnalysisRunner:
    def __init__(self, ..., fast_mode: bool = False):
        self.fast_mode = fast_mode
    
    def run(self, symbol: str, date: str):
        if self.fast_mode:
            # 跳过耗时节点：bull_researcher, bear_researcher debate
            # 简化 risk_manager 和 portfolio_manager 调用
            # 预计时间：20-30秒 (vs 完整分析 3-5分钟)
            pass
```

### Fast Mode vs 完整分析对比

| 特性 | Fast Mode | 完整分析 |
|------|-----------|---------|
| 执行节点 | market → sentiment → news → fundamentals → trader → portfolio | 所有节点 |
| Researcher Debate | ❌ 跳过 | ✅ 执行 |
| Detailed Risk | ❌ 简化 | ✅ 完整 |
| 预计时间 | 20-30秒 | 3-5分钟 |
| 适用场景 | 实时监控 | 深度分析 |

---

## 页面设计

### 自选股管理页面布局
```
┌──────────────────────────────────────────────────────────────┐
│  📊 自选股实时监控 - AI驱动变盘检测                              │
├──────────────────────────────────────────────────────────────┤
│  [🔍 搜索股票...] [➕ 添加自选股]                               │
├──────────────────────────────────────────────────────────────┤
│  📋 自选股列表 (每5分钟AI分析，变盘时2分钟高频)                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 代码    名称      价格    涨跌    AI信号      下次分析 │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ 000001  平安银行  ¥10.50  +2.1%   🟢买入(87%)  ⏱️2分钟│  │
│  │ 000858  五粮液    ¥158.2  -0.5%   🟡持有(62%)  ⏱️5分钟│  │
│  │ 600519  贵州茅台  ¥1688   +1.2%   🔴卖出(91%)  ⚡变盘 │  │
│  │                                                      🔥 │  │
│  └────────────────────────────────────────────────────────┘  │
│  [▶️ 开始监控] [⏸️ 停止] [🔄 立即分析全部]                      │
├──────────────────────────────────────────────────────────────┤
│  📈 实时监控面板 - 价格走势与AI信号关联                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                                                      │  │
│  │    价格 ─┬─╮    ╭─╮        ╭───🔥变盘信号           │  │
│  │         │  ╰────╯ ╰────────╯    (BUY→SELL)          │  │
│  │                                                      │  │
│  │    AI ──┴─╮    ╭─╯        ╭───置信度92%             │  │
│  │    信号   ╰────╯          ╯                         │  │
│  │                                                      │  │
│  └────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│  🔔 变盘信号历史 (基于AI分析结果对比)                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 🔥 10:35 平安银行  信号转变: BUY→SELL  置信度87%      │  │
│  │ 📊 10:30 五粮液    风险上升: low→high   需关注       │  │
│  │ ⚡ 10:25 贵州茅台  置信度突破: 65%→91%  强烈信号     │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**列表状态说明**：
- 🟢买入/🔴卖出/🟡持有 - 当前AI分析信号
- 括号内数字 - AI置信度百分比
- ⏱️2分钟/⏱️5分钟 - 下次分析倒计时
- ⚡变盘 - 刚检测到变盘，进入高频分析模式
- 🔥 - 高重要性变盘信号（重要性>0.9）

---

## 执行计划

| Phase | 任务 | 预计时间 | 依赖 |
|-------|------|---------|------|
| 1 | 数据模型与API | 2h | - |
| 2 | 自选股管理页面 | 3h | Phase 1 |
| 3 | 快速分析模式 | 4h | Phase 1 |
| 4 | 定时任务调度 | 3h | Phase 3 |
| 5 | 变盘检测与通知 | 4h | Phase 4 |
| 6 | 实时监控面板 | 3h | Phase 2,5 |
| **总计** | | **19h** | |

建议分2-3天完成。

---

## QA 测试场景 (可执行验证)

每个 Phase 完成后必须执行以下验证场景。

### Phase 1: 数据模型与API

**场景 1.1: 添加自选股**
- **工具**: Bash (curl)
- **步骤**:
  1. `curl -X POST http://localhost:8000/api/v1/watchlist/ -H "Content-Type: application/json" -d '{"symbol":"000001","name":"平安银行","exchange":"SZ"}'`
- **期望结果**: HTTP 201, 返回包含 `id`, `symbol`, `is_active=true` 的JSON
- **验证**: `response.id > 0 && response.symbol == "000001"`

**场景 1.2: 获取自选股列表**
- **工具**: Bash (curl)
- **步骤**:
  1. `curl http://localhost:8000/api/v1/watchlist/`
- **期望结果**: HTTP 200, 返回列表包含刚添加的股票
- **验证**: `response.length >= 1 && response[0].symbol == "000001"`

**场景 1.3: 数据库持久化验证**
- **工具**: Bash (psql)
- **步骤**:
  1. `psql -U trading -d trading_db -c "SELECT symbol, name FROM watchlist WHERE symbol='000001';"`
- **期望结果**: 查询返回一行数据，symbol=000001
- **验证**: 行数 == 1

---

### Phase 2: 自选股管理页面

**场景 2.1: 页面渲染**
- **工具**: Playwright
- **步骤**:
  1. 打开 `http://localhost:8501`
  2. 点击侧边栏 "📊 自选股管理"
  3. 等待页面加载 (timeout=10s)
- **期望结果**: 页面显示 "📊 自选股实时监控" 标题
- **验证**: `page.locator("text=自选股实时监控").is_visible() == true`
- **证据**: 截图保存到 `.sisyphus/evidence/p2-watchlist-page.png`

**场景 2.2: 添加股票交互**
- **工具**: Playwright
- **步骤**:
  1. 在搜索框输入 "000001"
  2. 点击 "搜索" 按钮
  3. 等待搜索结果出现 (timeout=5s)
  4. 点击结果中的 "➕ 添加" 按钮
- **期望结果**: 股票添加到列表，显示 "平安银行"
- **验证**: `page.locator("text=平安银行").is_visible() == true`
- **证据**: 截图保存到 `.sisyphus/evidence/p2-add-stock.png`

**场景 2.3: 删除股票**
- **工具**: Playwright
- **步骤**:
  1. 在股票列表中找到 "平安银行"
  2. 点击该行 "🗑️" 删除按钮
  3. 确认删除对话框点击 "确定"
- **期望结果**: 股票从列表中消失
- **验证**: `page.locator("text=平安银行").is_visible() == false`
- **证据**: 截图保存到 `.sisyphus/evidence/p2-delete-stock.png`

---

### Phase 3: 快速分析模式

**场景 3.1: Fast Mode API 调用**
- **工具**: Bash (curl)
- **步骤**:
  1. `curl -X POST http://localhost:8000/api/v1/watchlist/1/quick-analyze -H "Content-Type: application/json"`
- **期望结果**: HTTP 202 (Accepted), 返回 `task_id` 和 `status=RUNNING`
- **验证**: `response.status == "RUNNING" && response.task_id != null`

**场景 3.2: Fast Mode 执行时间**
- **工具**: Bash (curl + time)
- **步骤**:
  1. 记录开始时间 `start=$(date +%s)`
  2. 调用快速分析 API
  3. 轮询任务状态直到 `COMPLETED` 或 `FAILED`
  4. 记录结束时间 `end=$(date +%s)`
- **期望结果**: 总时间 < 60秒
- **验证**: `(end - start) < 60`
- **证据**: 时间数据保存到 `.sisyphus/evidence/p3-fast-mode-timing.json`

**场景 3.3: Fast Mode 结果完整性**
- **工具**: Bash (curl)
- **步骤**:
  1. 获取快速分析结果 `curl http://localhost:8000/api/v1/analysis/{task_id}`
- **期望结果**: 结果包含 `signal`, `confidence`, `risk_level` 字段
- **验证**: `response.result.signal in ['BUY', 'SELL', 'HOLD'] && response.result.confidence > 0`

**场景 3.4: Fast Mode 跳过 Debate 节点**
- **工具**: Bash (curl)
- **步骤**:
  1. 执行快速分析并获取 `task_id`
  2. 轮询直到完成 `curl http://localhost:8000/api/v1/analysis/{task_id}`
  3. 检查结果中的 `logs` 字段
- **期望结果**: 日志中不包含 `bull_researcher` 和 `bear_researcher` 节点的执行记录
- **验证**: `'bull_researcher' not in str(response.logs) && 'bear_researcher' not in str(response.logs)`

---

### Phase 4: 定时任务调度

**场景 4.1: APScheduler 启动验证**
- **工具**: Bash (curl)
- **步骤**:
  1. `curl http://localhost:8000/api/v1/scheduler/status`
- **期望结果**: 返回 `status=running`, `jobs_count >= 3`
- **验证**: `response.status == "running" && response.jobs_count >= 3`

**场景 4.2: 定时任务触发验证**
- **工具**: Bash (curl)
- **步骤**:
  1. 手动触发分析任务 (使用测试API) `curl -X POST http://localhost:8000/api/v1/scheduler/trigger/watchlist_morning_quick`
  2. 等待 5 秒
  3. 查询分析任务列表 `curl http://localhost:8000/api/v1/watchlist/analysis`
- **期望结果**: 新任务自动创建，analysis_type='quick'
- **验证**: 列表中出现新的 `quick` 类型任务
- **证据**: 任务列表保存到 `.sisyphus/evidence/p4-scheduled-tasks.json`

**场景 4.2b: 定时任务配置验证 (开发时)**
- **工具**: Python (单元测试)
- **文件**: `tests/unit/test_scheduler.py`
- **步骤**:
  1. 在 `.env.test` 中设置 `SCHEDULER_TEST_MODE=true` 和 `SCHEDULER_INTERVAL_MINUTES=1`
  2. 启动调度器 `python -m webapi.scheduler`
  3. 运行测试 `pytest tests/unit/test_scheduler.py::test_scheduler_trigger -v`
- **期望结果**: 测试通过，任务每分钟触发一次
- **验证**: 测试返回 `PASSED`

**场景 4.3: 高频模式批量扫描**
- **工具**: Bash (curl)
- **前提**: 将某股票设置为高频模式 `is_high_frequency=true`
- **步骤**:
  1. 等待 2 分钟 (高频扫描间隔)
  2. 查询该股票的分析任务列表
- **期望结果**: 出现新的 `analysis_type='quick'` 任务
- **验证**: 任务列表长度 > 之前的长度

---

### Phase 5: 变盘检测与通知

**场景 5.1: 信号转变检测 (BUY → SELL)**
- **工具**: Bash (curl)
- **步骤**:
  1. 构造请求体 `{"current_result": {"signal": "SELL", "confidence": 0.85}, "previous_result": {"signal": "BUY", "confidence": 0.7}}`
  2. 调用变盘检测 API `curl -X POST http://localhost:8000/api/v1/watchlist/detect-turning -H "Content-Type: application/json" -d '{...}'`
- **期望结果**: 返回 `is_turning=true`, `importance_score >= 0.9`
- **验证**: `response.is_turning == true && response.importance_score >= 0.9`

**场景 5.2: 置信度突破检测**
- **工具**: Bash (curl)
- **步骤**:
  1. 构造请求体 `{"current_result": {"signal": "BUY", "confidence": 0.88}, "previous_result": {"signal": "BUY", "confidence": 0.6}}`
  2. 调用变盘检测 API `curl -X POST http://localhost:8000/api/v1/watchlist/detect-turning -H "Content-Type: application/json" -d '{...}'`
- **期望结果**: 返回 `is_turning=true`, `turning_reason` 包含 "置信度突破"
- **验证**: `'置信度突破' in response.turning_reason`

**场景 5.3: 高频模式触发**
- **工具**: Bash (curl)
- **步骤**:
  1. 构造请求体触发信号转变 (BUY→SELL) 并调用变盘检测 API
  2. 立即查询自选股状态 `curl http://localhost:8000/api/v1/watchlist/1`
- **期望结果**: `is_high_frequency=true`, `high_freq_until` 为未来时间
- **验证**: `response.is_high_frequency == true && response.high_freq_until > now()`

**场景 5.4: 高频模式自动恢复 (单元测试)**
- **工具**: Python (单元测试)
- **文件**: `tests/unit/test_turning_detection.py`
- **步骤**:
  1. 准备最近 3 次分析结果 (信号一致, 置信度稳定)
  2. 调用 `should_use_high_frequency(recent_results, stable_threshold=3)`
- **期望结果**: 返回 `False` (应该恢复低频)
- **验证**: `result == false`
- **执行**: `pytest tests/unit/test_turning_detection.py::test_should_use_high_frequency -v`

**场景 5.5: 桌面通知发送 (Windows)**
- **工具**: Bash (Python)
- **步骤**:
  1. 在 Windows 环境运行: `python -c "from win10toast import ToastNotifier; ToastNotifier().show_toast('Test', 'Message', duration=3)"`
- **期望结果**: 系统右下角显示通知气泡
- **验证**: 肉眼验证 (或通过 pyautogui 截图验证)
- **证据**: 截图保存到 `.sisyphus/evidence/p5-notification.png`

---

### Phase 6: 实时监控面板

**场景 6.1: 实时行情显示**
- **工具**: Playwright
- **步骤**:
  1. 打开自选股管理页面
  2. 观察列表中的价格列
  3. 等待 10 秒
- **期望结果**: 价格数据从 "加载中..." 变为具体数值
- **验证**: `page.locator('.price-column').first.text_content() != "加载中..."`
- **证据**: 截图保存到 `.sisyphus/evidence/p6-realtime-price.png`

**场景 6.2: AI 信号显示**
- **工具**: Playwright
- **前提**: 某股票已完成至少一次分析
- **步骤**:
  1. 打开自选股管理页面
  2. 查看 AI 信号列
- **期望结果**: 显示 🟢买入/🔴卖出/🟡持有 + 置信度百分比
- **验证**: `page.locator('.signal-badge').first.text_content()` 匹配正则 `[🟢🔴🟡].+\(\d+%\)`

**场景 6.3: 变盘信号高亮**
- **工具**: Playwright
- **前提**: 某股票处于变盘状态
- **步骤**:
  1. 打开自选股管理页面
  2. 查看处于变盘状态的股票行
- **期望结果**: 行背景高亮显示 ⚡ 变盘图标
- **验证**: `page.locator('.turning-highlight').is_visible() == true`
- **证据**: 截图保存到 `.sisyphus/evidence/p6-turning-highlight.png`

**场景 6.4: 下次分析倒计时**
- **工具**: Playwright
- **步骤**:
  1. 打开自选股管理页面
  2. 查看 "下次分析" 列
  3. 等待 10 秒
  4. 再次查看同一位置
- **期望结果**: 倒计时数字减少 (如 "⏱️4分钟" → "⏱️3分钟")
- **验证**: 第二次读数 < 第一次读数

**场景 6.5: 变盘信号历史记录**
- **工具**: Playwright
- **前提**: 系统已记录至少一次变盘
- **步骤**:
  1. 打开自选股管理页面
  2. 滚动到 "🔔 变盘信号历史" 区域
- **期望结果**: 显示历史变盘记录列表，包含时间、股票、原因
- **验证**: `page.locator('.turning-history-item').count() >= 1`
- **证据**: 截图保存到 `.sisyphus/evidence/p6-turning-history.png`

---

### 集成测试场景

**场景 E2E.1: 完整流程验证**
- **工具**: Playwright + Bash (curl)
- **步骤**:
  1. 添加股票 "000001" 到自选股
  2. 手动触发一次快速分析
  3. 等待分析完成 (最长 60 秒)
  4. Mock 变盘检测 (修改上一次结果为相反信号)
  5. 再次触发分析
  6. 观察变盘通知是否发送
  7. 验证高频模式是否激活
- **期望结果**: 
  - 分析完成
  - 变盘被检测
  - 通知发送
  - 高频模式激活
- **证据**: 
  - 截图: `.sisyphus/evidence/e2e-full-flow.png`
  - 日志: `.sisyphus/evidence/e2e-full-flow.log`

**场景 E2E.2: 性能压力测试**
- **工具**: Bash (curl)
- **步骤**:
  1. 批量添加 10 只股票到自选股
  2. 同时触发所有股票的快速分析
  3. 监控 API 响应时间和任务完成时间
- **期望结果**: 
  - API 响应时间 < 1秒
  - 所有任务在 2 分钟内完成
- **验证**: 
  - `avg_response_time < 1000ms`
  - `max_completion_time < 120000ms`
- **证据**: 性能数据保存到 `.sisyphus/evidence/e2e-performance.json`

---

## 验证清单总结

| Phase | 场景数 | 关键验证点 |
|-------|-------|-----------|
| Phase 1 | 3 | API + 数据库 |
| Phase 2 | 3 | UI 交互 |
| Phase 3 | 4 | Fast Mode 功能 |
| Phase 4 | 3 | 定时任务调度 |
| Phase 5 | 5 | 变盘检测 + 通知 |
| Phase 6 | 5 | 实时监控面板 |
| E2E | 2 | 集成 + 性能 |
| **总计** | **25** | |

**执行要求**:
- 每个 Phase 完成时，执行该 Phase 的所有场景
- 所有场景通过后才能进入下一 Phase
- 失败场景需修复后重新验证
- 截图和日志必须保存到 `.sisyphus/evidence/` 目录
