"""align watchlist analysis price column type

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-04-03 10:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Align watchlist_analyses.price with ORM float storage."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    price_column = next(
        column for column in inspector.get_columns('watchlist_analyses') if column['name'] == 'price'
    )

    if not isinstance(price_column['type'], sa.Float):
        op.alter_column(
            "watchlist_analyses",
            "price",
            existing_type=sa.String(length=20),
            type_=sa.Float(),
            existing_nullable=True,
            postgresql_using="NULLIF(price, '')::double precision",
        )


def downgrade() -> None:
    """Restore string-based price storage."""
    op.alter_column(
        "watchlist_analyses",
        "price",
        existing_type=sa.Float(),
        type_=sa.String(length=20),
        existing_nullable=True,
        postgresql_using="price::text",
    )
