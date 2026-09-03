"""Declarative base, schema names and shared column conventions.

Three Postgres schemas, separated on purpose, matching the four-layer split
in ``docs/ARCHITECTURE.md`` (Records live directly in ``source``, so there
are three schemas for four layers):

``source``
    Records. Tables mirroring ``data/*.jsonl`` row for row. Loaded verbatim,
    never computed. No field from the source is dropped, including fields
    that are empty in this export.

``knowledge``
    Entities and Knowledge. Canonical addresses, visit history, warranty
    status, install dates, balances, callback chains - typed SQL, no model in
    the path. Created empty in T1.3 so the boundary exists from the first
    migration rather than appearing later; T2 fills it.

``prose``
    Prose. One row per note, ``vector`` + ``tsvector``, reached only through
    ``search_notes(entity_id, query)`` with a resolved entity id - never an
    unscoped semantic search over the corpus (CLAUDE.md hard rule 3). Created
    empty in T2.5's migration; the same migration fills it, since generating
    embeddings needs a live API call the migration itself cannot make -
    ``switchboard_core.prose.build`` does that separately.

Nothing in ``source`` may depend on ``knowledge`` or ``prose``.
"""

from sqlalchemy import BigInteger, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import UserDefinedType

SOURCE_SCHEMA = "source"
KNOWLEDGE_SCHEMA = "knowledge"
PROSE_SCHEMA = "prose"

#: Money is stored in cents everywhere in the database, exactly as the .jsonl
#: files carry it. Dollars exist only in the presentation layer and in the
#: .csv mirrors, which are not loaded. See docs/DATA.md.
Cents = BigInteger


class Vector(UserDefinedType):
    """A fixed-length float vector, stored via Postgres's ``pgvector``
    extension (installed in T1.2).

    Hand-rolled rather than the ``pgvector`` pip package: the only thing
    needed is serialising a Python ``list[float]`` to pgvector's text input
    format (``"[0.1,0.2,...]"``) and back, which ``UserDefinedType`` does in
    about a dozen lines. The package's numpy-aware conveniences have no other
    use in this codebase, so it would be a dependency for syntax sugar over
    code this short - not approved, since hard rule 6 asks first.

    Every actual query against this column - the RRF search, the bulk
    embedding insert - goes through raw SQL (`switchboard_core.prose`), never
    the ORM. This type exists so the declarative model can name the column
    and Alembic can emit correct DDL for it, not so the ORM manipulates
    vectors directly.
    """

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kwargs: object) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect):
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(repr(float(x)) for x in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value: str | None) -> list[float] | None:
            if value is None:
                return None
            return [float(x) for x in value.strip("[]").split(",")]

        return process


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
