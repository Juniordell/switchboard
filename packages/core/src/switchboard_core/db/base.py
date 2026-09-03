"""Declarative base, schema names and shared column conventions.

Two Postgres schemas, separated on purpose:

``source``
    Tables mirroring ``data/*.jsonl`` row for row. Loaded verbatim, never
    computed. No field from the source is dropped, including fields that are
    empty in this export.

``knowledge``
    Tables derived at load: visit history, warranty status, canonical
    addresses, balances, callback chains. Created empty here so the boundary
    exists from the first migration rather than appearing later; T2 fills it.

Nothing in ``source`` may depend on ``knowledge``.
"""

from sqlalchemy import BigInteger, MetaData
from sqlalchemy.orm import DeclarativeBase

SOURCE_SCHEMA = "source"
KNOWLEDGE_SCHEMA = "knowledge"

#: Money is stored in cents everywhere in the database, exactly as the .jsonl
#: files carry it. Dollars exist only in the presentation layer and in the
#: .csv mirrors, which are not loaded. See docs/DATA.md.
Cents = BigInteger

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every Switchboard table.

    The naming convention is set here so Alembic emits stable constraint names
    and later migrations can drop a constraint by name instead of by guess.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
