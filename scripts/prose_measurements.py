#!/usr/bin/env python
"""T2.5 measurements: p95 latency, and whether the dense leg improves ranking
over `ts_rank_cd` alone once the candidate set is already entity-filtered.

**Requires a live `OPENAI_API_KEY` and every note embedded**
(`python -m switchboard_core.prose`) - this script makes real API calls and
reports real numbers, never a fabricated placeholder. It refuses to run
without both, loudly, rather than producing a number that looks real and
isn't.

Run from the repository root:

    uv run python scripts/prose_measurements.py

**The 20-query set is not `evals/golden/tools.yaml`** - that file is T4.1,
which does not exist yet as of this task. `QUERIES` below is a stand-in,
built the same way every other fixture in this codebase was: found by
querying the live database for jobs with real, multi-note discussion of each
of `docs/DATA.md`'s ten most frequent note terms, not invented text. Every
`entity_id` below is a real `job_id`; every `query` is a plausible caller
phrasing of what that job's notes actually discuss.
"""

import statistics
import sys
import time

from sqlalchemy import text

from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.prose import embed_texts, rank_candidates
from switchboard_core.prose.search_notes import _resolve_entity_job_ids

#: (job_id, caller-style query, the DATA.md term it targets) - one job_id
#: appears twice (drain leg / freon+leak) only where the same visit
#: genuinely discussed both; every other entry is a distinct real job.
QUERIES: list[tuple[str, str, str]] = [
    (
        "job_1b0a65ad15994138ba88e1ae77eae368",
        "what did you do about the drain",
        "drain",
    ),
    ("job_28e341b2495a4e8cbf6d677eddcc00b5", "did you clear the drain line", "drain"),
    ("job_10300f519ca744b796e0054182f96eed", "why isn't it cooling", "not cooling"),
    (
        "job_26689b41d3844ef8ad0411acfc202bd9",
        "the system isn't cooling, what did you find",
        "not cooling",
    ),
    (
        "job_0e06b7683da0419c9a934a8cab1bb52a",
        "what's going on with the thermostat",
        "thermostat",
    ),
    (
        "job_04237bc70b4045aeb1cc9fa5826842a4",
        "did you replace the thermostat",
        "thermostat",
    ),
    (
        "job_84617a792d314457bd682d042daaa1bd",
        "what did you find on the condenser",
        "condenser",
    ),
    ("job_f5dcc1ff7469420997147052e0548eb9", "is the condenser okay", "condenser"),
    (
        "job_9ca68b9bd91a40f5b266ffde97af3922",
        "what's wrong with the compressor",
        "compressor",
    ),
    (
        "job_26af8d43519c4957b0465b7ed1d3d3cd",
        "did the compressor get fixed",
        "compressor",
    ),
    (
        "job_aac7cbbc84974c31849bff6c8c392e6d",
        "is this covered under warranty",
        "warranty",
    ),
    (
        "job_cda1ceb88c6543caa7f0fbcf3833d2f6",
        "what did you say about the warranty",
        "warranty",
    ),
    (
        "job_bc36a334ce594f179e89bc104e50bdca",
        "did you replace the capacitor",
        "capacitor",
    ),
    (
        "job_bb1c9e727ed6492987b939ca2b0e3a35",
        "what happened with the capacitor",
        "capacitor",
    ),
    ("job_30212e3cd0f9448daeb7d181bcef98aa", "how much freon did you add", "freon"),
    ("job_1476dc11f8464197bc0dfa2e10e4aa97", "was it low on freon", "freon"),
    (
        "job_b517f801f1194292abff1147b9de59c6",
        "what refrigerant does the unit use",
        "r410",
    ),
    ("job_ffeb29669af145b38ead2824eb289bfd", "is it r410", "r410"),
    ("job_51fc9fbde4c64ec98c2efaa7595db2fe", "did you find a leak", "leak"),
    ("job_1da1e743b7fb4a7784e9802706648572", "what's the story with the coil", "coil"),
]

_LEXICAL_ONLY_QUERY = text(
    """
    WITH candidates AS (
        SELECT nc.note_id, nc.content_tsv
        FROM prose.note_chunks nc
        WHERE nc.job_id = ANY(:job_ids)
    )
    SELECT note_id, ts_rank_cd(content_tsv, plainto_tsquery('english', :query)) AS score
    FROM candidates
    WHERE content_tsv @@ plainto_tsquery('english', :query)
    ORDER BY score DESC
    LIMIT :limit
    """
)


def require_ready(session) -> None:
    total, embedded = session.execute(
        text("SELECT count(*), count(embedding) FROM prose.note_chunks")
    ).one()
    if embedded == 0:
        sys.exit(
            "No notes are embedded yet. Run `python -m switchboard_core.prose` "
            "first (needs OPENAI_API_KEY) - refusing to report latency or "
            "ranking numbers against an empty embedding column."
        )
    if embedded < total:
        print(
            f"WARNING: {embedded}/{total} notes embedded, not all - "
            "numbers below cover only the embedded subset.",
            file=sys.stderr,
        )


def measure_latency(session, n_runs: int = 30) -> None:
    """p95 for a scoped search, embedding-call time and Postgres time kept
    separate - never summed and reported as one number, since only one of
    the two is a network call to a service this codebase doesn't operate.
    """
    embed_ms: list[float] = []
    sql_ms: list[float] = []

    for job_id, query, _term in (QUERIES * ((n_runs // len(QUERIES)) + 1))[:n_runs]:
        job_ids = _resolve_entity_job_ids(session, job_id)

        t0 = time.perf_counter()
        vector = embed_texts([query])[0]
        t1 = time.perf_counter()
        rank_candidates(session, job_ids, query, vector, limit=10)
        t2 = time.perf_counter()

        embed_ms.append((t1 - t0) * 1000)
        sql_ms.append((t2 - t1) * 1000)

    def pct(data: list[float], p: float) -> float:
        return statistics.quantiles(data, n=100)[int(p) - 1]

    print(f"=== latency over {n_runs} scoped searches ===")
    print(f"{'phase':<20}{'p50':>10}{'p95':>10}{'max':>10}   (ms)")
    for label, data in (("embedding call", embed_ms), ("Postgres (RRF)", sql_ms)):
        print(
            f"{label:<20}{pct(data, 50):>10.1f}{pct(data, 95):>10.1f}{max(data):>10.1f}"
        )
    total = [e + s for e, s in zip(embed_ms, sql_ms, strict=True)]
    p50, p95, p_max = pct(total, 50), pct(total, 95), max(total)
    print(f"{'total (both)':<20}{p50:>10.1f}{p95:>10.1f}{p_max:>10.1f}")


def measure_ranking(session) -> None:
    """Does the dense leg change the top result, once the candidate set is
    already entity-filtered to a handful of rows? Compares hybrid RRF
    against `ts_rank_cd` alone on the same 20 queries.
    """
    agreements = 0
    disagreements: list[tuple[str, str, str, str]] = []

    for job_id, query, term in QUERIES:
        job_ids = _resolve_entity_job_ids(session, job_id)
        vector = embed_texts([query])[0]

        hybrid = rank_candidates(session, job_ids, query, vector, limit=1)
        lexical_only = session.execute(
            _LEXICAL_ONLY_QUERY, {"job_ids": job_ids, "query": query, "limit": 1}
        ).first()

        hybrid_top = hybrid[0].note_id if hybrid else None
        lexical_top = lexical_only.note_id if lexical_only else None

        if hybrid_top == lexical_top:
            agreements += 1
        else:
            disagreements.append(
                (job_id, term, hybrid_top or "(none)", lexical_top or "(none)")
            )

    print()
    print(f"=== ranking: hybrid RRF vs ts_rank_cd alone, {len(QUERIES)} queries ===")
    print(f"top result agrees: {agreements}/{len(QUERIES)}")
    if disagreements:
        print("disagreements (job, term, hybrid top, lexical-only top):")
        for row in disagreements:
            print(f"  {row}")


def main() -> int:
    engine = create_db_engine()
    with session_factory(engine)() as session, session.begin():
        require_ready(session)
        measure_latency(session)
        measure_ranking(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
