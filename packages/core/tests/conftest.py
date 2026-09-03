"""Shared fixtures for tests that need a live database.

Requires Postgres up, migrated to head, and loaded
(`docker compose up -d`, `alembic upgrade head`, `python -m switchboard_core.load`)
- the same prerequisite `scripts/verify_load.py` already has. Nothing here
skips when the database is unavailable; a connection failure is a real
failure, the same way it is for verify_load.
"""

import pytest

from switchboard_core.db.session import create_db_engine, session_factory


@pytest.fixture(scope="session")
def db_session():
    """A read-only session against the live, loaded database.

    Session-scoped: every test in a run shares one connection. Safe because
    nothing under test here writes - resolve_address only reads.
    """
    engine = create_db_engine()
    factory = session_factory(engine)
    with factory() as session, session.begin():
        yield session
    engine.dispose()


@pytest.fixture
def write_session(db_session):
    """A SAVEPOINT around a test that writes, rolled back on the way out.

    `db_session` is session-scoped and every other test treats it as
    read-only. A write tool's rows would otherwise outlive the test that
    made them and change what a later schedule query returns - the overlay
    is deliberately visible to reads, which is exactly what makes leaking
    one dangerous here.
    """
    nested = db_session.begin_nested()
    try:
        yield db_session
    finally:
        nested.rollback()
