"""Initial schema

Revision ID: feeb0bc86f8d
Revises: 
Create Date: 2026-03-26 15:41:45.851999

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'feeb0bc86f8d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create analysis_tasks table
    op.create_table(
        'analysis_tasks',
        sa.Column('task_id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('result', JSONB, nullable=True),
        sa.Column('decision', sa.String(10), nullable=True),
        sa.Column('confidence', sa.Integer, nullable=True),
        sa.Column('message', sa.Text, nullable=True),
        sa.Column('error', sa.Text, nullable=True),
    )
    
    # Create indexes
    op.create_index('idx_analysis_tasks_symbol', 'analysis_tasks', ['symbol'])
    op.create_index('idx_analysis_tasks_status', 'analysis_tasks', ['status'])
    op.create_index('idx_analysis_tasks_created_at', 'analysis_tasks', ['created_at'])
    op.create_index('idx_analysis_tasks_symbol_status', 'analysis_tasks', ['symbol', 'status'])
    op.create_index('idx_analysis_tasks_created_status', 'analysis_tasks', ['created_at', 'status'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('idx_analysis_tasks_created_status', table_name='analysis_tasks')
    op.drop_index('idx_analysis_tasks_symbol_status', table_name='analysis_tasks')
    op.drop_index('idx_analysis_tasks_created_at', table_name='analysis_tasks')
    op.drop_index('idx_analysis_tasks_status', table_name='analysis_tasks')
    op.drop_index('idx_analysis_tasks_symbol', table_name='analysis_tasks')
    
    # Drop table
    op.drop_table('analysis_tasks')
