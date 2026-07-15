"""separate personal agents from device nodes

Revision ID: 202607130002
Revises: 202607130001
Create Date: 2026-07-13 00:02:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607130002"
down_revision: str | None = "202607130001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "personal_agents" not in tables:
        op.create_table(
            "personal_agents",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("active_clone_id", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["active_clone_id"], ["clone_agents.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
        op.create_index(
            op.f("ix_personal_agents_active_clone_id"),
            "personal_agents",
            ["active_clone_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_personal_agents_user_id"),
            "personal_agents",
            ["user_id"],
            unique=True,
        )

    if "device_nodes" not in tables:
        op.create_table(
            "device_nodes",
            sa.Column("node_id", sa.String(length=64), nullable=False),
            sa.Column("personal_agent_id", sa.String(length=64), nullable=False),
            sa.Column("public_key", sa.String(length=200), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["personal_agent_id"], ["personal_agents.id"]),
            sa.PrimaryKeyConstraint("node_id"),
            sa.UniqueConstraint(
                "personal_agent_id", "node_id", name="uq_device_personal_node"
            ),
        )
        op.create_index(
            op.f("ix_device_nodes_personal_agent_id"),
            "device_nodes",
            ["personal_agent_id"],
            unique=False,
        )

    peer_columns = {column["name"] for column in inspector.get_columns("peer_agents")}
    if "personal_agent_id" not in peer_columns:
        op.add_column(
            "peer_agents",
            sa.Column("personal_agent_id", sa.String(length=64), nullable=True),
        )
        op.create_index(
            op.f("ix_peer_agents_personal_agent_id"),
            "peer_agents",
            ["personal_agent_id"],
            unique=False,
        )

    negotiation_columns = {
        column["name"] for column in inspector.get_columns("negotiation_sessions")
    }
    for column_name in ("initiator_agent_id", "responder_agent_id"):
        if column_name not in negotiation_columns:
            op.add_column(
                "negotiation_sessions",
                sa.Column(column_name, sa.String(length=64), nullable=True),
            )
            op.create_index(
                op.f(f"ix_negotiation_sessions_{column_name}"),
                "negotiation_sessions",
                [column_name],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "negotiation_sessions" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("negotiation_sessions")
        }
        for column_name in ("responder_agent_id", "initiator_agent_id"):
            if column_name in columns:
                op.drop_index(
                    op.f(f"ix_negotiation_sessions_{column_name}"),
                    table_name="negotiation_sessions",
                )
                op.drop_column("negotiation_sessions", column_name)
    if "peer_agents" in tables:
        columns = {column["name"] for column in inspector.get_columns("peer_agents")}
        if "personal_agent_id" in columns:
            op.drop_index(
                op.f("ix_peer_agents_personal_agent_id"), table_name="peer_agents"
            )
            op.drop_column("peer_agents", "personal_agent_id")
    if "device_nodes" in tables:
        op.drop_table("device_nodes")
    if "personal_agents" in tables:
        op.drop_table("personal_agents")
