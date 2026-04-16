"""Add position fields to watchlist

Revision ID: a5b6c7d8e9f0
Revises: 393effabffe8
Create Date: 2026-04-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a5b6c7d8e9f0'
down_revision = '393effabffe8'
branch_labels = None
depends_on = None


def upgrade():
    # Add position tracking columns to watchlist
    op.add_column(
        'watchlist',
        sa.Column('cost_price', sa.String(20), nullable=True)
    )
    op.add_column(
        'watchlist',
        sa.Column('position_shares', sa.String(20), nullable=True)
    )
    op.add_column(
        'watchlist',
        sa.Column('target_position_pct', sa.String(20), nullable=True)
    )


def downgrade():
    # Drop position tracking columns
    op.drop_column('watchlist', 'target_position_pct')
    op.drop_column('watchlist', 'position_shares')
    op.drop_column('watchlist', 'cost_price')
