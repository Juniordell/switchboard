"""``data/customers.jsonl`` — 732 customers, 1,390 addresses, 26 tags."""

import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import SOURCE_SCHEMA, Base

#: ``kind`` is ``homeowner`` or ``business`` - not "company", as data/README.md
#: says - and it does not track reality: 31 homeowners carry a company and 48
#: are plainly businesses. Nothing may branch on it alone. See docs/AGENTS.md.
_CUSTOMERS_FK = f"{SOURCE_SCHEMA}.customers.id"


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, index=True)
    job_count: Mapped[int] = mapped_column()
    first_job: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    last_job: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


class CustomerTag(Base):
    """``customers[].tags``. ``position`` preserves array order."""

    __tablename__ = "customer_tags"
    __table_args__ = (
        Index("ix_customer_tags_tag", "tag"),
        {"schema": SOURCE_SCHEMA},
    )

    customer_id: Mapped[str] = mapped_column(
        ForeignKey(_CUSTOMERS_FK), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[str] = mapped_column(String)


class CustomerAddress(Base):
    """``customers[].addresses``.

    ``address_id`` is never null here, unlike on a job. This table is the
    source's address listing, not a deduplicated address entity: the source has
    no standalone address record, and building one is the canonicalisation in
    T2.1.

    ``address_id`` is unique on its own, not only as part of the composite
    primary key: the source mints one per customer-address occurrence, and all
    1,390 rows carry a distinct value, verified in T1.3. The explicit
    constraint (replacing a plain index of the same column) is what lets
    ``knowledge.address_alias.address_id`` be a real foreign key rather than a
    reference the loader merely promises to keep honest.
    """

    __tablename__ = "customer_addresses"
    __table_args__ = (
        UniqueConstraint("address_id"),
        {"schema": SOURCE_SCHEMA},
    )

    customer_id: Mapped[str] = mapped_column(
        ForeignKey(_CUSTOMERS_FK), primary_key=True
    )
    address_id: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column()
    street: Mapped[str | None] = mapped_column(String)
    street_line_2: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    zip: Mapped[str | None] = mapped_column(String)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
