"""add canonical memory backend state

Revision ID: 202607240001
Revises: 202607180001
Create Date: 2026-07-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607240001"
down_revision: str | None = "202607180001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "memory_backend_states" in set(inspector.get_table_names()):
        return
    op.create_table(
        "memory_backend_states",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("primary_source", sa.String(length=64), nullable=False),
        sa.Column("primary_scope", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detected_automatically", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_memory_backend_states_status",
        "memory_backend_states",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "memory_backend_states" in set(inspector.get_table_names()):
        op.drop_index("ix_memory_backend_states_status", table_name="memory_backend_states")
        op.drop_table("memory_backend_states")
