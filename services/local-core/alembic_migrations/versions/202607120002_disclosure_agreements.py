"""add disclosure policies and agreements

Revision ID: 202607120002
Revises: 202607120001
Create Date: 2026-07-12 00:02:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607120002"
down_revision: str | None = "202607120001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "peer_disclosure_policies" not in tables:
        op.create_table(
            "peer_disclosure_policies",
            sa.Column("peer_agent_id", sa.String(length=64), nullable=False),
            sa.Column("allowed_memory_types", sa.JSON(), nullable=False),
            sa.Column("max_sensitivity", sa.String(length=16), nullable=False),
            sa.Column("share_schedule", sa.Boolean(), nullable=False),
            sa.Column("share_skills", sa.Boolean(), nullable=False),
            sa.Column("extra", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["peer_agent_id"], ["peer_agents.agent_id"]),
            sa.PrimaryKeyConstraint("peer_agent_id"),
        )
    if "agreements" not in tables:
        op.create_table(
            "agreements",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("session_id", sa.String(length=32), nullable=False),
            sa.Column("intent", sa.String(length=100), nullable=False),
            sa.Column("initiator_agent_id", sa.String(length=64), nullable=False),
            sa.Column("responder_agent_id", sa.String(length=64), nullable=False),
            sa.Column("agreed_payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("agreed_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["negotiation_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id"),
        )
        op.create_index(
            op.f("ix_agreements_intent"), "agreements", ["intent"], unique=False
        )
        op.create_index(
            op.f("ix_agreements_initiator_agent_id"),
            "agreements",
            ["initiator_agent_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_agreements_responder_agent_id"),
            "agreements",
            ["responder_agent_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_agreements_session_id"), "agreements", ["session_id"], unique=True
        )
        op.create_index(
            op.f("ix_agreements_status"), "agreements", ["status"], unique=False
        )

    negotiation_columns = {
        column["name"] for column in inspector.get_columns("negotiation_sessions")
    }
    if "pending_approval_id" not in negotiation_columns:
        op.add_column(
            "negotiation_sessions",
            sa.Column("pending_approval_id", sa.String(length=32), nullable=True),
        )
        op.create_index(
            op.f("ix_negotiation_sessions_pending_approval_id"),
            "negotiation_sessions",
            ["pending_approval_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "negotiation_sessions" in tables:
        columns = {column["name"] for column in inspector.get_columns("negotiation_sessions")}
        if "pending_approval_id" in columns:
            op.drop_index(
                op.f("ix_negotiation_sessions_pending_approval_id"),
                table_name="negotiation_sessions",
            )
            op.drop_column("negotiation_sessions", "pending_approval_id")
    if "agreements" in tables:
        op.drop_table("agreements")
    if "peer_disclosure_policies" in tables:
        op.drop_table("peer_disclosure_policies")
