"""Pydantic models for cache management API."""

# pyright: reportUnusedImport=false, reportDeprecated=false, reportUnannotatedClassAttribute=false

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class CacheAnalystStatus(BaseModel):
    """Cache status details for a single analyst."""

    cached: bool = Field(..., description="Whether a cache row exists")
    valid: bool = Field(..., description="Whether the cache row is currently valid")
    created_at: Optional[str] = Field(None, description="Cache creation timestamp")
    expires_at: Optional[str] = Field(None, description="Cache expiration timestamp")
    cache_version: Optional[int] = Field(None, description="Cache version")
    lock_session_id: Optional[str] = Field(None, description="Lock session identifier")


class CacheStatusResponse(BaseModel):
    """Response model for cache status query."""

    symbol: str = Field(..., description="Stock symbol")
    analysis_date: str = Field(..., description="Analysis date (YYYY-MM-DD)")
    analysts: Dict[str, CacheAnalystStatus] = Field(
        default_factory=dict,
        description="Cache status for each analyst type"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "000001.SZ",
                "analysis_date": "2026-03-31",
                "analysts": {
                    "market": {
                        "cached": True,
                        "valid": True,
                        "created_at": "2026-03-31T08:00:00",
                        "expires_at": "2026-03-31T08:15:00",
                        "cache_version": 1
                    },
                    "sentiment": {
                        "cached": False,
                        "valid": False
                    }
                }
            }
        }


class CacheRefreshRequest(BaseModel):
    """Request model for cache refresh."""

    analyst_type: Optional[str] = Field(
        None,
        description="Specific analyst type to refresh (None = all)"
    )


class CacheRefreshResponse(BaseModel):
    """Response model for cache refresh."""

    symbol: str = Field(..., description="Stock symbol")
    analysis_date: str = Field(..., description="Analysis date (YYYY-MM-DD)")
    analyst_type: Optional[str] = Field(None, description="Specific analyst type refreshed")
    refreshed_count: int = Field(..., description="Number of cache entries refreshed")
    message: str = Field(..., description="Status message")


class CacheDeleteResponse(BaseModel):
    """Response model for cache deletion."""

    symbol: str = Field(..., description="Stock symbol")
    analysis_date: Optional[str] = Field(None, description="Analysis date (if specified)")
    analyst_type: Optional[str] = Field(None, description="Analyst type (if specified)")
    deleted_count: int = Field(..., description="Number of cache entries deleted")


class CacheMetricBreakdown(BaseModel):
    """Runtime cache hit/miss counters for one analyst."""

    full: int = Field(default=0, description="Full cache hits")
    partial: int = Field(default=0, description="Partial cache hits")
    miss: int = Field(default=0, description="Cache misses")


class CacheAnalystStats(BaseModel):
    """Entry distribution stats for one analyst."""

    total: int = Field(default=0, description="Total cache entries")
    valid: int = Field(default=0, description="Valid cache entries")


class CacheStatsResponse(BaseModel):
    """Response model for cache statistics."""

    time_range_hours: int = Field(..., description="Time range for statistics")
    symbol_filter: Optional[str] = Field(None, description="Symbol filter (if applied)")
    analyst_type_filter: Optional[str] = Field(None, description="Analyst type filter (if applied)")
    total_entries: int = Field(..., description="Total cache entries")
    valid_entries: int = Field(..., description="Valid (non-expired) entries")
    expired_entries: int = Field(..., description="Expired but not cleaned entries")
    hit_rate_estimate: float = Field(..., description="Estimated cache hit rate")
    runtime_hit_rate: float = Field(..., description="Observed runtime hit rate")
    hit_counters: Dict[str, int] = Field(default_factory=dict, description="Global hit/miss counters")
    analyst_hit_counters: Dict[str, CacheMetricBreakdown] = Field(
        default_factory=dict,
        description="Per-analyst hit/miss counters"
    )
    analyst_breakdown: Dict[str, CacheAnalystStats] = Field(
        default_factory=dict,
        description="Breakdown by analyst type"
    )


class EventInvalidationRequest(BaseModel):
    """Request model for event-driven cache invalidation."""

    event_type: str = Field(
        ...,
        description="Event type (trading_halt, limit_up, limit_down, earnings_report, major_news)"
    )
    symbol: str = Field(..., description="Stock symbol affected by the event")
    analysis_date: Optional[date] = Field(None, description="Optional analysis date scope")

    class Config:
        json_schema_extra = {
            "example": {
                "event_type": "limit_up",
                "symbol": "000001.SZ",
                "analysis_date": "2026-03-31"
            }
        }


class EventInvalidationResponse(BaseModel):
    """Response model for event-driven cache invalidation."""

    event_type: str = Field(..., description="Event type")
    symbol: str = Field(..., description="Stock symbol")
    analysis_date: Optional[str] = Field(None, description="Analysis date scope")
    analysts_affected: List[str] = Field(..., description="Analyst types affected")
    total_invalidated: int = Field(..., description="Number of entries invalidated")


class CacheHitRateResponse(BaseModel):
    """Response model for cache hit rate queries."""

    symbol: Optional[str] = None
    analyst_type: Optional[str] = None
    time_range_hours: int
    hit_rate: float
    counters: Dict[str, int] = Field(default_factory=dict)


class CacheEntry(BaseModel):
    """Model for a single cache entry."""

    id: int = Field(..., description="Cache entry ID")
    symbol: str = Field(..., description="Stock symbol")
    analyst_type: str = Field(..., description="Analyst type")
    analysis_date: date = Field(..., description="Analysis date")
    cache_version: int = Field(..., description="Cache version")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: datetime = Field(..., description="Expiration timestamp")
    is_valid: bool = Field(..., description="Whether the entry is valid")
    is_expired: bool = Field(..., description="Whether the entry has expired")


class CacheListResponse(BaseModel):
    """Response model for listing cache entries."""

    entries: List[CacheEntry] = Field(default_factory=list, description="Cache entries")
    total: int = Field(..., description="Total number of entries")
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=100, description="Page size")
