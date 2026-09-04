"""Every tool over HTTP.

Real requests through `TestClient` against the loaded database - the same
path `scripts/smoke_tools.sh` drives with curl, asserted here so a break
shows up in `pytest` before it shows up in a shell script.
"""

import pytest
from fastapi.testclient import TestClient

from switchboard_api.main import app
from switchboard_core.tools import READ_TOOLS, WRITE_TOOLS

AS_OF = "2026-09-03T09:00:00+00:00"
CANONICAL_ID = "cadr_2fa76af76a2a53d2909332ef8c0dba59"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _post(client, name, body, *, call_id="call_http_test", as_of=AS_OF):
    headers = {"X-Call-Id": call_id, "X-As-Of": as_of}
    return client.post(f"/api/tools/{name}", json=body, headers=headers)


class TestTheBindingSurface:
    def test_every_tool_is_listed(self, client) -> None:
        listed = {t["name"] for t in client.get("/api/tools").json()}
        assert listed == set(READ_TOOLS) | set(WRITE_TOOLS)

    def test_each_carries_a_json_schema_an_agent_can_bind(self, client) -> None:
        for tool in client.get("/api/tools").json():
            assert tool["request_schema"]["type"] == "object"
            assert "properties" in tool["request_schema"]

    def test_write_tools_are_flagged_and_are_all_dispatch(self, client) -> None:
        writes = [t for t in client.get("/api/tools").json() if t["writes"]]
        assert {t["name"] for t in writes} == set(WRITE_TOOLS)
        assert {t["agent"] for t in writes} == {"Dispatch"}


class TestCallingATool:
    def test_a_read_tool_answers_from_the_loaded_database(self, client) -> None:
        response = _post(
            client,
            "resolve_address",
            {"spoken_address": "eighty nine harbor light shores"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["tool"] == "resolve_address"
        assert body["call_id"] == "call_http_test"
        assert body["result"]["address"]["candidates"]

    def test_the_body_is_the_tool_s_own_schema_not_an_envelope(self, client) -> None:
        """What an agent binds and what the API accepts are one object."""
        response = _post(
            client, "get_customer_balance", {"customer_id": "cus_does_not_exist"}
        )
        assert response.status_code == 200
        assert response.json()["result"]["balance"]["job_count"] == 0

    def test_a_tool_needing_no_session_still_works(self, client) -> None:
        response = _post(
            client,
            "identify_caller_role",
            {"utterance": "my house is not cooling and I live here"},
        )
        assert response.json()["result"]["role"] == "homeowner"

    def test_as_of_makes_a_clock_dependent_tool_deterministic(self, client) -> None:
        first = _post(
            client,
            "get_schedule",
            {
                "start": AS_OF,
                "end": "2026-09-17T09:00:00+00:00",
                "role": "owner",
            },
        ).json()
        second = _post(
            client,
            "get_schedule",
            {
                "start": AS_OF,
                "end": "2026-09-17T09:00:00+00:00",
                "role": "owner",
            },
        ).json()
        assert first["result"] == second["result"]


class TestFailureShapes:
    def test_an_unknown_tool_is_404(self, client) -> None:
        response = _post(client, "no_such_tool", {})
        assert response.status_code == 404

    def test_a_missing_call_id_is_rejected(self, client) -> None:
        """CLAUDE.md hard rule 5: a call with nothing to attribute it to is
        not a valid call."""
        response = client.post(
            "/api/tools/resolve_address", json={"spoken_address": "anything"}
        )
        assert response.status_code == 422

    def test_a_malformed_body_is_422_not_a_tool_error(self, client) -> None:
        """A body that does not match the schema is a defect, and the
        contract says defects do not come back as polite results."""
        response = _post(client, "resolve_address", {"wrong_field": 1})
        assert response.status_code == 422

    def test_a_domain_error_is_200_with_ok_false(self, client) -> None:
        """A ToolError is a normal outcome; the caller branches on the
        payload over HTTP exactly as it does in Python."""
        response = _post(
            client, "search_notes", {"entity_id": "cus_123", "query": "drain"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["error"]["error"] == "InvalidEntityIdError"


class TestWritesOverHttp:
    def test_a_booking_round_trips_and_is_idempotent(self, client) -> None:
        call_id = "call_http_write_test"
        body = {
            "customer_id": "cus_http_test",
            "scheduled_start": "2026-11-05T14:00:00+00:00",
            "description": "http smoke booking",
            "display_address": "1 HTTP Test St",
            "spoken_confirmation": "yes, the fifth at two",
        }
        try:
            first = _post(client, "book_job", body, call_id=call_id).json()
            second = _post(client, "book_job", body, call_id=call_id).json()

            assert first["ok"] is True
            assert first["result"]["replayed"] is False
            assert second["result"]["replayed"] is True
            assert second["result"]["job_id"] == first["result"]["job_id"]
        finally:
            _cleanup(call_id)

    def test_an_unconfirmed_booking_cannot_be_made(self, client) -> None:
        response = _post(
            client,
            "book_job",
            {
                "customer_id": "cus_http_test",
                "scheduled_start": "2026-11-05T14:00:00+00:00",
                "description": "x",
                "display_address": "1 HTTP Test St",
                "spoken_confirmation": "",
            },
        )
        assert response.status_code == 422


def _cleanup(call_id: str) -> None:
    """Writes over HTTP commit for real, so the test removes its own rows."""
    from sqlalchemy import text

    from switchboard_core.db.session import create_db_engine, session_factory

    engine = create_db_engine()
    with session_factory(engine)() as session, session.begin():
        session.execute(
            text("DELETE FROM ops.booked_jobs WHERE call_id = :c"), {"c": call_id}
        )
        session.execute(
            text("DELETE FROM ops.write_audit WHERE call_id = :c"), {"c": call_id}
        )
    engine.dispose()
