"""``data/invoices.jsonl`` — 1,700 invoices, 4,390 items, 368 discounts,
1,367 payments, 0 taxes.

``data/README.md`` describes ``taxes``, ``discounts`` and ``payments`` as
"amounts only". That is true of discounts and wrong about payments, which carry
eight fields including a payment method and a surcharge. The file wins; the
divergence is recorded in docs/DATA.md.
"""

import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import SOURCE_SCHEMA, Base, Cents

#: Values seen in this export. Not a CHECK constraint, for the reason given in
#: :mod:`switchboard_core.db.source.jobs`; the loader warns instead.
INVOICE_STATUSES = frozenset({"paid", "open", "voided", "canceled", "pending_payment"})
INVOICE_ITEM_TYPES = frozenset({"labor", "material"})

_INVOICES_FK = f"{SOURCE_SCHEMA}.invoices.id"


class Invoice(Base):
    """One invoice.

    ``job_id`` is the only join key back to a job. 456 jobs have no invoice and
    135 have more than one, up to 4, so this relationship is neither total nor
    one to one.
    """

    __tablename__ = "invoices"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SOURCE_SCHEMA}.jobs.id"), index=True
    )

    #: The invoice's own number, on a different sequence from a job's
    #: job_number. Cite it only as an invoice number; see docs/AGENTS.md.
    invoice_number: Mapped[str] = mapped_column(String, unique=True, index=True)

    status: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[int] = mapped_column(Cents)
    subtotal: Mapped[int] = mapped_column(Cents)
    due_amount: Mapped[int] = mapped_column(Cents)

    paid_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    service_date: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    invoice_date: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class InvoiceItem(Base):
    """``invoices[].items``. Line names carry the company's price book.

    Warranty parts are matched with ``name ILIKE '%warrant%'`` - 64 items - not
    with the exact ``WARRANTY Parts / Service - WARRANTY - `` prefix, which
    matches 61 and silently drops 3 covered parts. See docs/DATA.md.
    """

    __tablename__ = "invoice_items"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey(_INVOICES_FK), index=True)
    position: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, index=True)
    unit_price: Mapped[int] = mapped_column(Cents)

    #: Scaled quantity, not money: 100 means one.
    qty_in_hundredths: Mapped[int] = mapped_column()

    amount: Mapped[int] = mapped_column(Cents)


class InvoiceDiscount(Base):
    """``invoices[].discounts``. Amount only, as data/README.md says."""

    __tablename__ = "invoice_discounts"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    # The primary key (invoice_id, position) already indexes invoice_id.
    invoice_id: Mapped[str] = mapped_column(ForeignKey(_INVOICES_FK), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(Cents)


class InvoiceTax(Base):
    """``invoices[].taxes``.

    Empty across all 1,700 invoices in this export, so the column shape is
    inferred from ``discounts``, the only other amount-only array. The table
    exists because the field exists: the source layer drops nothing, and a
    loader that silently skipped an always-empty array would keep skipping it
    when a later export filled it.
    """

    __tablename__ = "invoice_taxes"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    # The primary key (invoice_id, position) already indexes invoice_id.
    invoice_id: Mapped[str] = mapped_column(ForeignKey(_INVOICES_FK), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(Cents)


class InvoicePayment(Base):
    """``invoices[].payments``. Eight fields, not "amounts only"."""

    __tablename__ = "invoice_payments"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey(_INVOICES_FK), index=True)
    position: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String, index=True)
    payment_method: Mapped[str] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Cents)
    note: Mapped[str | None] = mapped_column(String)
    paid_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[str | None] = mapped_column(String)
    surcharge_fee_amount: Mapped[int] = mapped_column(Cents)
