"""Canonical addresses and the alias mapping onto them.

The source has no address entity - see
`switchboard_core.knowledge.address_normalize` for why `address.id` cannot be
the key. This module holds the two tables that fix that:

`canonical_addresses`
    One row per physically distinct address, 1,359 of them. `canonical_id` is
    `uuid5(NAMESPACE, normalised key)`, so it is the same value on every load
    without depending on row order.

`address_alias`
    Every source `address.id` (1,390, minus the one row with no address at
    all) mapped onto its `canonical_id`. `resolve_address` and every derived
    table join through this, never through `address.id` directly.
"""

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import KNOWLEDGE_SCHEMA, SOURCE_SCHEMA, Base


class CanonicalAddress(Base):
    __tablename__ = "canonical_addresses"
    __table_args__ = (
        # gin_trgm_ops backs both the similarity ranking resolve_address does
        # and the % operator that lets Postgres use the index to pre-filter
        # candidates instead of computing similarity() against all 1,359 rows.
        Index(
            "ix_canonical_addresses_street_trgm",
            "street_normalized",
            postgresql_using="gin",
            postgresql_ops={"street_normalized": "gin_trgm_ops"},
        ),
        Index("ix_canonical_addresses_zip", "zip"),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    canonical_id: Mapped[str] = mapped_column(String, primary_key=True)
    street_normalized: Mapped[str] = mapped_column(String)
    unit_normalized: Mapped[str] = mapped_column(String)
    zip: Mapped[str] = mapped_column(String)

    # Human-facing display fields, picked from one representative source row
    # per canonical group (the lowest address_id, for a stable, deterministic
    # choice across re-loads). Never used for matching - only for what a tool
    # result or a screen shows a person.
    display_street: Mapped[str] = mapped_column(String)
    display_unit: Mapped[str | None] = mapped_column(String)
    display_city: Mapped[str | None] = mapped_column(String)
    display_state: Mapped[str | None] = mapped_column(String)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class AddressAlias(Base):
    __tablename__ = "address_alias"
    __table_args__ = {"schema": KNOWLEDGE_SCHEMA}

    address_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SOURCE_SCHEMA}.customer_addresses.address_id"),
        primary_key=True,
    )
    canonical_id: Mapped[str] = mapped_column(
        ForeignKey(f"{KNOWLEDGE_SCHEMA}.canonical_addresses.canonical_id"),
        index=True,
    )
