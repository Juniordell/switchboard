"""platform tables: calls, tool_calls, review_queue

The NOTIFY trigger is hand-written, as in 0005. Autogenerate emits tables
and nothing else.

`ops.tool_calls` is what makes the live feed possible: hard rule 5's seven
fields have been a log line since T3.1, and a log line does not cross a
process boundary. As a row it can be announced, and T6.2's SSE endpoint
listens for exactly that.

The payload carries the row id and enough to route on, never `args`, which
has no bound - Postgres caps a notification at 8000 bytes.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOOL_CALL_CHANNEL = "switchboard_tool_calls"

_NOTIFY_FUNCTION = """
CREATE OR REPLACE FUNCTION ops.notify_tool_call() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify(
        'switchboard_tool_calls',
        json_build_object(
            'id', NEW.id,
            'call_id', NEW.call_id,
            'agent', NEW.agent,
            'tool', NEW.tool,
            'ok', NEW.ok,
            'duration_ms', NEW.duration_ms,
            'result_rows', NEW.result_rows,
            'created_at', NEW.created_at
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_NOTIFY_TRIGGER = """
CREATE TRIGGER tool_calls_notify
AFTER INSERT ON ops.tool_calls
FOR EACH ROW EXECUTE FUNCTION ops.notify_tool_call();
"""


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("caller", sa.String(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_agent", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("call_id", name=op.f("pk_calls")),
        schema="ops",
    )
    op.create_index(
        "ix_calls_started_at", "calls", ["started_at"], unique=False, schema="ops"
    )
    op.create_table(
        "review_queue",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_queue")),
        schema="ops",
    )
    op.create_index(
        "ix_review_queue_status", "review_queue", ["status"], unique=False, schema="ops"
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("result_rows", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("timings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_calls")),
        schema="ops",
    )
    op.create_index(
        "ix_tool_calls_call_id", "tool_calls", ["call_id"], unique=False, schema="ops"
    )
    op.create_index(
        "ix_tool_calls_created_at",
        "tool_calls",
        ["created_at"],
        unique=False,
        schema="ops",
    )

    op.execute(_NOTIFY_FUNCTION)
    op.execute(_NOTIFY_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tool_calls_notify ON ops.tool_calls")
    op.execute("DROP FUNCTION IF EXISTS ops.notify_tool_call()")

    op.drop_index("ix_tool_calls_created_at", table_name="tool_calls", schema="ops")
    op.drop_index("ix_tool_calls_call_id", table_name="tool_calls", schema="ops")
    op.drop_table("tool_calls", schema="ops")
    op.drop_index("ix_review_queue_status", table_name="review_queue", schema="ops")
    op.drop_table("review_queue", schema="ops")
    op.drop_index("ix_calls_started_at", table_name="calls", schema="ops")
    op.drop_table("calls", schema="ops")
