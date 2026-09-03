"""`search_notes` as a tool: mandatory scope, the error bridge, and the two
timings reported apart.

The only thing stubbed here is the paid network boundary - `embed_texts`.
Postgres is real, the notes are real, and the RRF ranking runs for real, so
`postgres_ms` is a measurement rather than a fixture. Stubbing it also keeps
the suite runnable without `OPENAI_API_KEY`, which is how every other test
in this repo already runs.
"""

import json
import logging
import sys

import pytest

from switchboard_core.prose.embeddings import EmbeddingsError
from switchboard_core.tools.contract import ToolError
from switchboard_core.tools.search_notes import (
    SearchNotesOutput,
    SearchNotesRequest,
    search_notes,
)

#: A real job with 17 notes.
JOB_ID = "job_28e341b2495a4e8cbf6d677eddcc00b5"

#: `prose/__init__.py` re-exports a function named `search_notes`, which
#: shadows the submodule of the same name on the package, so the dotted
#: string form of monkeypatch resolves to the function rather than the
#: module. `embed_texts` is bound into this module at import time, so it is
#: the binding that has to be replaced.
_PROSE_SEARCH = sys.modules["switchboard_core.prose.search_notes"]


@pytest.fixture
def stub_embeddings(monkeypatch):
    """Replace only the OpenAI call, at the module the prose layer calls it
    from. Any 1536-dimension vector ranks; the ordering it produces is not
    what this file asserts.
    """

    def _fake(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1535 + [1.0] for _ in texts]

    monkeypatch.setattr(_PROSE_SEARCH, "embed_texts", _fake)


class TestScopeIsMandatory:
    """CLAUDE.md hard rule 3, enforced at the request model and again at the
    tool boundary. None of these reach the embeddings API."""

    def test_entity_id_has_no_default(self) -> None:
        field = SearchNotesRequest.model_fields["entity_id"]
        assert field.is_required()

    def test_entity_id_is_not_optional(self) -> None:
        assert SearchNotesRequest.model_fields["entity_id"].annotation is str

    def test_an_empty_entity_id_returns_a_typed_error(self, db_session) -> None:
        out = search_notes(
            SearchNotesRequest(entity_id="", query="drain"),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, ToolError)
        assert out.error == "InvalidEntityIdError"
        assert out.tool == "search_notes"

    def test_a_malformed_entity_id_returns_a_typed_error(self, db_session) -> None:
        out = search_notes(
            SearchNotesRequest(entity_id="cus_123", query="drain"),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, ToolError)
        assert out.error == "InvalidEntityIdError"
        assert "canonical_id" in out.message

    def test_the_bridged_error_is_logged_as_a_failed_call(
        self, db_session, caplog
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="switchboard_core.tools"):
            search_notes(
                SearchNotesRequest(entity_id="cus_123", query="drain"),
                call_id="call_5",
                session=db_session,
            )
        record = json.loads(caplog.records[0].message)
        assert record["ok"] is False
        assert record["result_rows"] == 0
        assert record["tool"] == "search_notes"


class TestResults:
    def test_returns_notes_and_counts_them_as_rows(
        self, db_session, stub_embeddings
    ) -> None:
        out = search_notes(
            SearchNotesRequest(entity_id=JOB_ID, query="drain line"),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, SearchNotesOutput)
        assert out.notes
        assert out.result_rows() == len(out.notes)

    def test_every_date_is_the_job_s_service_date(
        self, db_session, stub_embeddings
    ) -> None:
        """Notes carry no timestamp; the field is named for what it
        actually is, and there is no other date to mistake it for."""
        out = search_notes(
            SearchNotesRequest(entity_id=JOB_ID, query="drain line"),
            call_id="call_1",
            session=db_session,
        )
        assert all(n.job_service_date for n in out.notes)
        assert not any(hasattr(n, "note_date") for n in out.notes)

    def test_an_address_with_no_jobs_searches_nothing_and_costs_nothing(
        self, db_session
    ) -> None:
        """No embeddings stub needed: with no scope to search, the paid leg
        never runs, and both timings are honestly zero."""
        out = search_notes(
            SearchNotesRequest(entity_id="cadr_does_not_exist", query="drain"),
            call_id="call_1",
            session=db_session,
        )
        assert out.notes == []
        assert out.embedding_ms == 0.0
        assert out.postgres_ms == 0.0


class TestTimingsAreReportedApart:
    def test_both_legs_reach_the_log_beside_the_total(
        self, db_session, stub_embeddings, caplog
    ) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            search_notes(
                SearchNotesRequest(entity_id=JOB_ID, query="drain line"),
                call_id="call_6",
                session=db_session,
            )
        record = json.loads(caplog.records[0].message)
        assert "embedding_ms" in record
        assert "postgres_ms" in record
        assert "duration_ms" in record
        assert record["postgres_ms"] > 0
        # The total covers both legs plus the wrapping, so it can never be
        # smaller than the part of it Postgres accounts for.
        assert record["duration_ms"] >= record["postgres_ms"]

    def test_an_unreachable_embeddings_api_is_a_typed_error(
        self, db_session, monkeypatch
    ) -> None:
        """Not a defect in this call path and not something a retry here
        fixes: on a live call the agent must be able to say so and offer a
        human, which needs a result rather than a traceback."""

        def _down(texts: list[str]) -> list[list[float]]:
            raise EmbeddingsError("OPENAI_API_KEY is not set")

        monkeypatch.setattr(_PROSE_SEARCH, "embed_texts", _down)

        out = search_notes(
            SearchNotesRequest(entity_id=JOB_ID, query="drain line"),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, ToolError)
        assert out.error == "RetrievalUnavailableError"
