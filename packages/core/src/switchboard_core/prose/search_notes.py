"""`search_notes(entity_id, query)`: hybrid retrieval over notes, scoped to a
resolved entity. CLAUDE.md hard rule 3: an unscoped semantic search over the
corpus is a bug, not an option - `entity_id` has **no default and is not
`Optional`**, so it cannot be omitted and cannot be passed as `None` without
Python's own type checking already objecting, and this module raises before
querying anything if it somehow gets an empty string anyway.

`entity_id` is either a `canonical_id` (`cadr_...` - every job at that
address) or a `job_id` (`job_...` - that job alone), matching
`docs/ARCHITECTURE.md`'s "scoped to canonical address and job": both entity
kinds are real scopes this system already resolves callers to, so both are
accepted here rather than picking one arbitrarily.

**The hybrid ranking is one SQL statement.** Both ranked lists - lexical via
`ts_rank_cd` over the generated `tsvector`, dense via cosine distance on the
embedding - are computed from the *same* entity-filtered CTE, ranked
independently, then fused by reciprocal rank at `1/(60 + rank)`
(`docs/ARCHITECTURE.md`). No score normalisation, nothing to get wrong there.
"""

import datetime
import time

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.knowledge.job_address import jobs_at_canonical_address
from switchboard_core.prose.embeddings import embed_texts

#: The constant in ARCHITECTURE.md's stated fusion formula.
RRF_K = 60

#: Notes rarely need it (median 120 characters), but the max is 10,076 - a
#: caller reading one aloud verbatim past this point would stop sounding like
#: a citation and start sounding like the whole note. Cut, not summarised:
#: this module generates no text, per CLAUDE.md hard rule 2.
SNIPPET_MAX_CHARS = 500

DEFAULT_LIMIT = 10


class NoteSearchResult(BaseModel):
    note_id: str
    job_id: str
    job_service_date: datetime.datetime
    snippet: str
    score: float


_HYBRID_SEARCH_QUERY = text(
    """
    WITH candidates AS (
        SELECT
            nc.note_id,
            nc.content,
            nc.content_tsv,
            nc.embedding,
            nc.job_id,
            COALESCE(j.completed_at, j.scheduled_start, j.created_at)
                AS job_service_date
        FROM prose.note_chunks nc
        JOIN source.jobs j ON j.id = nc.job_id
        WHERE nc.job_id = ANY(:job_ids)
    ),
    lexical_ranked AS (
        SELECT
            note_id,
            row_number() OVER (
                ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('english', :query))
                    DESC
            ) AS rank
        FROM candidates
        WHERE content_tsv @@ plainto_tsquery('english', :query)
    ),
    dense_ranked AS (
        SELECT
            note_id,
            row_number() OVER (
                ORDER BY embedding <=> (:query_embedding)::vector
            ) AS rank
        FROM candidates
        WHERE embedding IS NOT NULL
    ),
    fused AS (
        SELECT
            c.note_id,
            c.content,
            c.job_id,
            c.job_service_date,
            COALESCE(1.0 / (:rrf_k + l.rank), 0)
                + COALESCE(1.0 / (:rrf_k + d.rank), 0) AS score
        FROM candidates c
        LEFT JOIN lexical_ranked l ON l.note_id = c.note_id
        LEFT JOIN dense_ranked d ON d.note_id = c.note_id
    )
    SELECT note_id, content, job_id, job_service_date, score
    FROM fused
    WHERE score > 0
    ORDER BY score DESC, note_id
    LIMIT :limit
    """
)


def _resolve_entity_job_ids(session: Session, entity_id: str) -> list[str]:
    if not entity_id:
        raise ValueError("search_notes requires a resolved entity_id, got empty")
    if entity_id.startswith("cadr_"):
        return jobs_at_canonical_address(session, entity_id)
    if entity_id.startswith("job_"):
        return [entity_id]
    raise ValueError(
        f"entity_id must be a canonical_id (cadr_...) or a job_id (job_...), "
        f"got {entity_id!r}"
    )


def _snippet(content: str) -> str:
    if len(content) <= SNIPPET_MAX_CHARS:
        return content
    return content[:SNIPPET_MAX_CHARS].rstrip() + "…"


class SearchTimings(BaseModel):
    """The two legs of a search, measured apart. T2.5 put 463 ms of OpenAI
    against 2-5 ms of Postgres at p95, so one fused number says nothing
    about which half moved; `docs/HARNESS.md` Layer 4 asserts them
    separately.
    """

    embedding_ms: float
    postgres_ms: float


def search_notes_timed(
    session: Session,
    entity_id: str,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[NoteSearchResult], SearchTimings]:
    """`search_notes`, with the embedding call and the Postgres query timed
    apart. The tool layer reports these; the plain function below discards
    them. One implementation either way - the orchestration lives here, not
    duplicated in `switchboard_core.tools`.
    """
    job_ids = _resolve_entity_job_ids(session, entity_id)
    if not job_ids:
        # Neither leg ran: no scope to search, so no cost to report.
        return [], SearchTimings(embedding_ms=0.0, postgres_ms=0.0)

    t0 = time.perf_counter()
    query_vector = embed_texts([query])[0]
    t1 = time.perf_counter()
    results = rank_candidates(session, job_ids, query, query_vector, limit=limit)
    t2 = time.perf_counter()

    return results, SearchTimings(
        embedding_ms=round((t1 - t0) * 1000, 3),
        postgres_ms=round((t2 - t1) * 1000, 3),
    )


def search_notes(
    session: Session,
    entity_id: str,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[NoteSearchResult]:
    """Hybrid search over notes at `entity_id`. `entity_id` is required and
    positional - see the module docstring.
    """
    results, _timings = search_notes_timed(session, entity_id, query, limit=limit)
    return results


def rank_candidates(
    session: Session,
    job_ids: list[str],
    query: str,
    query_vector: list[float],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[NoteSearchResult]:
    """The RRF ranking query on its own, given an already-resolved job list
    and an already-computed query embedding.

    Split out from `search_notes` so the ranking SQL - the part T2.5 needs
    measured and the part any future caller might want to re-rank without
    re-embedding - is exercisable without a live embeddings API call. Real
    embeddings inserted directly and compared here, not a mock standing in
    for what the real vectors would rank - see `test_search_notes.py`.
    """
    query_embedding = "[" + ",".join(repr(float(x)) for x in query_vector) + "]"

    rows = session.execute(
        _HYBRID_SEARCH_QUERY,
        {
            "job_ids": job_ids,
            "query": query,
            "query_embedding": query_embedding,
            "rrf_k": RRF_K,
            "limit": limit,
        },
    ).all()

    return [
        NoteSearchResult(
            note_id=row.note_id,
            job_id=row.job_id,
            job_service_date=row.job_service_date,
            snippet=_snippet(row.content),
            score=row.score,
        )
        for row in rows
    ]
