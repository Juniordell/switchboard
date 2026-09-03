"""The post-call pipeline: queue, Extractor, Reviewer.

The model is stubbed. These assert the plumbing and the judgement rules -
what gets queued, what reaches a human, what does not - and the plumbing is
where the bugs were. A live run against a real conversation is a separate,
paid thing and is not what every commit should do.

Rows are committed on a dedicated engine, then removed. The shared
`db_session` is read-only with SAVEPOINTs and cannot see another
connection's uncommitted work, which is what the worker needs.
"""

import json

import pytest
from sqlalchemy import text

from switchboard_api.async_agents import extractor, reviewer
from switchboard_api.async_agents.queue import MAX_ATTEMPTS, claim, enqueue, finish
from switchboard_api.async_agents.reviewer import REVIEW_TAG
from switchboard_core.db.session import create_db_engine, session_factory

CALL = "call_async_test"


@pytest.fixture
def sessions():
    engine = create_db_engine()
    yield session_factory(engine)
    engine.dispose()


@pytest.fixture
def a_call(sessions):
    def wipe(session):
        for table in (
            "ops.review_queue",
            "ops.extractions",
            "ops.async_jobs",
            "ops.tool_calls",
            "ops.transcript_turns",
            "ops.calls",
        ):
            session.execute(
                text(f"DELETE FROM {table} WHERE call_id = :c"), {"c": CALL}
            )

    with sessions() as session, session.begin():
        wipe(session)
        session.execute(
            text("INSERT INTO ops.calls (call_id, caller) VALUES (:c, '+15550001111')"),
            {"c": CALL},
        )
        for seq, (role, body) in enumerate(
            [
                ("user", "am I under warranty on the condenser"),
                ("assistant", "I'll have someone check and call you back."),
            ]
        ):
            session.execute(
                text(
                    "INSERT INTO ops.transcript_turns (id, call_id, seq, role, text) "
                    "VALUES (:i, :c, :s, :r, :t)"
                ),
                {"i": f"trn_{seq}_{CALL}", "c": CALL, "s": seq, "r": role, "t": body},
            )
    yield
    with sessions() as session, session.begin():
        wipe(session)


class TestTheQueue:
    def test_enqueue_then_claim(self, sessions, a_call) -> None:
        with sessions() as session, session.begin():
            job_id = enqueue(session, CALL)
        with sessions() as session, session.begin():
            claimed = claim(session)
        assert claimed and claimed["id"] == job_id
        assert claimed["call_id"] == CALL

    def test_raw_sql_insert_does_not_violate_not_null(self, sessions, a_call) -> None:
        """`attempts` and `status` are server defaults, not Python ones.

        The first version used `default=`, which the ORM applies and raw SQL
        skips - and both the queue helper and the agent's shutdown insert
        with raw SQL, so every real call would have failed to enqueue.
        """
        with sessions() as session, session.begin():
            session.execute(
                text(
                    "INSERT INTO ops.async_jobs (id, call_id, kind) "
                    "VALUES ('job_raw_test', :c, 'extract')"
                ),
                {"c": CALL},
            )
            row = session.execute(
                text(
                    "SELECT status, attempts FROM ops.async_jobs "
                    "WHERE id = 'job_raw_test'"
                )
            ).one()
        assert row.status == "queued"
        assert row.attempts == 0

    def test_enqueuing_twice_queues_once(self, sessions, a_call) -> None:
        """A session that ends twice must not extract twice."""
        with sessions() as session, session.begin():
            first = enqueue(session, CALL)
            second = enqueue(session, CALL)
        assert first == second

    def test_a_job_that_keeps_failing_stops_being_claimed(
        self, sessions, a_call
    ) -> None:
        with sessions() as session, session.begin():
            enqueue(session, CALL)
        for _ in range(MAX_ATTEMPTS):
            with sessions() as session, session.begin():
                job = claim(session)
                assert job is not None
                finish(session, job["id"], error="boom")
                session.execute(
                    text("UPDATE ops.async_jobs SET status='queued' WHERE id=:i"),
                    {"i": job["id"]},
                )
        with sessions() as session, session.begin():
            assert claim(session) is None


class TestTheExtractor:
    def test_it_refuses_a_call_with_nothing_in_it(self, sessions) -> None:
        with (
            sessions() as session,
            session.begin(),
            pytest.raises(ValueError, match="no transcript"),
        ):
            extractor.extract(session, "call_that_never_happened")

    def test_it_stores_what_the_model_returned_whole(
        self, sessions, a_call, monkeypatch
    ) -> None:
        answer = {
            "asked": ["warranty on the condenser"],
            "promised": ["someone will call you back"],
            "changed": [],
            "resolved": {"canonical_id": None, "customer_id": None, "job_ids": []},
            "unresolved": ["warranty status"],
            "notes": "no answer given",
        }
        monkeypatch.setattr(extractor, "ask_for_json", lambda *a, **k: answer)

        with sessions() as session, session.begin():
            facts = extractor.extract(session, CALL)
            stored = session.execute(
                text("SELECT facts FROM ops.extractions WHERE call_id = :c"),
                {"c": CALL},
            ).scalar_one()
        assert facts == answer
        assert stored == answer

    def test_it_shows_the_model_the_tool_calls_too(
        self, sessions, a_call, monkeypatch
    ) -> None:
        """A promise in words is half the record; whether a tool wrote
        anything is the other half, and the gap is the point."""
        seen: dict[str, str] = {}

        def spy(system, user, **kwargs):
            seen["user"] = user
            return {"asked": [], "promised": [], "changed": []}

        monkeypatch.setattr(extractor, "ask_for_json", spy)
        with sessions() as session, session.begin():
            session.execute(
                text(
                    "INSERT INTO ops.tool_calls (id, call_id, agent, tool, args, "
                    "duration_ms, result_rows, ok) VALUES ('tc_async_test', :c, "
                    "'Service', 'get_warranty_status', '{}', 1.0, 1, true)"
                ),
                {"c": CALL},
            )
            extractor.extract(session, CALL)
        payload = json.loads(seen["user"])
        assert payload["tool_calls"][0]["tool"] == "get_warranty_status"
        assert payload["transcript"]


class TestTheReviewer:
    def _verdict(self, monkeypatch, confidence: float, headline: str = "check this"):
        monkeypatch.setattr(
            reviewer,
            "ask_for_json",
            lambda *a, **k: {
                "confidence": confidence,
                "problems": [],
                "missed": [],
                "headline": headline,
            },
        )

    def test_a_confident_clean_call_is_not_queued(
        self, sessions, a_call, monkeypatch
    ) -> None:
        self._verdict(monkeypatch, 0.95)
        facts = {"promised": ["a callback"], "changed": ["a callback"]}
        with sessions() as session, session.begin():
            verdict = reviewer.review(session, CALL, facts)
            queued = session.execute(
                text("SELECT count(*) FROM ops.review_queue WHERE call_id = :c"),
                {"c": CALL},
            ).scalar_one()
        assert verdict["queued"] is False
        assert queued == 0

    def test_low_confidence_reaches_a_human(
        self, sessions, a_call, monkeypatch
    ) -> None:
        self._verdict(monkeypatch, 0.4)
        with sessions() as session, session.begin():
            verdict = reviewer.review(session, CALL, {"promised": [], "changed": []})
            row = session.execute(
                text("SELECT kind, status FROM ops.review_queue WHERE call_id = :c"),
                {"c": CALL},
            ).one()
        assert verdict["queued"] is True
        assert row.kind == REVIEW_TAG
        assert row.status == "open"

    def test_an_unkept_promise_is_queued_however_confident_the_model_is(
        self, sessions, a_call, monkeypatch
    ) -> None:
        """The model's confidence about its own summary says nothing about
        whether the office owes somebody a callback."""
        self._verdict(monkeypatch, 0.99)
        facts = {"promised": ["someone will call you back"], "changed": []}
        with sessions() as session, session.begin():
            verdict = reviewer.review(session, CALL, facts)
        assert verdict["queued"] is True
        assert verdict["open_promises"] == ["someone will call you back"]
        assert any("promise" in r for r in verdict["reasons"])

    def test_the_tag_is_the_one_the_office_already_uses(self, db_session) -> None:
        """137 jobs in the loaded data carry it, 135 of them completed - so
        it already means "finished, somebody look", which is what this
        writes."""
        tagged = db_session.execute(
            text("SELECT count(DISTINCT job_id) FROM source.job_tags WHERE tag = :t"),
            {"t": REVIEW_TAG},
        ).scalar_one()
        assert tagged == 137
