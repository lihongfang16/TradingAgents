"""Add llm_streams column to analysis_tasks

Revision ID: 17e95f0a1b2c
Revises: 17e95ebede9e
Create Date: 2026-04-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "17e95f0a1b2c"
down_revision: Union[str, Sequence[str], None] = "17e95ebede9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add llm_streams JSONB column for storing per-agent LLM output text."""
    op.add_column("analysis_tasks", sa.Column("llm_streams", JSONB, nullable=True))


def downgrade() -> None:
    """Remove llm_streams column."""
    op.drop_column("analysis_tasks", "llm_streams")
