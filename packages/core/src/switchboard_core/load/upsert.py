"""Chunked upsert, which is what makes the loaders idempotent.

Every row is inserted with ``ON CONFLICT DO UPDATE`` on its primary key, so a
second run rewrites the same values and leaves the database identical.

Rows removed from the source between runs are **not** deleted here. The dataset
is immutable by hard rule 1, so that case cannot arise in this repository, and
``scripts/verify_load.py`` would catch it as a count mismatch if it ever did.
"""

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from switchboard_core.db.base import Base

#: Rows per statement. Postgres has a parameter ceiling per statement, and the
#: widest table here has ~25 columns, so a thousand rows stays well inside it.
CHUNK_SIZE = 1000


def upsert(
    session: Session,
    model: type[Base],
    rows: list[dict[str, Any]],
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """Insert or update ``rows``, returning how many were written."""
    if not rows:
        return 0

    table = model.__table__
    key_columns = [column.name for column in table.primary_key.columns]
    value_columns = [
        column.name for column in table.columns if column.name not in key_columns
    ]

    written = 0
    for start in range(0, len(rows), chunk_size):
        batch = rows[start : start + chunk_size]
        statement = insert(table).values(batch)
        if value_columns:
            statement = statement.on_conflict_do_update(
                index_elements=key_columns,
                set_={name: statement.excluded[name] for name in value_columns},
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=key_columns)
        session.execute(statement)
        written += len(batch)

    return written
