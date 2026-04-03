"""widen signal columns for 5-tier rating

Revision ID: 3d4e5f6g7h8i
Revises: 2c3d4e5f6g7h
Create Date: 2026-03-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d4e5f6g7h8i'
down_revision: Union[str, Sequence[str], None] = '2c3d4e5f6g7h'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen signal columns to support 5-tier rating (UNDERWEIGHT=11 chars)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    watchlist_columns = {column['name']: column for column in inspector.get_columns('watchlist')}
    analysis_columns = {column['name']: column for column in inspector.get_columns('watchlist_analyses')}

    # Widen watchlist.last_signal from String(10) to String(20)
    if getattr(watchlist_columns['last_signal']['type'], 'length', None) != 20:
        op.alter_column('watchlist', 'last_signal',
                        existing_type=sa.String(10),
                        type_=sa.String(20),
                        existing_nullable=True)
    
    # Widen watchlist_analyses.signal from String(10) to String(20)
    if getattr(analysis_columns['signal']['type'], 'length', None) != 20:
        op.alter_column('watchlist_analyses', 'signal',
                        existing_type=sa.String(10),
                        type_=sa.String(20),
                        existing_nullable=True)


def downgrade() -> None:
    """Narrow signal columns back to String(10)."""
    # Narrow watchlist_analyses.signal back to String(10)
    op.alter_column('watchlist_analyses', 'signal',
                    existing_type=sa.String(20),
                    type_=sa.String(10),
                    existing_nullable=True)
    
    # Narrow watchlist.last_signal back to String(10)
    op.alter_column('watchlist', 'last_signal',
                    existing_type=sa.String(20),
                    type_=sa.String(10),
                    existing_nullable=True)
