"""add analyst_report_cache table with TTL support

Revision ID: a1b2c3d4e5f6
Revises: 3d4e5f6g7h8i
Create Date: 2026-03-31 08:00:00.000000

"""

# pyright: reportDeprecated=false, reportUnusedCallResult=false

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "3d4e5f6g7h8i"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - create analyst_report_cache table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "analyst_report_cache" not in inspector.get_table_names():
        _ = op.create_table(
            "analyst_report_cache",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("symbol", sa.String(length=20), nullable=False),
            sa.Column("analyst_type", sa.String(length=20), nullable=False),
            sa.Column("analysis_date", sa.Date(), nullable=False),
            sa.Column("report_content", sa.Text(), nullable=False),
            sa.Column("cache_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("lock_session_id", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("analyst_report_cache")}

    if "ix_analyst_report_cache_symbol_analyst_type_date" not in indexes:
        op.create_index(
            "ix_analyst_report_cache_symbol_analyst_type_date",
            "analyst_report_cache",
            ["symbol", "analyst_type", "analysis_date"],
        )

    if "ix_analyst_report_cache_lock_session" not in indexes:
        op.create_index(
            "ix_analyst_report_cache_lock_session",
            "analyst_report_cache",
            ["lock_session_id"],
            postgresql_where=text("is_valid = true"),
        )

    if "ix_analyst_report_cache_expires" not in indexes:
        op.create_index(
            "ix_analyst_report_cache_expires",
            "analyst_report_cache",
            ["expires_at"],
            postgresql_where=text("is_valid = true"),
        )


def downgrade() -> None:
    """Downgrade schema - drop analyst_report_cache table."""
    op.drop_index("ix_analyst_report_cache_expires", table_name="analyst_report_cache")
    op.drop_index("ix_analyst_report_cache_lock_session", table_name="analyst_report_cache")
    op.drop_index("ix_analyst_report_cache_symbol_analyst_type_date", table_name="analyst_report_cache")
    op.drop_table("analyst_report_cache")
