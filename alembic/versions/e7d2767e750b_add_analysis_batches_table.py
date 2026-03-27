"""Add analysis_batches table

Revision ID: e7d2767e750b
Revises: feeb0bc86f8d
Create Date: 2026-03-26 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'e7d2767e750b'
down_revision: Union[str, Sequence[str], None] = 'feeb0bc86f8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create analysis_batches table
    op.create_table(
        'analysis_batches',
        sa.Column('batch_id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('total', sa.Integer, nullable=False, default=0),
        sa.Column('completed_count', sa.Integer, nullable=False, default=0),
        sa.Column('failed_count', sa.Integer, nullable=False, default=0),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('task_ids', JSONB, nullable=False, default=list),
        sa.Column('symbols', JSONB, nullable=True),
        sa.Column('message', sa.Text, nullable=True),
        sa.Column('error', sa.Text, nullable=True),
    )
    
    # Create indexes
    op.create_index('idx_analysis_batches_status', 'analysis_batches', ['status'])
    op.create_index('idx_analysis_batches_created_at', 'analysis_batches', ['created_at'])
    op.create_index('idx_analysis_batches_status_created', 'analysis_batches', ['status', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('idx_analysis_batches_status_created', table_name='analysis_batches')
    op.drop_index('idx_analysis_batches_created_at', table_name='analysis_batches')
    op.drop_index('idx_analysis_batches_status', table_name='analysis_batches')
    
    # Drop table
    op.drop_table('analysis_batches')
