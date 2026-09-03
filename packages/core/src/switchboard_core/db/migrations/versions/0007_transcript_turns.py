"""transcript turns

Nothing stored what was said before this. A call log that lists tool calls
with no words around them tells an office manager what the machine did and
nothing about what the caller wanted.

Revision ID: 9c3576b4e8f7
Revises: 0006
Create Date: 2026-09-03 23:24:59.170480+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcript_turns")),
        schema="ops",
    )
    op.create_index(
        "ix_transcript_turns_call_id",
        "transcript_turns",
        ["call_id", "seq"],
        unique=False,
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transcript_turns_call_id", table_name="transcript_turns", schema="ops"
    )
    op.drop_table("transcript_turns", schema="ops")
