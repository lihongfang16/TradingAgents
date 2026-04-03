"""add price and error_message to watchlist_analysis

Revision ID: 2c3d4e5f6g7h
Revises: e37df11b4061
Create Date: 2026-03-30 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c3d4e5f6g7h'
down_revision: Union[str, Sequence[str], None] = 'e37df11b4061'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('watchlist_analyses')}

    if 'price' not in columns:
        op.add_column('watchlist_analyses', sa.Column('price', sa.String(length=20), nullable=True))
    if 'error_message' not in columns:
        op.add_column('watchlist_analyses', sa.Column('error_message', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Drop error_message column
    op.drop_column('watchlist_analyses', 'error_message')
    # Drop price column
    op.drop_column('watchlist_analyses', 'price')
