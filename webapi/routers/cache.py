"""Cache management API router."""

# pyright: reportCallInDefaultInitializer=false

from datetime import datetime
from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from webapi.config.database import get_db
from webapi.services.analysis_cache_service import AnalysisCacheService
from webapi.models.cache import (
    CacheDeleteResponse,
    CacheRefreshResponse,
    CacheStatusResponse,
    CacheStatsResponse,
    EventInvalidationRequest,
    EventInvalidationResponse,
)

router = APIRouter(prefix="/cache", tags=["cache"])


def get_cache_service(db: Session = Depends(get_db)) -> AnalysisCacheService:
    """Dependency to get cache service instance."""
    return AnalysisCacheService(db)


@router.get("/status/{symbol}", response_model=CacheStatusResponse)
async def get_cache_status(
    symbol: str,
    date: Optional[str] = Query(None, description="Analysis date (YYYY-MM-DD), defaults to today"),
    cache_service: AnalysisCacheService = Depends(get_cache_service),
) -> CacheStatusResponse:
    """Get cache status for a symbol.
    
    Returns the cache status for all analyst types for the given symbol and date.
    """
    try:
        if date:
            analysis_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            analysis_date_obj = datetime.utcnow().date()

        status = cast(dict[str, Any], cache_service.get_cache_status(symbol, analysis_date_obj))
        return CacheStatusResponse(**status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD") from None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving cache status: {exc}") from exc


@router.post("/refresh/{symbol}", response_model=CacheRefreshResponse)
async def refresh_cache(
    symbol: str,
    date: Optional[str] = Query(None, description="Analysis date (YYYY-MM-DD), defaults to today"),
    analyst_type: Optional[str] = Query(None, description="Specific analyst type to refresh (None = all)"),
    cache_service: AnalysisCacheService = Depends(get_cache_service),
) -> CacheRefreshResponse:
    """Refresh (invalidate) cache for a symbol.
    
    Invalidates the cache entries, forcing recomputation on next analysis.
    """
    try:
        if analyst_type and analyst_type not in AnalysisCacheService.ANALYST_TYPES:
            raise HTTPException(status_code=400, detail="Invalid analyst_type")

        if date:
            analysis_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            analysis_date_obj = None

        invalidated_count = cache_service.invalidate_cache(
            symbol=symbol,
            analyst_type=analyst_type,
            analysis_date=analysis_date_obj,
        )

        return CacheRefreshResponse(
            symbol=symbol,
            analysis_date=date or datetime.utcnow().strftime("%Y-%m-%d"),
            analyst_type=analyst_type,
            refreshed_count=invalidated_count,
            message=f"Successfully invalidated {invalidated_count} cache entries",
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD") from None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error refreshing cache: {exc}") from exc


@router.delete("/{symbol}", response_model=CacheDeleteResponse)
async def delete_cache(
    symbol: str,
    date: Optional[str] = Query(None, description="Analysis date (YYYY-MM-DD)"),
    analyst_type: Optional[str] = Query(None, description="Specific analyst type to delete"),
    cache_service: AnalysisCacheService = Depends(get_cache_service),
) -> CacheDeleteResponse:
    """Delete (invalidate) cache entries for a symbol.
    
    This performs a soft delete by marking entries as invalid.
    """
    try:
        if analyst_type and analyst_type not in AnalysisCacheService.ANALYST_TYPES:
            raise HTTPException(status_code=400, detail="Invalid analyst_type")

        if date:
            analysis_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            analysis_date_obj = None

        deleted_count = cache_service.invalidate_cache(
            symbol=symbol,
            analyst_type=analyst_type,
            analysis_date=analysis_date_obj,
        )

        return CacheDeleteResponse(
            symbol=symbol,
            analysis_date=date,
            analyst_type=analyst_type,
            deleted_count=deleted_count,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD") from None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error deleting cache: {exc}") from exc


@router.get("/stats", response_model=CacheStatsResponse)
async def get_cache_stats(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    analyst_type: Optional[str] = Query(None, description="Filter by analyst type"),
    time_range_hours: int = Query(24, description="Time range for statistics (hours)"),
    cache_service: AnalysisCacheService = Depends(get_cache_service),
) -> CacheStatsResponse:
    """Get cache statistics.
    
    Returns aggregate statistics about cache usage and hit rates.
    """
    try:
        if analyst_type and analyst_type not in AnalysisCacheService.ANALYST_TYPES:
            raise HTTPException(status_code=400, detail="Invalid analyst_type")

        stats = cast(
            dict[str, Any],
            cache_service.get_cache_stats(symbol=symbol, analyst_type=analyst_type, time_range_hours=time_range_hours),
        )
        return CacheStatsResponse(**stats)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving cache stats: {exc}") from exc


@router.post("/invalidate-event", response_model=EventInvalidationResponse)
async def invalidate_on_event(
    request: EventInvalidationRequest,
    cache_service: AnalysisCacheService = Depends(get_cache_service),
) -> EventInvalidationResponse:
    """Invalidate cache based on market events.
    
    Supported events:
    - trading_halt: Invalidates market, sentiment, news
    - limit_up: Invalidates market, sentiment
    - limit_down: Invalidates market, sentiment
    - earnings_report: Invalidates fundamentals
    - major_news: Invalidates news, sentiment
    """
    try:
        if request.event_type not in AnalysisCacheService.EVENT_INVALIDATION_MAP:
            raise HTTPException(status_code=400, detail="Invalid event_type")

        total_invalidated = cache_service.invalidate_on_event(
            event_type=request.event_type,
            symbol=request.symbol,
            analysis_date=request.analysis_date,
        )

        # Get affected analysts from the service
        affected_analysts = list(cache_service.EVENT_INVALIDATION_MAP.get(request.event_type, ()))

        return EventInvalidationResponse(
            event_type=request.event_type,
            symbol=request.symbol,
            analysis_date=request.analysis_date.isoformat() if request.analysis_date else None,
            analysts_affected=affected_analysts,
            total_invalidated=total_invalidated,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error processing event invalidation: {exc}") from exc


@router.post("/cleanup")
async def cleanup_expired_cache(
    batch_size: int = Query(1000, description="Maximum number of entries to clean up"),
    cache_service: AnalysisCacheService = Depends(get_cache_service)
):
    """Clean up expired cache entries.
    
    Performs soft delete on expired cache entries.
    """
    try:
        cleaned_count = cache_service.cleanup_expired_cache(batch_size=batch_size)
        return {
            "cleaned_count": cleaned_count,
            "message": f"Successfully cleaned up {cleaned_count} expired cache entries"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cleaning up cache: {str(e)}")
