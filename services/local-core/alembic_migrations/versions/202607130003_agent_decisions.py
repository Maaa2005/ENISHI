"""add peer aliases and negotiation decisions

Revision ID: 202607130003
Revises: 202607130002
Create Date: 2026-07-13 00:03:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607130003"
down_revision: str | None = "202607130002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    peer_columns = {column["name"] for column in inspector.get_columns("peer_agents")}
    if "aliases" not in peer_columns:
        op.add_column(
            "peer_agents",
            sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        )

    if "negotiation_decisions" not in tables:
        op.create_table(
            "negotiation_decisions",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("session_id", sa.String(length=32), nullable=False),
            sa.Column("clone_id", sa.String(length=32), nullable=False),
            sa.Column("policy_version", sa.Integer(), nullable=False),
            sa.Column("outcome", sa.String(length=32), nullable=False),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["clone_id"], ["clone_agents.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["negotiation_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_negotiation_decisions_clone_id"),
            "negotiation_decisions",
            ["clone_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_negotiation_decisions_outcome"),
            "negotiation_decisions",
            ["outcome"],
            unique=False,
        )
        op.create_index(
            op.f("ix_negotiation_decisions_session_id"),
            "negotiation_decisions",
            ["session_id"],
            unique=False,
        )

    if "relay_outbox" not in tables:
        op.create_table(
            "relay_outbox",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("message_id", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=32), nullable=False),
            sa.Column("approval_id", sa.String(length=32), nullable=True),
            sa.Column("envelope", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["negotiation_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for column, unique in (
            ("approval_id", True),
            ("message_id", True),
            ("session_id", False),
            ("status", False),
        ):
            op.create_index(
                op.f(f"ix_relay_outbox_{column}"),
                "relay_outbox",
                [column],
                unique=unique,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "relay_outbox" in tables:
        for column in ("status", "session_id", "message_id", "approval_id"):
            op.drop_index(op.f(f"ix_relay_outbox_{column}"), table_name="relay_outbox")
        op.drop_table("relay_outbox")
    if "negotiation_decisions" in tables:
        op.drop_index(
            op.f("ix_negotiation_decisions_session_id"),
            table_name="negotiation_decisions",
        )
        op.drop_index(
            op.f("ix_negotiation_decisions_outcome"),
            table_name="negotiation_decisions",
        )
        op.drop_index(
            op.f("ix_negotiation_decisions_clone_id"),
            table_name="negotiation_decisions",
        )
        op.drop_table("negotiation_decisions")
    peer_columns = {column["name"] for column in inspector.get_columns("peer_agents")}
    if "aliases" in peer_columns:
        op.drop_column("peer_agents", "aliases")
