"""
Watchlist Router for TradingAgents API
"""
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webapi.config.database import get_db
from webapi.models.database import Watchlist, WatchlistAnalysis, WatchlistConfig
from webapi.models.analysis import (
    AnalysisRequest,
    StockExchange,
    AnalysisHistoryResponse,
    AnalysisHistoryItem,
    SignalType,
)
import asyncio

# Lazy import analysis_service to avoid slow startup
def get_analysis_service():
    from webapi.services.analysis_service import analysis_service
    return analysis_service


def get_scheduler_service():
    from webapi.services.scheduler_service import scheduler_service
    return scheduler_service


def create_analysis_complete_callback(watchlist_analysis_id: int):
    """Create callback to update WatchlistAnalysis and Watchlist when analysis completes."""
    def callback(task_id: str, result: Dict[str, Any]):
        from webapi.config.database import SessionLocal
        db = SessionLocal()
        try:
            analysis = db.query(WatchlistAnalysis).filter(
                WatchlistAnalysis.id == watchlist_analysis_id
            ).first()
            if analysis:
                analysis.completed_at = datetime.utcnow()
                
                # Extract signal and confidence for later use
                signal_value = "UNKNOWN"
                confidence_value = 0.0
                
                if result.get("status") == "error":
                    analysis.error_message = result.get("error", "Analysis failed")
                else:
                    # Extract signal
                    signal = result.get("signal", "")
                    if isinstance(signal, dict):
                        signal_value = signal.get("decision", "UNKNOWN")
                        confidence_value = signal.get("confidence", 0) or 0.0
                        analysis.signal = signal_value
                        analysis.confidence = confidence_value
                    elif isinstance(signal, str):
                        # Normalize signal: uppercase, strip whitespace, extract last word
                        normalized = signal.upper().strip()
                        # Extract the last word if it contains spaces (e.g., "Decision: BUY" -> "BUY")
                        words = normalized.split()
                        if words:
                            last_word = words[-1]
                            # Map common variations to standard 5-tier signals
                            signal_map = {
                                'BUY': 'BUY',
                                'OVERWEIGHT': 'OVERWEIGHT',
                                'HOLD': 'HOLD',
                                'UNDERWEIGHT': 'UNDERWEIGHT',
                                'SELL': 'SELL',
                                # Handle common misspellings/variations with trailing dots
                                'BUY.': 'BUY',
                                'OVERWEIGHT.': 'OVERWEIGHT',
                                'HOLD.': 'HOLD',
                                'UNDERWEIGHT.': 'UNDERWEIGHT',
                                'SELL.': 'SELL',
                                # Chinese translations
                                '买入': 'BUY',
                                '增持': 'OVERWEIGHT',
                                '持有': 'HOLD',
                                '减持': 'UNDERWEIGHT',
                                '卖出': 'SELL',
                            }
                            signal_value = signal_map.get(last_word, last_word)
                        else:
                            signal_value = "UNKNOWN"
                        analysis.signal = signal_value
                        # Confidence not available from signal processor - store None
                        # Don't fabricate confidence as it misleads users
                        analysis.confidence = None
                    
                    # Set price from result or fallback to watchlist last_price
                    analysis.price = result.get("price")
                    if not analysis.price:
                        watchlist = db.query(Watchlist).filter(
                            Watchlist.id == analysis.watchlist_id
                        ).first()
                        if watchlist and watchlist.last_price:
                            analysis.price = float(watchlist.last_price)
                    
                    # Update confidence_value for watchlist update (None if not available)
                    confidence_value = analysis.confidence
                
                db.commit()
                
                # Also update Watchlist current state for UI display
                watchlist = db.query(Watchlist).filter(
                    Watchlist.id == analysis.watchlist_id
                ).first()
                if watchlist:
                    watchlist.last_analysis_at = datetime.utcnow()
                    watchlist.last_signal = signal_value
                    watchlist.last_confidence = str(confidence_value)
                    db.commit()
                    
        except Exception as e:
            db.rollback()
            print(f"[CALLBACK ERROR] {e}", file=sys.stderr)
        finally:
            db.close()
    return callback


router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])

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


class MonitoringStateResponse(BaseModel):
    """Response model for global watchlist monitoring state."""
    is_active: bool
    started_at: Optional[str] = None
    interval_minutes: int


class MonitoringStateUpdate(BaseModel):
    """Request model for updating global watchlist monitoring state."""
    is_active: Optional[bool] = None
    interval_minutes: Optional[int] = None


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
    config = config or {}
    confidence_threshold = config.get('confidence_jump', 0.15)

    current_signal = current_result.get('signal', 'UNKNOWN')
    previous_signal = previous_result.get('signal', 'UNKNOWN')

    # Handle nested signal structure
    if isinstance(current_signal, dict):
        current_signal = current_signal.get('decision', current_signal.get('signal', 'UNKNOWN'))
    if isinstance(previous_signal, dict):
        previous_signal = previous_signal.get('decision', previous_signal.get('signal', 'UNKNOWN'))

    current_conf = current_result.get('confidence', 0)
    previous_conf = previous_result.get('confidence', 0)

    current_risk = current_result.get('risk_level', 'medium')
    previous_risk = previous_result.get('risk_level', 'medium')

    turning_signals: List[str] = []
    importance = 0.0

    # 1. Signal change detection
    if current_signal != previous_signal and current_signal in ['BUY', 'SELL']:
        if previous_signal in ['SELL', 'BUY'] or (previous_signal == 'HOLD' and current_conf > 0.75):
            turning_signals.append(f"信号转变: {previous_signal} → {current_signal}")
            importance += 0.9

    # 2. Confidence jump detection
    conf_jump = current_conf - previous_conf
    if conf_jump >= confidence_threshold and current_conf > 0.8:
        turning_signals.append(f"置信度突破: {previous_conf:.0%} → {current_conf:.0%}")
        importance += 0.6

    # 3. Risk level change detection
    risk_levels = {'low': 1, 'medium': 2, 'high': 3}
    if risk_levels.get(current_risk, 2) != risk_levels.get(previous_risk, 2):
        if risk_levels.get(current_risk, 2) > risk_levels.get(previous_risk, 2):
            turning_signals.append(f"风险上升: {previous_risk} → {current_risk}")
            importance += 0.4
        else:
            turning_signals.append(f"风险下降: {previous_risk} → {current_risk}")
            importance += 0.3

    # 4. Emergency signal detection
    market_alert = current_result.get('market_alert', '')
    if market_alert and '异常' in str(market_alert):
        turning_signals.append(f"市场警报: {market_alert}")
        importance += 0.95

    is_turning = importance >= 0.5 or len(turning_signals) >= 2
    reason = " | ".join(turning_signals) if turning_signals else "无显著变化"

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
    # Check if symbol already exists
    existing = db.query(Watchlist).filter(Watchlist.symbol == request.symbol).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Symbol {request.symbol} already in watchlist")

    watchlist = Watchlist(
        symbol=request.symbol,
        name=request.name,
        exchange=request.exchange,
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
    )


@router.post("/scheduler/trigger/{job_id}", response_model=Dict[str, Any])
async def trigger_scheduler_job(job_id: str, db: Session = Depends(get_db)):
    """
    Manually trigger a scheduler job (for testing purposes).

    In production, this would invoke the actual scheduler job handler.
    """
    # For now, trigger analysis for all active high-frequency watchlist items
    high_freq_items = db.query(Watchlist).filter(
        Watchlist.is_active == 'Y',
        Watchlist.is_high_frequency == 'Y',
    ).all()

    results = []
    for item in high_freq_items:
        request = AnalysisRequest(
            symbol=item.symbol,
            exchange=StockExchange.CN,
        )
        task = get_analysis_service().create_task(request)

        watchlist_analysis = WatchlistAnalysis(
            watchlist_id=item.id,
            analysis_id=task.task_id,
            analysis_type='scheduled',
            triggered_by='scheduler',
            created_at=datetime.utcnow(),
        )
        db.add(watchlist_analysis)
        db.commit()

        asyncio.create_task(
            get_analysis_service().run_analysis(task.task_id, request)
        )

        results.append({
            "symbol": item.symbol,
            "task_id": task.task_id,
            "watchlist_analysis_id": watchlist_analysis.id,
        })

    return {
        "job_id": job_id,
        "triggered": len(results),
        "results": results,
    }


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
        watchlist.name = request.name
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
    db: Session = Depends(get_db),
):
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


@router.post("/{watchlist_id}/quick-analyze", response_model=WatchlistAnalysisResponse, status_code=202)
async def quick_analyze(
    watchlist_id: int,
    db: Session = Depends(get_db),
):
    """Trigger a quick analysis (Fast Mode) for a watchlist stock."""
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    # Create quick analysis request
    request = AnalysisRequest(
        symbol=watchlist.symbol,
        exchange=StockExchange.CN,
        analysts=["market"],  # Quick mode: only market analyst
    )
    task = get_analysis_service().create_task(request)

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
        get_analysis_service().run_analysis(
            task.task_id, 
            request,
            on_complete=create_analysis_complete_callback(watchlist_analysis_id)
        )
    )

    return _analysis_to_response(watchlist_analysis)


# ============================================================================
# Analysis History Endpoint (for K-line Signal Overlay)
# ============================================================================


@router.get("/{watchlist_id}/analysis-history", response_model=AnalysisHistoryResponse)
async def get_analysis_history(
    watchlist_id: int,
    limit: int = Query(50, ge=1, le=100, description="Number of records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
):
    """Get analysis history for a watchlist stock (for K-line overlay)."""
    # Check if watchlist exists
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    # Query analysis history - filter to only include records with valid signals
    # This ensures total/has_more are accurate for the actual returned items
    valid_signals = [s.value for s in SignalType]
    query = db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.watchlist_id == watchlist_id,
        WatchlistAnalysis.completed_at.isnot(None),  # Only completed analyses
        WatchlistAnalysis.signal.in_(valid_signals)  # Only valid signals
    ).order_by(WatchlistAnalysis.created_at.desc())

    total = query.count()
    analyses = query.offset(offset).limit(limit).all()

    # Convert to response items
    items = []
    for analysis in analyses:
        # Signal is already validated by the query filter
        signal_enum = SignalType(analysis.signal)
        
        # Use completed_at for timestamp (when price was captured)
        # Only include confidence if it was actually produced by the analysis
        confidence_val = float(analysis.confidence) if analysis.confidence else None
        
        items.append(AnalysisHistoryItem(
            timestamp=analysis.completed_at or analysis.created_at,
            signal=signal_enum,
            confidence=confidence_val,
            price=float(analysis.price) if analysis.price else None,
            error_message=analysis.error_message,
        ))

    return AnalysisHistoryResponse(
        watchlist_id=watchlist_id,
        symbol=watchlist.symbol,
        items=items,
        total=total,
        has_more=(offset + len(items)) < total,
    )
