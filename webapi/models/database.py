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
        )
