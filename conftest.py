"""Shared fixtures for tests that need a live database.

At the repository root so every testpath sees them - `packages/core/tests`,
and `evals`, whose number-provenance case reads the same loaded database.

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


@pytest.fixture(scope="session", autouse=True)
def tool_call_log(tmp_path_factory):
    """Capture every tool call this run produced, for Layer 4.

    `docs/HARNESS.md`: Layer 4 measures **the tool call log produced by the
    eval run that is executing**, not a log from somewhere else. There is no
    ambient corpus of production calls in CI, and asserting against a
    borrowed one produces a number that means nothing. So the suite records
    its own calls and `evals/layer4.py` reads exactly those.
    """
    import contextlib
    import json
    import logging
    import pathlib

    records: list[dict] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            # A non-JSON line on this logger is not a tool call.
            with contextlib.suppress(ValueError):
                records.append(json.loads(record.getMessage()))

    logger = logging.getLogger("switchboard_core.tools")
    handler = Collector()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        destination = (
            pathlib.Path(__file__).parent / "evals" / "last_run_tool_calls.jsonl"
        )
        destination.write_text("".join(json.dumps(r) + "\n" for r in records))
