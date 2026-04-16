"""Pydantic models for TradingAgents Web API analysis endpoints."""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportExplicitAny=false, reportGeneralTypeIssues=false, reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnannotatedClassAttribute=false, reportDeprecated=false, reportMissingTypeArgument=false, reportUnusedImport=false, reportUnusedVariable=false

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AnalysisStatus(str, Enum):
    """Analysis task status enumeration."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StockExchange(str, Enum):
    """Stock exchange enumeration."""
    US = "US"
    CN = "CN"
    HK = "HK"


class AnalysisRequest(BaseModel):
    """Request model for single stock analysis."""
    symbol: str
    date: Optional[str] = None
    exchange: StockExchange = StockExchange.CN
    source: str = "mairui"
    analysts: List[str] = Field(default_factory=lambda: ["market", "news", "social", "fundamentals"])
    llm_provider: Optional[str] = None
    deep_model: Optional[str] = None
    quick_model: Optional[str] = None
    force_refresh: bool = Field(default=False, description="Force refresh - bypass cache and recompute all analysts")
    is_quick: bool = Field(default=False, description="Enable fast-path analysis mode")


class AnalysisResponse(BaseModel):
    """Response model for single stock analysis."""

    task_id: str
    status: AnalysisStatus
    symbol: str
    message: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    logs: List[Dict[str, Any]] = Field(default_factory=list)

    # Real-time progress fields (for running/pending tasks)
    agents_progress: Optional[Dict[str, Any]] = None
    current_agent: Optional[str] = None
    progress_pct: Optional[int] = None
    elapsed_time: Optional[int] = None  # seconds
    remaining_time: Optional[int] = None  # seconds

    # Per-agent LLM output text for post-analysis review
    llm_streams: Optional[Dict[str, Any]] = None

    # Position context from watchlist
    position_context: Optional[Dict[str, Any]] = None

    # Extracted trading decision and confidence
    decision: Optional[str] = None  # BUY, OVERWEIGHT, HOLD, UNDERWEIGHT, SELL, UNKNOWN
    confidence: Optional[int] = None  # 0-100

    class Config:
        from_attributes = True


class BatchAnalysisRequest(BaseModel):
    """Request model for batch stock analysis."""
    symbols: List[str] = Field(min_length=1, max_length=10)
    date: Optional[str] = None
    exchange: StockExchange = StockExchange.CN
    source: str = "mairui"
    analysts: List[str] = Field(default_factory=lambda: ["market", "news", "social", "fundamentals"])
    force_refresh: bool = Field(default=False, description="Force refresh - bypass cache and recompute all analysts")


class BatchAnalysisResponse(BaseModel):
    """Response model for batch stock analysis."""
    batch_id: str
    total: int
    completed_count: int = 0
    failed_count: int = 0
    tasks: List[AnalysisResponse]
    status: AnalysisStatus
    created_at: str
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


class AnalysisProgress(BaseModel):
    """Progress model for analysis task tracking."""
    task_id: str
    status: AnalysisStatus
    progress: float = Field(ge=0, le=100)
    current_step: str
    message: str
    timestamp: datetime
    logs: List[str] = Field(default_factory=list)


class SignalType(str, Enum):
    """Signal type enumeration - 5-tier rating system."""
    BUY = "BUY"
    OVERWEIGHT = "OVERWEIGHT"
    HOLD = "HOLD"
    UNDERWEIGHT = "UNDERWEIGHT"
    SELL = "SELL"


class AnalysisHistoryItem(BaseModel):
    """Single analysis history record for K-line overlay."""
    timestamp: datetime
    signal: SignalType
    confidence: Optional[float] = Field(None, ge=0, le=1)
    price: Optional[float] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class AnalysisHistoryResponse(BaseModel):
    """Response model for analysis history endpoint."""
    watchlist_id: int
    symbol: str
    items: List[AnalysisHistoryItem]
    total: int
    has_more: bool

    class Config:
        from_attributes = True


class DiffReportRequest(BaseModel):
    """Request model for diff report between two analysis tasks."""
    task_id_1: str
    task_id_2: str
    symbol: Optional[str] = None  # For validation


class DiffReportResponse(BaseModel):
    """Response model for diff report between two analysis tasks."""
    analysts: Dict[str, Any]
    decision: Dict[str, Any]
    confidence: Dict[str, Any]
    timestamp_range: str
