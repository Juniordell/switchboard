"""Canonical addresses: the Entities layer's address table.

`knowledge.canonical_addresses` holds one row per physically distinct address
(1,359 of them, over the 1,390 rows of `source.customer_addresses`).
`knowledge.address_alias` maps every source `address.id` onto its
`canonical_id`, so nothing downstream ever joins on `address.id` directly.

Also promotes `source.customer_addresses.address_id` from a plain index to a
unique constraint - it was already unique in the data (verified in T1.3), and
`address_alias.address_id` needs a real target to be a real foreign key rather
than a reference the loader merely promises to keep honest.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_addresses",
        sa.Column("canonical_id", sa.String(), nullable=False),
        sa.Column("street_normalized", sa.String(), nullable=False),
        sa.Column("unit_normalized", sa.String(), nullable=False),
        sa.Column("zip", sa.String(), nullable=False),
        sa.Column("display_street", sa.String(), nullable=False),
        sa.Column("display_unit", sa.String(), nullable=True),
        sa.Column("display_city", sa.String(), nullable=True),
        sa.Column("display_state", sa.String(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("canonical_id", name=op.f("pk_canonical_addresses")),
        schema="knowledge",
    )
    op.create_index(
        "ix_canonical_addresses_street_trgm",
        "canonical_addresses",
        ["street_normalized"],
        unique=False,
        schema="knowledge",
        postgresql_using="gin",
        postgresql_ops={"street_normalized": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_canonical_addresses_zip",
        "canonical_addresses",
        ["zip"],
        unique=False,
        schema="knowledge",
    )
    # The unique constraint must exist before address_alias's foreign key can
    # reference customer_addresses.address_id - autogenerate ordered these the
    # other way round and the upgrade failed with InvalidForeignKey.
    op.drop_index(
        op.f("ix_customer_addresses_address_id"),
        table_name="customer_addresses",
        schema="source",
    )
    op.create_unique_constraint(
        op.f("uq_customer_addresses_address_id"),
        "customer_addresses",
        ["address_id"],
        schema="source",
    )
    op.create_table(
        "address_alias",
        sa.Column("address_id", sa.String(), nullable=False),
        sa.Column("canonical_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["address_id"],
            ["source.customer_addresses.address_id"],
            name=op.f("fk_address_alias_address_id_customer_addresses"),
        ),
        sa.ForeignKeyConstraint(
            ["canonical_id"],
            ["knowledge.canonical_addresses.canonical_id"],
            name=op.f("fk_address_alias_canonical_id_canonical_addresses"),
        ),
        sa.PrimaryKeyConstraint("address_id", name=op.f("pk_address_alias")),
        schema="knowledge",
    )
    op.create_index(
        op.f("ix_address_alias_canonical_id"),
        "address_alias",
        ["canonical_id"],
        unique=False,
        schema="knowledge",
    )


def downgrade() -> None:
    # Mirror image of upgrade's reordering: address_alias must go before the
    # unique constraint its foreign key depends on can be dropped.
    op.drop_index(
        op.f("ix_address_alias_canonical_id"),
        table_name="address_alias",
        schema="knowledge",
    )
    op.drop_table("address_alias", schema="knowledge")
    op.drop_constraint(
        op.f("uq_customer_addresses_address_id"),
        "customer_addresses",
        schema="source",
        type_="unique",
    )
    op.create_index(
        op.f("ix_customer_addresses_address_id"),
        "customer_addresses",
        ["address_id"],
        unique=False,
        schema="source",
    )
    op.drop_index(
        "ix_canonical_addresses_zip",
        table_name="canonical_addresses",
        schema="knowledge",
    )
    op.drop_index(
        "ix_canonical_addresses_street_trgm",
        table_name="canonical_addresses",
        schema="knowledge",
        postgresql_using="gin",
        postgresql_ops={"street_normalized": "gin_trgm_ops"},
    )
    op.drop_table("canonical_addresses", schema="knowledge")
