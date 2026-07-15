"""agent setup settings

Revision ID: 202607130001
Revises: 202607120002
Create Date: 2026-07-13 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607130001"
down_revision: str | None = "202607120002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "nickname" not in user_columns:
        op.add_column("users", sa.Column("nickname", sa.String(length=200), nullable=True))

    if "memory_source_settings" not in tables:
        op.create_table(
            "memory_source_settings",
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("connected", sa.Boolean(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("scope", sa.String(length=500), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("source"),
        )

    if "default_disclosure_policy" not in tables:
        op.create_table(
            "default_disclosure_policy",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("allowed_memory_types", sa.JSON(), nullable=False),
            sa.Column("max_sensitivity", sa.String(length=16), nullable=False),
            sa.Column("share_schedule", sa.Boolean(), nullable=False),
            sa.Column("share_skills", sa.Boolean(), nullable=False),
            sa.Column("extra", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "default_disclosure_policy" in tables:
        op.drop_table("default_disclosure_policy")
    if "memory_source_settings" in tables:
        op.drop_table("memory_source_settings")
    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "nickname" in user_columns:
            op.drop_column("users", "nickname")
