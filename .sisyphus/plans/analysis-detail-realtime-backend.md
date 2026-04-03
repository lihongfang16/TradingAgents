# Plan: Backend Support for Real-time Analysis Steps (方案A)

## Overview
Extend backend to support real-time progress tracking with 10 detailed agent steps for the analysis detail page.

## Current State
- `AnalysisRunner.run()` executes synchronously without progress callbacks
- `db_task.result` is only written after completion
- Only 3 high-level progress steps exist (graph_setup, propagate, signal_processing)
- UI detail page cannot access real-time progress data

## Target State
- AnalysisRunner reports progress via callback during execution
- Database stores real-time progress (agents_progress, current_agent, progress_pct)
- 10 detailed agent steps tracked throughout execution
- API returns live progress data for running tasks

## Detailed Implementation Plan

---

### Phase 1: Database Schema Update

**File**: `webapi/models/database.py`

Add fields to AnalysisTask model:
- `agents_progress` (JSONB) - Dict mapping agent_id to status
- `current_agent` (String) - Currently executing agent
- `progress_pct` (Integer) - Overall progress percentage
- `logs` (JSONB) - List of log entries with timestamps

```python
class AnalysisTask(Base):
    # ... existing fields ...
    
    # Real-time progress fields (NEW)
    agents_progress = Column(JSONB, nullable=True, default=dict)
    current_agent = Column(String(50), nullable=True)
    progress_pct = Column(Integer, nullable=True, default=0)
    logs = Column(JSONB, nullable=True, default=list)
```

**Alembic Migration**:
- Create migration to add new columns
- Set default values for existing records

---

### Phase 2: AnalysisRunner Enhancement

**File**: `tradingagents/core/analysis_runner.py`

#### 2.1 Add Callback Support

Add `progress_callback` parameter to `__init__`:

```python
def __init__(
    self,
    symbol: str,
    date: str,
    analysts: List[str],
    llm_model: str,
    llm_provider: str,
    initial_cash: float = 100000.0,
    max_iterations: int = 300,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,  # NEW
):
```

#### 2.2 Define Agent Step Mapping

Create mapping from internal execution to UI steps:

```python
AGENT_STEPS = [
    ("graph_setup", "🚀", "初始化分析图"),
    ("market_analyst", "📊", "市场分析师"),
    ("sentiment_analyst", "💭", "情绪分析师"),
    ("news_analyst", "📰", "新闻分析师"),
    ("fundamentals_analyst", "🏢", "基本面分析师"),
    ("bull_researcher", "🐂", "看涨研究员"),
    ("bear_researcher", "🐻", "看跌研究员"),
    ("trader", "💼", "交易员"),
    ("risk_manager", "⚠️", "风控经理"),
    ("portfolio_manager", "👔", "投资组合经理"),
]
```

#### 2.3 Instrument Graph Execution

Modify `run()` method to track each agent:

```python
def run(self) -> Dict[str, Any]:
    # Initialize all steps as "not_started"
    agents_progress = {step_id: "not_started" for step_id, _, _ in AGENT_STEPS}
    
    # Step 1: graph_setup
    agents_progress["graph_setup"] = "in_progress"
    self._report_progress(agents_progress, "graph_setup", 10)
    
    # Build graph
    graph = self.graph
    agents_progress["graph_setup"] = "completed"
    
    # Step 2-5: Analysts execute in parallel or sequence
    for analyst in self.analysts:
        agents_progress[f"{analyst}_analyst"] = "in_progress"
        self._report_progress(agents_progress, f"{analyst}_analyst", ...)
        # Execute analyst
        agents_progress[f"{analyst}_analyst"] = "completed"
    
    # Step 6-7: Researchers (bull/bear)
    agents_progress["bull_researcher"] = "in_progress"
    # ... execute
    agents_progress["bull_researcher"] = "completed"
    
    agents_progress["bear_researcher"] = "in_progress"
    # ... execute
    agents_progress["bear_researcher"] = "completed"
    
    # Step 8: Trader
    agents_progress["trader"] = "in_progress"
    # ... execute
    agents_progress["trader"] = "completed"
    
    # Step 9: Risk Manager
    agents_progress["risk_manager"] = "in_progress"
    # ... execute
    agents_progress["risk_manager"] = "completed"
    
    # Step 10: Portfolio Manager
    agents_progress["portfolio_manager"] = "in_progress"
    # ... execute
    agents_progress["portfolio_manager"] = "completed"
    
    return result

def _report_progress(self, agents_progress: Dict, current_agent: str, progress_pct: int):
    """Report progress via callback if provided."""
    if self.progress_callback:
        self.progress_callback({
            "agents_progress": agents_progress.copy(),
            "current_agent": current_agent,
            "progress_pct": progress_pct,
            "timestamp": datetime.now().isoformat(),
        })
```

---

### Phase 3: AnalysisService Integration

**File**: `webapi/services/analysis_service.py`

#### 3.1 Progress Callback Handler

Add method to handle progress updates:

```python
def _update_task_progress(self, task_id: str, progress_data: Dict[str, Any]):
    """Update task progress in database."""
    db = SessionLocal()
    try:
        db_task = db.query(AnalysisTask).filter(
            AnalysisTask.task_id == task_id
        ).first()
        if db_task:
            db_task.agents_progress = progress_data.get("agents_progress", {})
            db_task.current_agent = progress_data.get("current_agent", "")
            db_task.progress_pct = progress_data.get("progress_pct", 0)
            db_task.updated_at = datetime.utcnow()
            
            # Append to logs
            logs = db_task.logs or []
            logs.append({
                "timestamp": progress_data.get("timestamp"),
                "agent": progress_data.get("current_agent"),
                "progress": progress_data.get("progress_pct"),
            })
            db_task.logs = logs
            
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error updating progress: {e}")
    finally:
        db.close()
```

#### 3.2 Modify Analysis Execution

Update `_run_sync_analysis` to pass callback:

```python
def _run_sync_analysis(self, task_id: str, request: AnalysisRequest) -> Dict[str, Any]:
    """Run analysis synchronously with progress tracking."""
    # ... existing code ...
    
    # Create runner with progress callback
    runner = AnalysisRunner(
        symbol=symbol,
        date=date,
        analysts=analysts,
        llm_model=llm_model,
        llm_provider=llm_provider,
        max_iterations=300,
        base_url=base_url,
        api_key=api_key,
        progress_callback=lambda data: self._update_task_progress(task_id, data),  # NEW
    )
    
    # Run analysis
    result = runner.run()
    return result
```

#### 3.3 Update get_task to Return Progress

Modify `get_task` to include progress fields:

```python
def get_task(self, task_id: str) -> Optional[AnalysisResponse]:
    """Get task by ID with progress information."""
    # ... existing code ...
    
    # Build response with progress data
    return AnalysisResponse(
        task_id=db_task.task_id,
        status=AnalysisStatus(db_task.status),
        symbol=db_task.symbol,
        # ... other fields ...
        result={
            # ... existing result fields ...
            "agents_progress": db_task.agents_progress or {},
            "current_agent": db_task.current_agent or "",
            "progress_pct": db_task.progress_pct or 0,
        } if db_task.status in (AnalysisStatus.PENDING, AnalysisStatus.RUNNING) else db_task.result,
    )
```

---

### Phase 4: API Response Update

**File**: `webapi/models/analysis.py`

Update AnalysisResponse model to include progress fields in result:

```python
class AnalysisResponse(BaseModel):
    task_id: str
    status: AnalysisStatus
    symbol: str
    message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    logs: List[str] = []
    
    # Progress fields (populated when task is running)
    agents_progress: Optional[Dict[str, str]] = None
    current_agent: Optional[str] = None
    progress_pct: Optional[int] = None
```

---

### Phase 5: Testing

#### 5.1 Unit Tests

Test progress callback mechanism:

```python
def test_progress_callback():
    progress_updates = []
    
    def callback(data):
        progress_updates.append(data)
    
    runner = AnalysisRunner(
        symbol="000001",
        date="2026-03-26",
        analysts=["market"],
        llm_model="gpt-4",
        llm_provider="openai",
        progress_callback=callback,
    )
    
    result = runner.run()
    
    # Verify progress was reported
    assert len(progress_updates) > 0
    assert "agents_progress" in progress_updates[0]
    assert "current_agent" in progress_updates[0]
    assert "progress_pct" in progress_updates[0]
```

#### 5.2 Integration Tests

Test end-to-end flow:

```python
def test_analysis_progress_tracking():
    # Create task
    task = analysis_service.create_task(request)
    
    # Start analysis
    asyncio.create_task(analysis_service.run_analysis(task.task_id, request))
    
    # Wait a bit
    await asyncio.sleep(1)
    
    # Get task - should have progress
    updated_task = analysis_service.get_task(task.task_id)
    assert updated_task.progress_pct > 0
    assert updated_task.current_agent is not None
    assert len(updated_task.agents_progress) > 0
```

---

### Phase 6: Frontend Verification

Verify UI displays correctly:

1. Create new analysis
2. Navigate to detail page immediately
3. Confirm 10 steps are displayed
4. Confirm current step is highlighted
5. Confirm progress bar updates
6. Confirm logs appear
7. Wait for completion
8. Verify completed state displays correctly

---

## TODOs

- [ ] 1. Create Alembic migration for new database columns
- [ ] 2. Modify AnalysisRunner to accept progress_callback parameter
- [ ] 3. Add AGENT_STEPS mapping and _report_progress method
- [ ] 4. Instrument all 10 agent steps in run() method
- [ ] 5. Add _update_task_progress method to AnalysisService
- [ ] 6. Modify _run_sync_analysis to pass callback to runner
- [ ] 7. Update get_task to return progress fields
- [ ] 8. Update AnalysisResponse model
- [ ] 9. Write unit tests for progress callback
- [ ] 10. Write integration tests for progress tracking
- [ ] 11. Run full test suite
- [ ] 12. Verify UI functionality

---

## Success Criteria

- [ ] New database columns created and migrated
- [ ] AnalysisRunner reports progress for all 10 steps
- [ ] Database stores real-time progress during execution
- [ ] API returns progress data for running tasks
- [ ] UI detail page displays 10 steps with correct status
- [ ] Progress bar updates in real-time
- [ ] Logs show agent execution history
- [ ] All tests pass

## Estimated Effort

**Total**: 2-3 hours
- Phase 1 (DB): 20 min
- Phase 2 (Runner): 40 min
- Phase 3 (Service): 30 min
- Phase 4 (API): 15 min
- Phase 5 (Tests): 30 min
- Phase 6 (Verify): 15 min
