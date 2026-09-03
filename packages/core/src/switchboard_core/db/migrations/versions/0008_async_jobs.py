"""async jobs and extractions

The queue announces on its own channel so the worker wakes on a commit
rather than on a timer. A poll loop would add latency to a job that only
ever arrives when a phone call ends.

Revision ID: b742e490d5ff
Revises: 0007
Create Date: 2026-09-03 23:51:27.413405+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NOTIFY = """
CREATE OR REPLACE FUNCTION ops.notify_async_job() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify(
        'switchboard_async_jobs',
        json_build_object('id', NEW.id, 'call_id', NEW.call_id,
                          'kind', NEW.kind)::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_TRIGGER = """
CREATE TRIGGER async_jobs_notify
AFTER INSERT ON ops.async_jobs
FOR EACH ROW EXECUTE FUNCTION ops.notify_async_job();
"""


def upgrade() -> None:
    op.create_table(
        "async_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_async_jobs")),
        schema="ops",
    )
    op.create_index(
        "ix_async_jobs_status",
        "async_jobs",
        ["status", "created_at"],
        unique=False,
        schema="ops",
    )
    op.create_table(
        "extractions",
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("call_id", name=op.f("pk_extractions")),
        schema="ops",
    )

    # review_queue.status had the same Python-only default; 0006 is
    # already merged, so the server default is added here instead.
    op.alter_column("review_queue", "status", server_default="open", schema="ops")

    op.execute(_NOTIFY)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS async_jobs_notify ON ops.async_jobs")
    op.execute("DROP FUNCTION IF EXISTS ops.notify_async_job()")

    op.drop_table("extractions", schema="ops")
    op.drop_index("ix_async_jobs_status", table_name="async_jobs", schema="ops")
    op.drop_table("async_jobs", schema="ops")
