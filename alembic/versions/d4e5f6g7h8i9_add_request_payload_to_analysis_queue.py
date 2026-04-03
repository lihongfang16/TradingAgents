"""Add request_payload to analysis_queue

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-04-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd4e5f6g7h8i9'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade():
    # Add request_payload column to analysis_queue
    op.add_column(
        'analysis_queue',
        sa.Column('request_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade():
    # Drop request_payload column
    op.drop_column('analysis_queue', 'request_payload')
