"""Add reference_capital to watchlist

Revision ID: b6c7d8e9f0a1
Revises: 0ac58bc764c0
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6c7d8e9f0a1'
down_revision = '0ac58bc764c0'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('watchlist', sa.Column('reference_capital', sa.String(20), nullable=True))

def downgrade():
    op.drop_column('watchlist', 'reference_capital')