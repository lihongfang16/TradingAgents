"""Add watchlist and watchlist_analyses tables

Revision ID: xxxx_add_watchlist_tables
Revises: 17e7696578ef
Create Date: 2026-03-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'xxxx_add_watchlist_tables'
down_revision: Union[str, Sequence[str], None] = '17e7696578ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create watchlist and watchlist_analyses tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'watchlist' not in inspector.get_table_names():
        op.create_table(
            'watchlist',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('symbol', sa.String(20), nullable=False, unique=True),
            sa.Column('name', sa.String(100), nullable=True),
            sa.Column('exchange', sa.String(10), nullable=True),
            sa.Column('added_at', sa.DateTime, nullable=False, default=sa.func.now()),
            sa.Column('is_active', sa.String(1), nullable=False, default='Y'),
            sa.Column('turning_detection_enabled', sa.String(1), nullable=False, default='Y'),
            sa.Column('confidence_jump_threshold', sa.String(10), nullable=False, default='0.15'),
            sa.Column('last_analysis_at', sa.DateTime, nullable=True),
            sa.Column('last_signal', sa.String(10), nullable=True),
            sa.Column('last_confidence', sa.String(10), nullable=True),
            sa.Column('last_risk_level', sa.String(20), nullable=True),
            sa.Column('is_high_frequency', sa.String(1), nullable=False, default='N'),
            sa.Column('high_freq_until', sa.DateTime, nullable=True),
            sa.Column('last_price', sa.String(20), nullable=True),
            sa.Column('last_change_pct', sa.String(10), nullable=True),
        )

    watchlist_indexes = {idx['name'] for idx in inspector.get_indexes('watchlist')}
    if 'idx_watchlist_symbol_active' not in watchlist_indexes:
        op.create_index('idx_watchlist_symbol_active', 'watchlist', ['symbol', 'is_active'])
    if 'idx_watchlist_high_freq' not in watchlist_indexes:
        op.create_index('idx_watchlist_high_freq', 'watchlist', ['is_high_frequency', 'high_freq_until'])

    if 'watchlist_analyses' not in inspector.get_table_names():
        op.create_table(
            'watchlist_analyses',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('watchlist_id', sa.Integer, nullable=False, index=True),
            sa.Column('analysis_id', sa.String(36), nullable=True, index=True),
            sa.Column('analysis_type', sa.String(20), nullable=False),
            sa.Column('triggered_by', sa.String(20), nullable=False, default='scheduled'),
            sa.Column('created_at', sa.DateTime, nullable=False, default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime, nullable=True),
            sa.Column('signal', sa.String(10), nullable=True),
            sa.Column('confidence', sa.String(10), nullable=True),
            sa.Column('risk_level', sa.String(20), nullable=True),
            sa.Column('is_turning_point', sa.String(1), nullable=False, default='N'),
            sa.Column('turning_reason', sa.Text, nullable=True),
            sa.Column('importance_score', sa.String(10), nullable=True),
            sa.Column('alert_sent', sa.String(1), nullable=False, default='N'),
            sa.Column('alert_sent_at', sa.DateTime, nullable=True),
        )

    analysis_indexes = {idx['name'] for idx in inspector.get_indexes('watchlist_analyses')}
    if 'idx_watchlist_analyses_watchlist_id' not in analysis_indexes:
        op.create_index('idx_watchlist_analyses_watchlist_id', 'watchlist_analyses', ['watchlist_id', 'created_at'])
    if 'idx_watchlist_analyses_turning' not in analysis_indexes:
        op.create_index('idx_watchlist_analyses_turning', 'watchlist_analyses', ['is_turning_point', 'created_at'])


def downgrade() -> None:
    """Drop watchlist_analyses and watchlist tables."""
    op.drop_index('idx_watchlist_analyses_turning', table_name='watchlist_analyses')
    op.drop_index('idx_watchlist_analyses_watchlist_id', table_name='watchlist_analyses')
    op.drop_table('watchlist_analyses')
    op.drop_index('idx_watchlist_high_freq', table_name='watchlist')
    op.drop_index('idx_watchlist_symbol_active', table_name='watchlist')
    op.drop_table('watchlist')
