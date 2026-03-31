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


class Watchlist(Base):
    """Watchlist ORM model for tracking watched stocks."""
    
    __tablename__ = "watchlist"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Stock info
    symbol = Column(String(20), nullable=False, index=True, unique=True)
    name = Column(String(100), nullable=True)
    exchange = Column(String(10), nullable=True)
    
    # Timestamps
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(String(1), nullable=False, default='Y')  # Y/N
    
    # Turning detection config
    turning_detection_enabled = Column(String(1), nullable=False, default='Y')  # Y/N
    confidence_jump_threshold = Column(String(10), nullable=False, default='0.15')
    
    # Current state from last analysis
    last_analysis_at = Column(DateTime, nullable=True)
    last_signal = Column(String(20), nullable=True)  # BUY, OVERWEIGHT, HOLD, UNDERWEIGHT, SELL
    last_confidence = Column(String(10), nullable=True)
    last_risk_level = Column(String(20), nullable=True)
    
    # Runtime state
    is_high_frequency = Column(String(1), nullable=False, default='N')  # Y/N
    high_freq_until = Column(DateTime, nullable=True)
    last_price = Column(String(20), nullable=True)
    last_change_pct = Column(String(10), nullable=True)
    
    # Table configuration
    __table_args__ = (
        Index('idx_watchlist_symbol_active', 'symbol', 'is_active'),
        Index('idx_watchlist_high_freq', 'is_high_frequency', 'high_freq_until'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            'id': self.id,
            'symbol': self.symbol,
            'name': self.name,
            'exchange': self.exchange,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'is_active': self.is_active == 'Y',
            'turning_detection_enabled': self.turning_detection_enabled == 'Y',
            'confidence_jump_threshold': float(self.confidence_jump_threshold) if self.confidence_jump_threshold else 0.15,
            'last_analysis_at': self.last_analysis_at.isoformat() if self.last_analysis_at else None,
            'last_signal': self.last_signal,
            'last_confidence': float(self.last_confidence) if self.last_confidence else None,
            'last_risk_level': self.last_risk_level,
            'is_high_frequency': self.is_high_frequency == 'Y',
            'high_freq_until': self.high_freq_until.isoformat() if self.high_freq_until else None,
            'last_price': float(self.last_price) if self.last_price else None,
            'last_change_pct': float(self.last_change_pct) if self.last_change_pct else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Watchlist":
        """Create instance from dictionary."""
        return cls(
            id=data.get('id'),
            symbol=data.get('symbol', ''),
            name=data.get('name'),
            exchange=data.get('exchange'),
            added_at=datetime.fromisoformat(data['added_at']) if data.get('added_at') else datetime.utcnow(),
            is_active='Y' if data.get('is_active', True) else 'N',
            turning_detection_enabled='Y' if data.get('turning_detection_enabled', True) else 'N',
            confidence_jump_threshold=str(data.get('confidence_jump_threshold', 0.15)),
            last_analysis_at=datetime.fromisoformat(data['last_analysis_at']) if data.get('last_analysis_at') else None,
            last_signal=data.get('last_signal'),
            last_confidence=str(data['last_confidence']) if data.get('last_confidence') is not None else None,
            last_risk_level=data.get('last_risk_level'),
            is_high_frequency='Y' if data.get('is_high_frequency', False) else 'N',
            high_freq_until=datetime.fromisoformat(data['high_freq_until']) if data.get('high_freq_until') else None,
            last_price=str(data['last_price']) if data.get('last_price') is not None else None,
            last_change_pct=str(data['last_change_pct']) if data.get('last_change_pct') is not None else None,
        )


class WatchlistAnalysis(Base):
    """Watchlist analysis task ORM model."""
    
    __tablename__ = "watchlist_analyses"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign keys
    watchlist_id = Column(Integer, nullable=False, index=True)
    analysis_id = Column(String(36), nullable=True, index=True)
    
    # Analysis type and trigger
    analysis_type = Column(String(20), nullable=False)  # 'full', 'quick', 'turning'
    triggered_by = Column(String(20), nullable=False, default='scheduled')  # 'scheduled', 'turning', 'manual'
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Analysis result
    signal = Column(String(20), nullable=True)  # BUY, OVERWEIGHT, HOLD, UNDERWEIGHT, SELL
    confidence = Column(String(10), nullable=True)
    risk_level = Column(String(20), nullable=True)
    price = Column(String(20), nullable=True)  # Stock price at analysis time
    error_message = Column(Text, nullable=True)  # Error details if analysis failed
    
    # Turning detection
    is_turning_point = Column(String(1), nullable=False, default='N')  # Y/N
    turning_reason = Column(Text, nullable=True)
    importance_score = Column(String(10), nullable=True)
    
    # Notification status
    alert_sent = Column(String(1), nullable=False, default='N')  # Y/N
    alert_sent_at = Column(DateTime, nullable=True)
    
    # Table configuration
    __table_args__ = (
        Index('idx_watchlist_analyses_watchlist_id', 'watchlist_id', 'created_at'),
        Index('idx_watchlist_analyses_turning', 'is_turning_point', 'created_at'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            'id': self.id,
            'watchlist_id': self.watchlist_id,
            'analysis_id': self.analysis_id,
            'analysis_type': self.analysis_type,
            'triggered_by': self.triggered_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'signal': self.signal,
            'confidence': float(self.confidence) if self.confidence else None,
            'risk_level': self.risk_level,
            'price': float(self.price) if self.price else None,
            'error_message': self.error_message,
            'is_turning_point': self.is_turning_point == 'Y',
            'turning_reason': self.turning_reason,
            'importance_score': float(self.importance_score) if self.importance_score else None,
            'alert_sent': self.alert_sent == 'Y',
            'alert_sent_at': self.alert_sent_at.isoformat() if self.alert_sent_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WatchlistAnalysis":
        """Create instance from dictionary."""
        return cls(
            id=data.get('id'),
            watchlist_id=data.get('watchlist_id', 0),
            analysis_id=data.get('analysis_id'),
            analysis_type=data.get('analysis_type', 'quick'),
            triggered_by=data.get('triggered_by', 'scheduled'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.utcnow(),
            completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
            signal=data.get('signal'),
            confidence=str(data['confidence']) if data.get('confidence') is not None else None,
            risk_level=data.get('risk_level'),
            price=str(data['price']) if data.get('price') is not None else None,
            error_message=data.get('error_message'),
            is_turning_point='Y' if data.get('is_turning_point', False) else 'N',
            turning_reason=data.get('turning_reason'),
            importance_score=str(data['importance_score']) if data.get('importance_score') is not None else None,
            alert_sent='Y' if data.get('alert_sent', False) else 'N',
            alert_sent_at=datetime.fromisoformat(data['alert_sent_at']) if data.get('alert_sent_at') else None,
        )


class WatchlistConfig(Base):
    """Global watchlist configuration table for persistent monitoring state."""
    
    __tablename__ = "watchlist_config"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Configuration key-value pairs
    config_key = Column(String(50), nullable=False, unique=True, index=True)
    config_value = Column(Text, nullable=True)  # JSON string storage
    
    # Timestamps
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Table configuration
    __table_args__ = (
        Index('idx_watchlist_config_key', 'config_key'),
    )
    
    @classmethod
    def get_value(cls, db, key: str, default: str = None) -> str:
        """Get configuration value by key."""
        config = db.query(cls).filter(cls.config_key == key).first()
        return config.config_value if config else default
    
    @classmethod
    def set_value(cls, db, key: str, value: str) -> None:
        """Set configuration value by key."""
        config = db.query(cls).filter(cls.config_key == key).first()
        if config:
            config.config_value = value
            config.updated_at = datetime.utcnow()
        else:
            config = cls(config_key=key, config_value=value)
            db.add(config)
        db.commit()
    
    @classmethod
    def init_defaults(cls, db) -> None:
        """Initialize default configuration values."""
        defaults = {
            'monitoring_active': 'false',
            'monitoring_interval': '5',
            'monitoring_started_at': None,
        }
        for key, value in defaults.items():
            exists = db.query(cls).filter(cls.config_key == key).first()
            if not exists:
                db.add(cls(config_key=key, config_value=value))
        db.commit()
