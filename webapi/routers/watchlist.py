"""
Watchlist Router for TradingAgents API
"""

# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportImportCycles=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportCallInDefaultInitializer=false, reportUnusedCallResult=false, reportDeprecated=false, reportUnusedFunction=false, reportUnannotatedClassAttribute=false, reportUnusedParameter=false
import sys
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
import asyncio

from webapi.config.database import get_db
from webapi.models.database import Watchlist, WatchlistAnalysis, WatchlistConfig
from webapi.models.analysis import AnalysisRequest, AnalysisResponse, StockExchange, AnalysisHistoryResponse, AnalysisHistoryItem

# Lazy import analysis_service to avoid slow startup
def get_analysis_service():
    from webapi.services.analysis_service import analysis_service
    return analysis_service


def get_scheduler_service():
    from webapi.services.scheduler_service import scheduler_service
    return scheduler_service


def _normalize_analysis_signal(raw_signal: Any) -> tuple[Optional[str], Optional[float]]:
    """Normalize runner signal payload into persisted signal/confidence values."""
    confidence_value: Optional[float] = None
    signal_value: Optional[str] = None

    if isinstance(raw_signal, dict):
        signal_value = raw_signal.get("decision") or raw_signal.get("signal")
        confidence = raw_signal.get("confidence")
        if confidence is not None:
            confidence_value = float(confidence)
    elif isinstance(raw_signal, str):
        normalized = raw_signal.upper().strip()
        words = normalized.split()
        if words:
            last_word = words[-1].rstrip(".。")
            signal_map = {
                'BUY': 'BUY',
                'OVERWEIGHT': 'OVERWEIGHT',
                'HOLD': 'HOLD',
                'UNDERWEIGHT': 'UNDERWEIGHT',
                'SELL': 'SELL',
                '买入': 'BUY',
                '增持': 'OVERWEIGHT',
                '持有': 'HOLD',
                '减持': 'UNDERWEIGHT',
                '卖出': 'SELL',
            }
            signal_value = signal_map.get(last_word, last_word)

    return signal_value, confidence_value


def _normalize_risk_level(result: Dict[str, Any]) -> Optional[str]:
    """Normalize risk level from analysis result."""
    risk_level = result.get("risk_level")
    if not risk_level and isinstance(result.get("result"), dict):
        risk_level = result["result"].get("risk_level")
    if risk_level is None:
        return None

    normalized = str(risk_level).strip().lower()
    return normalized if normalized in {"low", "medium", "high"} else None


def create_analysis_complete_callback(watchlist_analysis_id: int):
    """Create callback to update WatchlistAnalysis and Watchlist when analysis completes."""
    def callback(task_id: str, result: Dict[str, Any]):
        try:
            from webapi.services.scheduler_service import process_watchlist_analysis_completion

            enriched_result = dict(result or {})
            enriched_result.setdefault("task_id", task_id)
            process_watchlist_analysis_completion(watchlist_analysis_id, enriched_result)
        except Exception as e:
            print(f"[CALLBACK ERROR] {e}", file=sys.stderr)
    return callback


router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


# NOTE: _result_to_response is defined after WatchlistAnalysisResponse below
# to avoid forward-reference NameError at module load time.


# ============================================================================
# Pydantic Models
# ============================================================================


class WatchlistCreate(BaseModel):
    """Request model for creating a watchlist entry."""
    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None


class WatchlistUpdate(BaseModel):
    """Request model for updating a watchlist entry."""
    name: Optional[str] = None
    exchange: Optional[str] = None
    is_active: Optional[bool] = None
    turning_detection_enabled: Optional[bool] = None
    confidence_jump_threshold: Optional[float] = None


class WatchlistResponse(BaseModel):
    """Response model for a watchlist entry."""
    id: int
    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    added_at: str
    is_active: bool
    turning_detection_enabled: bool
    confidence_jump_threshold: float
    last_analysis_at: Optional[str] = None
    last_signal: Optional[str] = None
    last_confidence: Optional[float] = None
    last_risk_level: Optional[str] = None
    is_high_frequency: bool
    high_freq_until: Optional[str] = None
    last_price: Optional[float] = None
    last_change_pct: Optional[float] = None

    class Config:
        from_attributes = True


class WatchlistAnalysisResponse(BaseModel):
    """Response model for a watchlist analysis record."""
    id: int
    watchlist_id: int
    analysis_id: Optional[str] = None
    analysis_type: str
    triggered_by: str
    created_at: str
    completed_at: Optional[str] = None
    signal: Optional[str] = None
    confidence: Optional[float] = None
    risk_level: Optional[str] = None
    is_turning_point: bool
    turning_reason: Optional[str] = None
    importance_score: Optional[float] = None
    alert_sent: bool
    alert_sent_at: Optional[str] = None

    class Config:
        from_attributes = True


class WatchlistAnalysisHistoryResponse(BaseModel):
    """History item for watchlist signal overlay."""

    timestamp: datetime
    signal: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    price: Optional[float] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


def _result_to_response(result: Dict[str, Any], watchlist_id: int) -> "WatchlistAnalysisResponse":
    """Convert incremental analysis result dict to WatchlistAnalysisResponse.

    Args:
        result: Result dict from IncrementalAnalysisService.run_incremental()
        watchlist_id: ID of the watchlist item

    Returns:
        WatchlistAnalysisResponse populated from result
    """
    inner = result.get("result", {})
    signal = inner.get("signal", "")
    if isinstance(signal, dict):
        signal = signal.get("decision", signal.get("signal", ""))
    if isinstance(signal, str):
        signal = signal.upper().strip().split()[-1] if signal.strip() else "UNKNOWN"

    confidence = inner.get("confidence")
    if confidence is not None:
        confidence = float(confidence)

    risk_level = inner.get("risk_level")

    return WatchlistAnalysisResponse(
        id=0,  # Will be set by database
        watchlist_id=watchlist_id,
        analysis_id=result.get("task_id"),
        analysis_type="incremental",
        triggered_by="manual",
        created_at=datetime.utcnow().isoformat(),
        completed_at=datetime.utcnow().isoformat(),
        signal=signal,
        confidence=confidence,
        risk_level=risk_level,
        is_turning_point=False,
        turning_reason=None,
        importance_score=None,
        alert_sent=False,
        alert_sent_at=None,
    )


class TurningDetectionRequest(BaseModel):
    """Request model for turning point detection."""
    current_result: Dict[str, Any]
    previous_result: Dict[str, Any]
    config: Optional[Dict[str, Any]] = None


class TurningDetectionResponse(BaseModel):
    """Response model for turning point detection."""
    is_turning: bool
    reason: str
    importance_score: float


class SchedulerStatusResponse(BaseModel):
    """Response model for scheduler status."""
    is_running: bool
    active_jobs: int
    next_scheduled: Optional[str] = None
    job_ids: List[str] = Field(default_factory=list)


class MonitoringStateResponse(BaseModel):
    """Response model for global watchlist monitoring state."""
    is_active: bool
    started_at: Optional[str] = None
    interval_minutes: int


class MonitoringStateUpdate(BaseModel):
    """Request model for updating global watchlist monitoring state."""
    is_active: Optional[bool] = None
    interval_minutes: Optional[int] = None


class IncrementalAnalyzeRequest(BaseModel):
    """Request model for incremental analysis."""
    force_refresh_analysts: Optional[List[str]] = None  # Optional manual override


# ============================================================================
# Turning Point Detection Algorithm
# ============================================================================


def detect_turning_point(
    current_result: Dict[str, Any],
    previous_result: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> TurningDetectionResponse:
    """
    Detect market turning points by comparing current and previous analysis results.

    Args:
        current_result: Latest analysis result
        previous_result: Previous analysis result
        config: Optional configuration with confidence_jump threshold

    Returns:
        TurningDetectionResponse with detection results
    """
    from webapi.services.scheduler_service import detect_turning_point as scheduler_detect_turning_point

    is_turning, reason, importance = scheduler_detect_turning_point(
        current_result=current_result,
        previous_result=previous_result,
        config=config,
    )

    return TurningDetectionResponse(
        is_turning=is_turning,
        reason=reason,
        importance_score=min(importance, 1.0),
    )


# ============================================================================
# Helper Functions
# ============================================================================


def _watchlist_to_response(w: Watchlist) -> WatchlistResponse:
    """Convert a Watchlist ORM model to WatchlistResponse."""
    return WatchlistResponse(
        id=w.id,
        symbol=w.symbol,
        name=w.name,
        exchange=w.exchange,
        added_at=w.added_at.isoformat() if w.added_at else None,
        is_active=w.is_active == 'Y',
        turning_detection_enabled=w.turning_detection_enabled == 'Y',
        confidence_jump_threshold=float(w.confidence_jump_threshold) if w.confidence_jump_threshold else 0.15,
        last_analysis_at=w.last_analysis_at.isoformat() if w.last_analysis_at else None,
        last_signal=w.last_signal,
        last_confidence=float(w.last_confidence) if w.last_confidence else None,
        last_risk_level=w.last_risk_level,
        is_high_frequency=w.is_high_frequency == 'Y',
        high_freq_until=w.high_freq_until.isoformat() if w.high_freq_until else None,
        last_price=float(w.last_price) if w.last_price else None,
        last_change_pct=float(w.last_change_pct) if w.last_change_pct else None,
    )


def _analysis_to_response(a: WatchlistAnalysis) -> WatchlistAnalysisResponse:
    """Convert a WatchlistAnalysis ORM model to WatchlistAnalysisResponse."""
    return WatchlistAnalysisResponse(
        id=a.id,
        watchlist_id=a.watchlist_id,
        analysis_id=a.analysis_id,
        analysis_type=a.analysis_type,
        triggered_by=a.triggered_by,
        created_at=a.created_at.isoformat() if a.created_at else None,
        completed_at=a.completed_at.isoformat() if a.completed_at else None,
        signal=a.signal,
        confidence=float(a.confidence) if a.confidence else None,
        risk_level=a.risk_level,
        is_turning_point=a.is_turning_point == 'Y',
        turning_reason=a.turning_reason,
        importance_score=float(a.importance_score) if a.importance_score else None,
        alert_sent=a.alert_sent == 'Y',
        alert_sent_at=a.alert_sent_at.isoformat() if a.alert_sent_at else None,
    )


# ============================================================================
# Watchlist CRUD Endpoints
# ============================================================================


@router.post("/", response_model=WatchlistResponse, status_code=201)
async def create_watchlist(request: WatchlistCreate, db: Session = Depends(get_db)):
    """Add a new stock to the watchlist."""
    normalized_symbol = request.symbol.strip().upper()
    normalized_name = request.name.strip() if request.name else None
    normalized_exchange = request.exchange.strip().upper() if request.exchange else None

    # Check if symbol already exists
    existing = db.query(Watchlist).filter(Watchlist.symbol == normalized_symbol).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Symbol {normalized_symbol} already in watchlist")

    watchlist = Watchlist(
        symbol=normalized_symbol,
        name=normalized_name,
        exchange=normalized_exchange,
        added_at=datetime.utcnow(),
        is_active='Y',
        turning_detection_enabled='Y',
        confidence_jump_threshold='0.15',
        is_high_frequency='N',
    )
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    return _watchlist_to_response(watchlist)


@router.get("/", response_model=List[WatchlistResponse])
async def list_watchlist(
    active_only: bool = Query(False, description="Filter to active stocks only"),
    db: Session = Depends(get_db),
):
    """Get all watchlist entries."""
    query = db.query(Watchlist)
    if active_only:
        query = query.filter(Watchlist.is_active == 'Y')
    query = query.order_by(Watchlist.added_at.desc())
    return [_watchlist_to_response(w) for w in query.all()]


@router.get("/analysis", response_model=List[WatchlistAnalysisResponse])
async def list_watchlist_analyses(
    watchlist_id: Optional[int] = Query(None, description="Filter by watchlist ID"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get watchlist analysis history."""
    query = db.query(WatchlistAnalysis)
    if watchlist_id is not None:
        query = query.filter(WatchlistAnalysis.watchlist_id == watchlist_id)
    query = query.order_by(WatchlistAnalysis.created_at.desc())
    return [_analysis_to_response(a) for a in query.limit(limit).all()]


@router.get("/alerts", response_model=List[WatchlistAnalysisResponse])
async def get_turning_signals(
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get all turning point alerts."""
    query = db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.is_turning_point == 'Y'
    ).order_by(WatchlistAnalysis.created_at.desc())
    return [_analysis_to_response(a) for a in query.limit(limit).all()]


@router.post("/detect-turning", response_model=TurningDetectionResponse)
async def detect_turning(
    request: TurningDetectionRequest,
    db: Session = Depends(get_db),
):
    """
    Execute turning point detection by comparing current and previous analysis results.

    This endpoint compares two analysis results and determines if a market turning
    point has occurred based on signal changes, confidence jumps, and risk level shifts.
    """
    return detect_turning_point(
        current_result=request.current_result,
        previous_result=request.previous_result,
        config=request.config,
    )


# ============================================================================
# Scheduler Endpoints
# ============================================================================


def _parse_bool_config(value: Optional[str], default: bool = False) -> bool:
    """Parse watchlist config bool values from string storage."""
    if value is None:
        return default
    return str(value).lower() == "true"


def _get_monitoring_state(db: Session) -> MonitoringStateResponse:
    """Read monitoring state from persistent watchlist config."""
    WatchlistConfig.init_defaults(db)
    is_active = _parse_bool_config(
        WatchlistConfig.get_value(db, "monitoring_active", "false"),
        default=False,
    )
    started_at = WatchlistConfig.get_value(db, "monitoring_started_at", "")
    interval_str = WatchlistConfig.get_value(db, "monitoring_interval", "5")

    try:
        interval_minutes = int(interval_str) if interval_str is not None else 5
    except (TypeError, ValueError):
        interval_minutes = 5

    return MonitoringStateResponse(
        is_active=is_active,
        started_at=started_at or None,
        interval_minutes=interval_minutes,
    )


def _set_monitoring_active(db: Session, is_active: bool) -> MonitoringStateResponse:
    """Persist active state and sync scheduler runtime state."""
    scheduler_service = get_scheduler_service()

    WatchlistConfig.set_value(db, "monitoring_active", "true" if is_active else "false")
    if is_active:
        existing_started_at = WatchlistConfig.get_value(db, "monitoring_started_at", "")
        if not existing_started_at:
            WatchlistConfig.set_value(db, "monitoring_started_at", datetime.utcnow().isoformat())
        if not scheduler_service.is_running:
            scheduler_service.start()
    else:
        WatchlistConfig.set_value(db, "monitoring_started_at", "")
        if scheduler_service.is_running:
            scheduler_service.stop()

    return _get_monitoring_state(db)


@router.get("/monitoring/state", response_model=MonitoringStateResponse)
async def get_monitoring_state(db: Session = Depends(get_db)):
    """Get current persistent monitoring state."""
    return _get_monitoring_state(db)


@router.post("/monitoring/state", response_model=MonitoringStateResponse)
async def update_monitoring_state(
    request: MonitoringStateUpdate,
    db: Session = Depends(get_db),
):
    """Update monitoring state and optional interval configuration."""
    WatchlistConfig.init_defaults(db)

    if request.interval_minutes is not None:
        if request.interval_minutes <= 0:
            raise HTTPException(status_code=422, detail="interval_minutes must be greater than 0")
        WatchlistConfig.set_value(db, "monitoring_interval", str(request.interval_minutes))

    if request.is_active is not None:
        return _set_monitoring_active(db, request.is_active)

    return _get_monitoring_state(db)


@router.post("/monitoring/start", response_model=MonitoringStateResponse)
async def start_monitoring(db: Session = Depends(get_db)):
    """Start watchlist monitoring and scheduler."""
    WatchlistConfig.init_defaults(db)
    return _set_monitoring_active(db, True)


@router.post("/monitoring/stop", response_model=MonitoringStateResponse)
async def stop_monitoring(db: Session = Depends(get_db)):
    """Stop watchlist monitoring and scheduler."""
    WatchlistConfig.init_defaults(db)
    return _set_monitoring_active(db, False)


@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status():
    """Get the current status of the scheduler."""
    scheduler_service = get_scheduler_service()
    jobs = scheduler_service.get_jobs()
    next_scheduled = None
    if jobs:
        next_times: List[str] = []
        for job in jobs:
            next_run = job.get("next_run")
            if isinstance(next_run, str):
                next_times.append(next_run)
        if next_times:
            next_scheduled = min(next_times)

    return SchedulerStatusResponse(
        is_running=scheduler_service.is_running,
        active_jobs=len(jobs),
        next_scheduled=next_scheduled,
        job_ids=[str(job.get("id")) for job in jobs if job.get("id")],
    )


@router.post("/scheduler/trigger/{job_id}", response_model=Dict[str, Any])
async def trigger_scheduler_job(job_id: str, db: Session = Depends(get_db)):
    """
    Manually trigger a scheduler job (for testing purposes).

    In production, this would invoke the actual scheduler job handler.
    """
    _ = db
    result = get_scheduler_service().trigger_job(job_id)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Scheduler job not found: {job_id}")
    return result


# ============================================================================
# Watchlist ID-based Endpoints (must be after static routes)
# ============================================================================


@router.get("/{watchlist_id}", response_model=WatchlistResponse)
async def get_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    """Get a single watchlist entry by ID."""
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    return _watchlist_to_response(watchlist)


@router.put("/{watchlist_id}", response_model=WatchlistResponse)
async def update_watchlist(
    watchlist_id: int,
    request: WatchlistUpdate,
    db: Session = Depends(get_db),
):
    """Update a watchlist entry."""
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    if request.name is not None:
        watchlist.name = request.name.strip() or None
    if request.exchange is not None:
        watchlist.exchange = request.exchange.strip().upper() or None
    if request.is_active is not None:
        watchlist.is_active = 'Y' if request.is_active else 'N'
    if request.turning_detection_enabled is not None:
        watchlist.turning_detection_enabled = 'Y' if request.turning_detection_enabled else 'N'
    if request.confidence_jump_threshold is not None:
        watchlist.confidence_jump_threshold = str(request.confidence_jump_threshold)

    db.commit()
    db.refresh(watchlist)
    return _watchlist_to_response(watchlist)


@router.delete("/{watchlist_id}", status_code=204)
async def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    """Delete a watchlist entry and its associated analysis records."""
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    # Delete associated watchlist analyses first (to avoid FK constraint issues)
    db.query(WatchlistAnalysis).filter(WatchlistAnalysis.watchlist_id == watchlist_id).delete(synchronize_session=False)
    db.delete(watchlist)
    db.commit()
    return None


# ============================================================================
# Analysis Endpoints
# ============================================================================


@router.post("/analyze", response_model=Dict[str, Any])
async def trigger_watchlist_analysis(
    symbol: Optional[str] = Query(None, description="Optional symbol filter"),
    force_refresh: bool = Query(False, description="Bypass cache and force full recomputation"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Manually trigger analysis for all (or filtered) watchlist stocks."""
    query = db.query(Watchlist).filter(Watchlist.is_active == 'Y')
    if symbol:
        query = query.filter(Watchlist.symbol == symbol)

    watchlist_items = query.all()
    if not watchlist_items:
        raise HTTPException(status_code=404, detail="No active watchlist items found")

    results = []
    for item in watchlist_items:
        # Create analysis request
        request = AnalysisRequest(
            symbol=item.symbol,
            exchange=StockExchange.CN,
            force_refresh=force_refresh,
        )
        task = get_analysis_service().create_task(request)

        # Record watchlist analysis
        watchlist_analysis = WatchlistAnalysis(
            watchlist_id=item.id,
            analysis_id=task.task_id,
            analysis_type='full',
            triggered_by='manual',
            created_at=datetime.utcnow(),
        )
        db.add(watchlist_analysis)
        db.commit()

        # Start analysis in background with callback
        watchlist_analysis_id = watchlist_analysis.id
        asyncio.create_task(
            get_analysis_service().run_analysis(
                task.task_id, 
                request,
                on_complete=create_analysis_complete_callback(watchlist_analysis_id)
            )
        )

        results.append({
            "symbol": item.symbol,
            "task_id": task.task_id,
            "watchlist_analysis_id": watchlist_analysis.id,
        })

    return {"triggered": len(results), "results": results}


@router.post("/{watchlist_id}/quick-analyze", response_model=AnalysisResponse, status_code=202)
async def quick_analyze(
    watchlist_id: int,
    db: Session = Depends(get_db),
) -> AnalysisResponse:
    """Trigger a quick analysis (Fast Mode) for a watchlist stock."""
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    # Create quick analysis request
    request = AnalysisRequest(
        symbol=watchlist.symbol,
        exchange=StockExchange.CN,
        analysts=["market"],
        is_quick=True,
    )
    analysis_service = get_analysis_service()
    task = analysis_service.create_task(request)

    # Record watchlist analysis
    watchlist_analysis = WatchlistAnalysis(
        watchlist_id=watchlist.id,
        analysis_id=task.task_id,
        analysis_type='quick',
        triggered_by='manual',
        created_at=datetime.utcnow(),
    )
    db.add(watchlist_analysis)
    db.commit()
    db.refresh(watchlist_analysis)

    # Start analysis in background with callback
    watchlist_analysis_id = watchlist_analysis.id
    asyncio.create_task(
        analysis_service.run_analysis(
            task.task_id, 
            request,
            on_complete=create_analysis_complete_callback(watchlist_analysis_id),
            is_quick=True,
        )
    )

    return AnalysisResponse(
        task_id=task.task_id,
        status=task.status,
        symbol=task.symbol,
        message=f"Quick analysis queued for {watchlist.symbol}",
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        result={
            "analysis_type": "quick",
            "watchlist_id": watchlist.id,
            "watchlist_analysis_id": watchlist_analysis.id,
        },
        error=task.error,
        logs=task.logs,
        agents_progress=task.agents_progress,
        current_agent=task.current_agent,
        progress_pct=task.progress_pct,
        elapsed_time=task.elapsed_time,
        remaining_time=task.remaining_time,
        llm_streams=task.llm_streams,
    )


@router.post("/{watchlist_id}/incremental-analyze/precheck")
async def incremental_analyze_precheck(
    watchlist_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Precheck endpoint for incremental analysis.

    Runs change detection and returns which analysts need refresh
    vs which can use cached results. Does NOT execute any analysis.
    """
    # Get watchlist
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    # Check full analysis exists today (matches IncrementalAnalysisService logic)
    today = date.today()
    full_today = db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.analysis_type == 'full',
        WatchlistAnalysis.completed_at.isnot(None),
        WatchlistAnalysis.error_message.is_(None),
        func.date(WatchlistAnalysis.created_at) == today,
    ).first()

    if not full_today:
        return {
            "error": "需要先完成今日全量分析",
            "needs_refresh": [],
            "cached": [],
            "all_cached": False,
        }

    # Run change detection
    from webapi.services.change_detection import ChangeDetector

    detector = ChangeDetector()
    last_analysis_time = full_today.completed_at
    last_price = float(watchlist.last_price) if watchlist.last_price else None

    changes = detector.auto_detect(
        symbol=watchlist.symbol,
        last_analysis_time=last_analysis_time,
        last_price=last_price,
    )

    needs_refresh = [k for k, v in changes.items() if v]
    cached = [k for k, v in changes.items() if not v]

    return {
        "needs_refresh": needs_refresh,
        "cached": cached,
        "all_cached": len(needs_refresh) == 0,
    }


@router.post("/{watchlist_id}/incremental-analyze", response_model=WatchlistAnalysisResponse)
async def incremental_analyze(
    watchlist_id: int,
    request: Optional[IncrementalAnalyzeRequest] = None,
    db: Session = Depends(get_db),
):
    """Trigger an incremental analysis for a watchlist stock.

    Incremental analysis re-runs only analysts whose data has changed since
    the last full analysis, using cached results for unchanged analysts.
    """
    # 1. Get watchlist item from DB
    watchlist_item = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist_item:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    # 2. Prepare options
    options = {
        "watchlist_id": watchlist_id,
        "triggered_by": "manual",
    }
    if request and request.force_refresh_analysts:
        options["force_refresh_analysts"] = request.force_refresh_analysts

    # 3. Call IncrementalAnalysisService.run_incremental()
    from webapi.services.incremental_analysis_service import IncrementalAnalysisService
    service = IncrementalAnalysisService(db)
    result = service.run_incremental(
        symbol=watchlist_item.symbol,
        analysis_date=date.today().isoformat(),
        options=options,
    )

    # 4. Handle return values
    if "error" in result:
        error = result["error"]
        status_code = result.get("status", 400)
        if status_code == 409:
            raise HTTPException(status_code=409, detail=error)
        raise HTTPException(status_code=400, detail=error)

    # 5. Return 200 with WatchlistAnalysisResponse
    return _result_to_response(result, watchlist_id)


# ============================================================================
# Analysis History Endpoint (for K-line Signal Overlay)
# ============================================================================


@router.get("/{watchlist_id}/analysis-history", response_model=AnalysisHistoryResponse)
async def get_analysis_history(
    watchlist_id: int,
    limit: int = Query(50, ge=1, le=100, description="Number of records to return"),
    db: Session = Depends(get_db),
):
    """Get analysis history for a watchlist stock (for K-line overlay)."""
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    analyses = WatchlistAnalysis.get_analysis_history(watchlist_id, limit=limit, db=db)

    items: List[AnalysisHistoryItem] = []
    for analysis in analyses:
        items.append(AnalysisHistoryItem(
            timestamp=analysis.completed_at or analysis.created_at,
            signal=analysis.signal,
            confidence=float(analysis.confidence) if analysis.confidence else None,
            price=analysis.price,
            error_message=analysis.error_message,
        ))

    # Count total for pagination info
    total_count = db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.watchlist_id == watchlist_id,
        WatchlistAnalysis.completed_at.isnot(None),
    ).count()

    return AnalysisHistoryResponse(
        watchlist_id=watchlist_id,
        symbol=watchlist.symbol,
        items=items,
        total=total_count,
        has_more=total_count > limit,
    )
