"""Derived install date, one row per canonical address that has one.

`knowledge.install_dates` is built from jobs whose description identifies a
whole-system install, most recent per canonical address. See T2.3a in
docs/TASKS.md and the InstallDate model's docstring, including why
canonical_id cascades on delete.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "install_dates",
        sa.Column("canonical_id", sa.String(), nullable=False),
        sa.Column("install_job_id", sa.String(), nullable=False),
        sa.Column("install_date", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_id"],
            ["knowledge.canonical_addresses.canonical_id"],
            name=op.f("fk_install_dates_canonical_id_canonical_addresses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["install_job_id"],
            ["source.jobs.id"],
            name=op.f("fk_install_dates_install_job_id_jobs"),
        ),
        sa.PrimaryKeyConstraint("canonical_id", name=op.f("pk_install_dates")),
        schema="knowledge",
    )
    op.create_index(
        op.f("ix_install_dates_install_job_id"),
        "install_dates",
        ["install_job_id"],
        unique=False,
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_install_dates_install_job_id"),
        table_name="install_dates",
        schema="knowledge",
    )
    op.drop_table("install_dates", schema="knowledge")
    # ### end Alembic commands ###
