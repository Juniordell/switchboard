"""ops writes: bookings, reschedules, agent notes, and the write audit

Two things autogenerate does not produce, both added by hand here:

1. ``CREATE SCHEMA ops``. Autogenerate emits tables, never the schema they
   live in, exactly as in 0002 and 0004.
2. The ``NOTIFY`` trigger. Every insert into ``ops.write_audit`` emits on
   the ``switchboard_writes`` channel, which T6.2 turns into SSE. Putting
   it in a trigger rather than in the tools means a future write cannot
   forget to announce itself - and because Postgres holds notifications
   until commit, a write that rolls back never announces one either, which
   application-level code would have had to arrange for deliberately.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Small on purpose: the row id and enough to route on. A consumer that
#: wants the values reads the audit row. Postgres caps a payload at 8000
#: bytes, and `new_values` has no bound.
_NOTIFY_FUNCTION = """
CREATE OR REPLACE FUNCTION ops.notify_write() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify(
        'switchboard_writes',
        json_build_object(
            'audit_id', NEW.id,
            'tool', NEW.tool,
            'action', NEW.action,
            'job_id', NEW.job_id,
            'call_id', NEW.call_id
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_NOTIFY_TRIGGER = """
CREATE TRIGGER write_audit_notify
AFTER INSERT ON ops.write_audit
FOR EACH ROW EXECUTE FUNCTION ops.notify_write();
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.create_table(
        "agent_notes",
        sa.Column("note_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("note_id", name=op.f("pk_agent_notes")),
        schema="ops",
    )
    op.create_index(
        "ix_agent_notes_job_id", "agent_notes", ["job_id"], unique=False, schema="ops"
    )

    op.create_table(
        "booked_jobs",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("canonical_id", sa.String(), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_window", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("display_address", sa.String(), nullable=False),
        sa.Column("tech_id", sa.String(), nullable=True),
        sa.Column("tech_name", sa.String(), nullable=True),
        sa.Column("work_status", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_booked_jobs")),
        schema="ops",
    )
    op.create_index(
        "ix_booked_jobs_customer_id",
        "booked_jobs",
        ["customer_id"],
        unique=False,
        schema="ops",
    )
    op.create_index(
        "ix_booked_jobs_scheduled_start",
        "booked_jobs",
        ["scheduled_start"],
        unique=False,
        schema="ops",
    )

    op.create_table(
        "job_reschedules",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_job_reschedules")),
        schema="ops",
    )

    op.create_table(
        "write_audit",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("old_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("spoken_confirmation", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_write_audit")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_write_audit_idempotency_key")
        ),
        schema="ops",
    )
    op.create_index(
        "ix_write_audit_call_id", "write_audit", ["call_id"], unique=False, schema="ops"
    )
    op.create_index(
        "ix_write_audit_job_id", "write_audit", ["job_id"], unique=False, schema="ops"
    )

    op.execute(_NOTIFY_FUNCTION)
    op.execute(_NOTIFY_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS write_audit_notify ON ops.write_audit")
    op.execute("DROP FUNCTION IF EXISTS ops.notify_write()")

    op.drop_index("ix_write_audit_job_id", table_name="write_audit", schema="ops")
    op.drop_index("ix_write_audit_call_id", table_name="write_audit", schema="ops")
    op.drop_table("write_audit", schema="ops")
    op.drop_table("job_reschedules", schema="ops")
    op.drop_index(
        "ix_booked_jobs_scheduled_start", table_name="booked_jobs", schema="ops"
    )
    op.drop_index("ix_booked_jobs_customer_id", table_name="booked_jobs", schema="ops")
    op.drop_table("booked_jobs", schema="ops")
    op.drop_index("ix_agent_notes_job_id", table_name="agent_notes", schema="ops")
    op.drop_table("agent_notes", schema="ops")

    op.execute("DROP SCHEMA IF EXISTS ops")
