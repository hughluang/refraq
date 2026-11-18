"""Retain capture bindings and durable executable control intent."""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0093_source_capture_control"
down_revision = "0092_job_delayed_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_capture_bindings",
        sa.Column(
            "source_id",
            sa.String(64),
            sa.ForeignKey("sources.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("binding_id", sa.String(64), unique=True, nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
    )
    op.create_table(
        "source_capture_operations",
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(64),
            sa.ForeignKey("source_capture_bindings.source_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_source_capture_operations_source_id",
        "source_capture_operations",
        ["source_id"],
    )
    bindings = sa.table(
        "source_capture_bindings",
        sa.column("source_id"),
        sa.column("binding_id"),
        sa.column("state", sa.JSON()),
    )
    for source in (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id, capture_revision FROM sources "
                "WHERE capture_credential_ciphertext IS NOT NULL OR capture_revision > 0"
            )
        )
        .mappings()
    ):
        state = {
            "source_id": source["id"],
            "binding_id": f"cap_{uuid4().hex}",
            "capture_generation": 1,
            "owner_epoch": 0,
            "runtime_instance_id": None,
            "control_revision": 0,
            "credential_revision": source["capture_revision"],
            "applied_revision": None,
            "observed_at": None,
            "stop_ack": None,
            "desired": "blocked",
        }
        op.get_bind().execute(
            bindings.insert().values(
                source_id=source["id"],
                binding_id=state["binding_id"],
                state=state,
            )
        )


def downgrade() -> None:
    op.drop_index("ix_source_capture_operations_source_id", "source_capture_operations")
    op.drop_table("source_capture_operations")
    op.drop_table("source_capture_bindings")
