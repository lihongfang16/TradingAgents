"""add_position_context_to_analysis_tasks

Revision ID: 0ac58bc764c0
Revises: a5b6c7d8e9f0
Create Date: 2026-04-16 13:48:10.606698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ac58bc764c0'
down_revision: Union[str, Sequence[str], None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add position_context JSONB column to analysis_tasks."""
    from sqlalchemy.dialects.postgresql import JSONB
    op.add_column(
        'analysis_tasks',
        sa.Column('position_context', JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    """Drop position_context column."""
    op.drop_column('analysis_tasks', 'position_context')
