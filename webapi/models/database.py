"""SQLAlchemy ORM models for TradingAgents database."""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from webapi.config.database import Base


class AnalysisTask(Base):
    """Analysis task ORM model."""
    
    __tablename__ = "analysis_tasks"
    
    # Primary key
    task_id = Column(String(36), primary_key=True, nullable=False)
    
    # Task metadata
    symbol = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Analysis result (non-structured, stored as JSONB)
    result = Column(JSONB, nullable=True)
    
    # Extracted fields for querying
    decision = Column(String(10), nullable=True)  # BUY, SELL, HOLD, UNKNOWN
    confidence = Column(Integer, nullable=True)
    
    # Messages
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    # Real-time progress tracking (NEW)
    agents_progress = Column(JSONB, nullable=True, default=dict)
    current_agent = Column(String(50), nullable=True)
    progress_pct = Column(Integer, nullable=True, default=0)
    logs = Column(JSONB, nullable=True, default=list)

    # Table configuration
    __table_args__ = (
        Index('idx_analysis_tasks_symbol_status', 'symbol', 'status'),
        Index('idx_analysis_tasks_created_status', 'created_at', 'status'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            'task_id': self.task_id,
            'symbol': self.symbol,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'result': self.result,
            'decision': self.decision,
            'confidence': self.confidence,
            'message': self.message,
            'error': self.error,
            'agents_progress': self.agents_progress,
            'current_agent': self.current_agent,
            'progress_pct': self.progress_pct,
            'logs': self.logs,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisTask":
        """Create instance from dictionary."""
        return cls(
            task_id=data.get('task_id'),
            symbol=data.get('symbol', ''),
            status=data.get('status', 'PENDING'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else None,
            completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
            result=data.get('result'),
            decision=data.get('decision'),
            confidence=data.get('confidence'),
            message=data.get('message'),
            error=data.get('error'),
            agents_progress=data.get('agents_progress'),
            current_agent=data.get('current_agent'),
            progress_pct=data.get('progress_pct'),
            logs=data.get('logs'),
        )
    
    @classmethod
    def from_analysis_response(cls, response: Any) -> "AnalysisTask":
        """Create instance from AnalysisResponse Pydantic model."""
        result_data = None
        decision_val = None
        
        if response.result:
            result_data = dict(response.result)
            # Extract decision from result if available
            if isinstance(response.result, dict):
                if 'signal' in response.result and isinstance(response.result['signal'], dict):
                    decision_val = response.result['signal'].get('decision')
                elif 'decision' in response.result:
                    decision_val = response.result['decision']
        
        return cls(
            task_id=response.task_id,
            symbol=response.symbol,
            status=response.status.value if hasattr(response.status, 'value') else str(response.status),
            created_at=datetime.fromisoformat(response.created_at) if response.created_at else datetime.utcnow(),
            updated_at=datetime.fromisoformat(response.updated_at) if response.updated_at else None,
            completed_at=datetime.fromisoformat(response.completed_at) if response.completed_at else None,
            result=result_data,
            decision=decision_val,
            confidence=response.result.get('confidence') if result_data else None,
            message=response.message,
            error=response.error,
            agents_progress=getattr(response, 'agents_progress', None),
            current_agent=getattr(response, 'current_agent', None),
            progress_pct=getattr(response, 'progress_pct', None),
            logs=getattr(response, 'logs', None),
        )


class AnalysisBatch(Base):
    """Batch analysis ORM model for persisting batch metadata."""
    
    __tablename__ = "analysis_batches"
    
    # Primary key
    batch_id = Column(String(36), primary_key=True, nullable=False)
    
    # Batch metadata
    total = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Task IDs (JSON array of task UUIDs)
    task_ids = Column(JSONB, nullable=False, default=list)
    
    # Optional metadata
    symbols = Column(JSONB, nullable=True)  # List of symbols in this batch
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    
    # Table configuration
    __table_args__ = (
        Index('idx_analysis_batches_status_created', 'status', 'created_at'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            'batch_id': self.batch_id,
            'total': self.total,
            'completed_count': self.completed_count,
            'failed_count': self.failed_count,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'task_ids': self.task_ids,
            'symbols': self.symbols,
            'message': self.message,
            'error': self.error,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisBatch":
        """Create instance from dictionary."""
        return cls(
            batch_id=data.get('batch_id'),
            total=data.get('total', 0),
            completed_count=data.get('completed_count', 0),
            failed_count=data.get('failed_count', 0),
            status=data.get('status', 'PENDING'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else None,
            completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
            task_ids=data.get('task_ids', []),
            symbols=data.get('symbols'),
            message=data.get('message'),
            error=data.get('error'),
        )
