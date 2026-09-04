"""call traceparent

One trace has to cover the phone call and the pipeline that runs after it.
Those are different processes minutes apart, and OpenTelemetry context
survives neither gap on its own, so the call carries its own traceparent
and the worker re-enters the trace from it.

Revision ID: d4337ab41fa6
Revises: 0008
Create Date: 2026-09-04 00:02:05.422895+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calls", sa.Column("traceparent", sa.String(), nullable=True), schema="ops"
    )


def downgrade() -> None:
    op.drop_column("calls", "traceparent", schema="ops")
