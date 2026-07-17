"""add peer card capabilities

Revision ID: 202607180001
Revises: 202607130003
Create Date: 2026-07-18 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607180001"
down_revision: str | None = "202607130003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("peer_agents")}
    if "capabilities" not in columns:
        op.add_column(
            "peer_agents",
            sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("peer_agents")}
    if "capabilities" in columns:
        op.drop_column("peer_agents", "capabilities")
