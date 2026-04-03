"""merge heads for watchlist overlay work

Revision ID: b2c3d4e5f6g7
Revises: 17e95f0a1b2c, a1b2c3d4e5f6
Create Date: 2026-04-03 10:00:00.000000
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, Sequence[str], None] = ("17e95f0a1b2c", "a1b2c3d4e5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge Alembic heads without schema changes."""


def downgrade() -> None:
    """Downgrade merge revision without schema changes."""
