"""Add progress tracking fields to analysis_tasks

Revision ID: 17e7696578ef
Revises: e7d2767e750b
Create Date: 2026-03-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '17e7696578ef'
down_revision: Union[str, Sequence[str], None] = 'e7d2767e750b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add progress tracking columns to analysis_tasks table."""
    # Add columns
    op.add_column('analysis_tasks', sa.Column('agents_progress', JSONB, nullable=True))
    op.add_column('analysis_tasks', sa.Column('current_agent', sa.String(50), nullable=True))
    op.add_column('analysis_tasks', sa.Column('progress_pct', sa.Integer, nullable=True))
    op.add_column('analysis_tasks', sa.Column('logs', JSONB, nullable=True))


def downgrade() -> None:
    """Remove progress tracking columns from analysis_tasks table."""
    op.drop_column('analysis_tasks', 'logs')
    op.drop_column('analysis_tasks', 'progress_pct')
    op.drop_column('analysis_tasks', 'current_agent')
    op.drop_column('analysis_tasks', 'agents_progress')
