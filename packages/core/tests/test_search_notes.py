"""`search_notes`/`rank_candidates` against the live database.

The RRF query is verified with real embedding *math*, not a mock: synthetic
unit vectors inserted directly (unrelated dimensions are orthogonal, so
cosine distance between any two is exactly 1.0 except the one deliberately
aligned with the query, at distance 0), inside a SAVEPOINT rolled back at the
end of each test - the shared `db_session` fixture is otherwise read-only
across this whole test suite, and nothing here may leak a synthetic
embedding into a later test.
"""

import contextlib

import pytest
from sqlalchemy import text

from switchboard_core.prose import (
    RRF_K,
    NoteSearchResult,
    rank_candidates,
    search_notes,
)

#: A job with 17 real notes - enough to exercise ranking and ties.
JOB_ID = "job_28e341b2495a4e8cbf6d677eddcc00b5"


def _unit_vector(hot_index: int, dim: int = 1536) -> list[float]:
    """An axis-aligned unit vector. Any two distinct axes are orthogonal, so
    cosine distance between them is exactly 1.0 - a clean, exact baseline to
    assert against, not an approximation.
    """
    vector = [0.0] * dim
    vector[hot_index] = 1.0
    return vector


@contextlib.contextmanager
def synthetic_embeddings(db_session, note_ids: list[str]):
    """Assign each note_id a distinct orthogonal unit vector, in a SAVEPOINT
    rolled back on exit regardless of the test's outcome.
    """
    nested = db_session.begin_nested()
    try:
        for i, note_id in enumerate(note_ids):
            literal = "[" + ",".join(repr(x) for x in _unit_vector(i)) + "]"
            db_session.execute(
                text(
                    "UPDATE prose.note_chunks SET embedding = (:e)::vector "
                    "WHERE note_id = :n"
                ),
                {"e": literal, "n": note_id},
            )
        yield
    finally:
        nested.rollback()


def _note_ids_for_job(db_session, job_id: str) -> list[str]:
    return list(
        db_session.execute(
            text(
                "SELECT note_id FROM prose.note_chunks WHERE job_id = :j "
                "ORDER BY note_id"
            ),
            {"j": job_id},
        ).scalars()
    )


class TestRRFMathIsExact:
    """Isolates each leg of the fusion in turn and checks the arithmetic
    exactly, not just the resulting order - `1/(60+rank)` is a documented
    constant (`docs/ARCHITECTURE.md`), not an approximation to eyeball.
    """

    def test_dense_leg_alone_matches_the_documented_formula(self, db_session) -> None:
        note_ids = _note_ids_for_job(db_session, JOB_ID)
        target = note_ids[0]
        with synthetic_embeddings(db_session, note_ids):
            query_vector = _unit_vector(0)  # identical to target's vector
            results = rank_candidates(
                db_session,
                [JOB_ID],
                "zzqxjklw nonsense term nothing lexical matches this",
                query_vector,
                limit=len(note_ids),
            )
            assert results[0].note_id == target
            assert results[0].score == pytest.approx(1.0 / (RRF_K + 1))
            # Every other note is tied at cosine distance 1.0 - all present,
            # none scoring above the dense-leg-only leader.
            assert len(results) == len(note_ids)
            assert all(r.score <= results[0].score for r in results)

    def test_no_embedding_and_no_lexical_match_returns_nothing(
        self, db_session
    ) -> None:
        """embedding IS NULL (true before `embed_pending` ever runs on a note
        - every note in the live database is embedded now, so this pins that
        state explicitly inside a SAVEPOINT rather than relying on it holding
        globally) and no lexical match: the fused score is 0 + 0, filtered
        out by `WHERE score > 0` - not a zero-score row, no row at all.
        """
        note_ids = _note_ids_for_job(db_session, JOB_ID)
        nested = db_session.begin_nested()
        try:
            db_session.execute(
                text(
                    "UPDATE prose.note_chunks SET embedding = NULL "
                    "WHERE note_id = ANY(:ids)"
                ),
                {"ids": note_ids},
            )
            results = rank_candidates(
                db_session,
                [JOB_ID],
                "zzqxjklw nonsense term nothing lexical matches this",
                _unit_vector(0),
                limit=10,
            )
            assert results == []
        finally:
            nested.rollback()


class TestEntityScopeIsMandatory:
    """CLAUDE.md hard rule 3: search_notes requires a resolved entity id as
    a positional argument. Checked as an actual TypeError from calling it
    wrong, not just read off the signature.
    """

    def test_calling_without_entity_id_raises_type_error(self, db_session) -> None:
        with pytest.raises(TypeError):
            search_notes(db_session, query="drain")  # type: ignore[call-arg]

    def test_entity_id_has_no_default_in_the_signature(self) -> None:
        import inspect

        params = inspect.signature(search_notes).parameters
        assert params["entity_id"].default is inspect.Parameter.empty

    def test_entity_id_is_positional(self) -> None:
        import inspect

        params = inspect.signature(search_notes).parameters
        assert params["entity_id"].kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )

    def test_an_empty_entity_id_raises_rather_than_searching_everything(
        self, db_session
    ) -> None:
        with pytest.raises(ValueError, match="requires a resolved entity_id"):
            search_notes(db_session, "", "drain")

    def test_an_unrecognised_entity_id_prefix_raises(self, db_session) -> None:
        with pytest.raises(ValueError, match=r"canonical_id.*or a job_id"):
            search_notes(db_session, "cus_not_a_valid_scope", "drain")


class TestEntityScopeAcceptsBothKinds:
    def test_a_job_id_scopes_to_that_job_alone(self, db_session) -> None:
        note_ids = _note_ids_for_job(db_session, JOB_ID)
        with synthetic_embeddings(db_session, note_ids):
            results = rank_candidates(
                db_session, [JOB_ID], "dehum", _unit_vector(0), limit=20
            )
            assert all(r.job_id == JOB_ID for r in results)

    def test_a_canonical_id_scopes_to_every_job_at_the_address(
        self, db_session
    ) -> None:
        """cadr_7781ff2789ea56ff902b44968cfa1957 (103 Grouper Landing Rd, the
        T2.3a fixture) has two jobs. A note on either must come back when
        searched by the address's canonical_id, not just by its own job_id -
        exercised through `_resolve_entity_job_ids` directly, the same
        function `search_notes` calls before ever touching the ranking SQL.
        """
        from switchboard_core.knowledge import jobs_at_canonical_address
        from switchboard_core.prose.search_notes import _resolve_entity_job_ids

        canonical_id = "cadr_7781ff2789ea56ff902b44968cfa1957"
        expected_job_ids = jobs_at_canonical_address(db_session, canonical_id)
        assert len(expected_job_ids) == 2

        resolved = _resolve_entity_job_ids(db_session, canonical_id)
        assert sorted(resolved) == sorted(expected_job_ids)


class TestSnippet:
    def test_short_content_is_returned_verbatim(self) -> None:
        from switchboard_core.prose.search_notes import _snippet

        assert _snippet("short note") == "short note"

    def test_long_content_is_cut_not_summarised(self) -> None:
        from switchboard_core.prose.search_notes import SNIPPET_MAX_CHARS, _snippet

        long_content = "x" * 10_076  # the real max note length
        result = _snippet(long_content)
        assert len(result) <= SNIPPET_MAX_CHARS + 1  # +1 for the ellipsis mark
        assert result.startswith("x" * 100)
        assert result.endswith("…")


class TestResultShape:
    def test_result_type_has_no_free_text_field_beyond_the_snippet(self) -> None:
        assert set(NoteSearchResult.model_fields) == {
            "note_id",
            "job_id",
            "job_service_date",
            "snippet",
            "score",
        }
