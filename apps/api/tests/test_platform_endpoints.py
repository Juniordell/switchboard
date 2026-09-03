"""The operations platform endpoints, and the live stream.

The stream carries a requirement rather than a shape: a tool call made
during a live call has to reach a browser in under a second. That is
measured end to end by `scripts/measure_event_latency.py` against a running
server. What is asserted here is everything that has to hold for the
measurement to mean anything.

These tests **commit**, on their own connection, because the rows have to be
visible to the API's session and to a `NOTIFY`. The shared `db_session`
fixture is read-only with SAVEPOINTs and cannot be used for that, so each
fixture cleans up what it wrote.

`record_tool_calls()` installs a handler on a module-level logger, which is
global to the process: a test that installs it and walks away makes every
later tool call in the suite write a row. The fixture below removes it.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from switchboard_api.main import app
from switchboard_api.platform import CHANNELS, MAX_LIMIT, _psycopg_url
from switchboard_core.db.session import create_db_engine, database_url, session_factory
from switchboard_core.observability import (
    TOOL_LOGGER,
    ToolCallRecorder,
    record_tool_calls,
)

CALL_ID = "call_platform_test"
RECORDER_CALL_ID = "call_recorder_test"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def committed():
    """A session that really commits, with its own engine."""
    engine = create_db_engine()
    sessions = session_factory(engine)

    def run(statement: str, **params):
        with sessions() as session, session.begin():
            result = session.execute(text(statement), params)
            # DELETE and INSERT return nothing; asking them for rows raises.
            return result.all() if result.returns_rows else []

    yield run
    engine.dispose()


@pytest.fixture
def a_recorded_tool_call(committed):
    committed("DELETE FROM ops.tool_calls WHERE call_id = :c", c=CALL_ID)
    committed("DELETE FROM ops.calls WHERE call_id = :c", c=CALL_ID)
    committed(
        "INSERT INTO ops.tool_calls "
        "(id, call_id, agent, tool, args, duration_ms, result_rows, ok) "
        "VALUES ('tc_platform_test', :c, 'Service', 'get_visit_history', "
        "'{}', 12.5, 3, true)",
        c=CALL_ID,
    )
    committed(
        "INSERT INTO ops.calls (call_id, caller) VALUES (:c, '+15550000000')",
        c=CALL_ID,
    )
    yield
    committed("DELETE FROM ops.tool_calls WHERE call_id = :c", c=CALL_ID)
    committed("DELETE FROM ops.calls WHERE call_id = :c", c=CALL_ID)


@pytest.fixture
def recorder(committed):
    """Install the recorder, and take it back off.

    Without the teardown every tool call the rest of the suite makes lands
    in ops.tool_calls - which is exactly what happened the first time these
    tests ran, and is why the removal is a fixture rather than a habit.
    """
    handler = record_tool_calls()
    yield handler
    logging.getLogger(TOOL_LOGGER).removeHandler(handler)
    committed("DELETE FROM ops.tool_calls WHERE call_id = :c", c=RECORDER_CALL_ID)


class TestTheReadEndpoints:
    def test_all_four_answer(self, client) -> None:
        for path in ("/calls", "/tool_calls", "/jobs", "/review_queue"):
            assert client.get(path).status_code == 200, path

    def test_tool_calls_carries_the_seven_fields(
        self, client, a_recorded_tool_call
    ) -> None:
        """CLAUDE.md hard rule 5, as a row rather than a log line."""
        row = client.get(f"/tool_calls?call_id={CALL_ID}").json()["items"][0]
        for field in (
            "call_id",
            "agent",
            "tool",
            "args",
            "duration_ms",
            "result_rows",
            "ok",
        ):
            assert field in row, field

    def test_a_call_reports_how_many_tools_it_used(
        self, client, a_recorded_tool_call
    ) -> None:
        mine = [
            c for c in client.get("/calls").json()["items"] if c["call_id"] == CALL_ID
        ]
        assert mine and mine[0]["tool_calls"] == 1

    def test_jobs_unions_the_write_overlay(self, client) -> None:
        """A job the agent booked has no job number - the field service
        system assigns those - so the column is null, not invented."""
        items = client.get("/jobs?limit=200").json()["items"]
        assert items
        assert {"agent_booked", "rescheduled", "job_number"} <= set(items[0])

    def test_the_page_size_is_bounded(self, client) -> None:
        assert client.get(f"/tool_calls?limit={MAX_LIMIT + 1}").status_code == 422


class TestTheRecorder:
    def test_it_persists_what_the_decorator_logs(self, recorder, committed) -> None:
        """The T3.1 contract is unchanged; a handler on the same logger
        turns the line into a row."""
        logging.getLogger(TOOL_LOGGER).info(
            json.dumps(
                {
                    "call_id": RECORDER_CALL_ID,
                    "agent": "Service",
                    "tool": "get_schedule",
                    "args": {"role": "owner"},
                    "duration_ms": 4.2,
                    "result_rows": 2,
                    "ok": True,
                }
            )
        )
        rows = committed(
            "SELECT tool, result_rows, ok FROM ops.tool_calls WHERE call_id = :c",
            c=RECORDER_CALL_ID,
        )
        assert len(rows) == 1
        assert rows[0].tool == "get_schedule"
        assert rows[0].ok is True

    def test_partial_timings_land_in_their_own_column(
        self, recorder, committed
    ) -> None:
        """search_notes reports embedding_ms and postgres_ms beside the
        total (T3.1). They stay out of the seven named fields."""
        logging.getLogger(TOOL_LOGGER).info(
            json.dumps(
                {
                    "call_id": RECORDER_CALL_ID,
                    "agent": "Service",
                    "tool": "search_notes",
                    "args": {"entity_id": "job_x", "query": "drain"},
                    "duration_ms": 470.0,
                    "result_rows": 3,
                    "ok": True,
                    "embedding_ms": 463.0,
                    "postgres_ms": 2.3,
                }
            )
        )
        rows = committed(
            "SELECT timings FROM ops.tool_calls "
            "WHERE call_id = :c AND tool = 'search_notes'",
            c=RECORDER_CALL_ID,
        )
        assert rows[0].timings == {"embedding_ms": 463.0, "postgres_ms": 2.3}

    def test_installing_twice_does_not_double_write(self, recorder) -> None:
        record_tool_calls()
        installed = [
            h
            for h in logging.getLogger(TOOL_LOGGER).handlers
            if isinstance(h, ToolCallRecorder)
        ]
        assert len(installed) == 1

    def test_a_non_tool_line_is_ignored(self, recorder) -> None:
        """This logger carries nothing else today, but a stray line must
        not take the handler down."""
        recorder.emit(
            logging.LogRecord(
                TOOL_LOGGER, logging.INFO, __file__, 1, "not json", (), None
            )
        )


class TestTheStream:
    def test_it_listens_on_both_channels(self) -> None:
        """The write audit and the tool call log announce separately; one
        stream reads both so the dashboard needs one connection."""
        assert set(CHANNELS) == {"switchboard_tool_calls", "switchboard_writes"}

    def test_the_listener_url_is_one_psycopg_can_parse(self) -> None:
        """database_url() is SQLAlchemy's dialect form, which psycopg
        rejects outright - found by the stream closing on connect."""
        assert database_url().startswith("postgresql+psycopg://")
        assert _psycopg_url().startswith("postgresql://")
        assert "+psycopg" not in _psycopg_url()
