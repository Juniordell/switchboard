"""`resolve_address`: spoken street to canonical address, with a confidence score.

Never returns `address.id`. Every candidate carries a `canonical_id`, so
nothing downstream can accidentally chain on the source's fragmented id - see
`switchboard_core.knowledge.address_normalize` for why that matters.

This is written as a plain typed function today, ahead of the tool contract
(Pydantic in, Pydantic out, `{call_id, agent, tool, ...}` logging) that T3.1
builds. The shape here - a Pydantic request in, a Pydantic result out - is
already what that contract expects; T3.1 wraps it, it does not change it.
"""

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.knowledge.address_normalize import normalize_street

#: Below this score, docs/AGENTS.md is explicit: the agent must ask, never
#: guess. Exposed here so a caller checks the same constant this module used
#: to decide `must_ask`, rather than hard-coding 0.55 a second place.
CONFIDENCE_THRESHOLD = 0.55

#: Two candidates within this score of each other are, for a caller who only
#: heard one imperfectly, indistinguishable - even when both individually
#: clear CONFIDENCE_THRESHOLD. Real example: "harborlight shores boulevard"
#: scores 0.806 against "4 Harborlight Shores Blvd S" and 0.784 against
#: "89 Harborlight Shores Blvd W", a gap of 0.022. Both are good matches; the
#: agent still cannot tell which one the caller means. Not specified anywhere
#: in docs/AGENTS.md - a judgement call, recorded in docs/DECISIONS.md.
AMBIGUOUS_GAP = 0.05

#: How many candidates resolve_address ever returns.
MAX_CANDIDATES = 3

#: SQL-side floor, well below CONFIDENCE_THRESHOLD, that lets Postgres use the
#: GIN trigram index (the `%` operator) to narrow candidates before ranking,
#: instead of computing similarity() against every one of the 1,337 rows.
#: Candidates this weak would never pass CONFIDENCE_THRESHOLD regardless.
_SQL_SIMILARITY_FLOOR = 0.2

_CANDIDATE_QUERY = text(
    """
    SELECT
        canonical_id,
        display_street,
        display_unit,
        display_city,
        display_state,
        zip,
        similarity(:query, street_normalized) AS score
    FROM knowledge.canonical_addresses
    WHERE street_normalized % :query
    ORDER BY score DESC
    LIMIT :limit
    """
)


class AddressCandidate(BaseModel):
    canonical_id: str
    display_address: str
    score: float


class ResolveAddressResult(BaseModel):
    query: str
    normalized_query: str
    candidates: list[AddressCandidate]

    #: True when the agent must ask rather than pick: no candidate at all,
    #: the top score is below CONFIDENCE_THRESHOLD, or the top two are close
    #: enough to be genuinely ambiguous. False means "confident and singular."
    must_ask: bool


def _display_address(row) -> str:
    parts = [row.display_street]
    if row.display_unit:
        parts.append(row.display_unit)
    location = ", ".join(p for p in (row.display_city, row.display_state) if p)
    if location:
        parts.append(location)
    if row.zip:
        parts.append(row.zip)
    return ", ".join(parts)


def resolve_address(session: Session, spoken_address: str) -> ResolveAddressResult:
    """Resolve a caller's spoken street to up to 3 canonical candidates.

    `spoken_address` is normalised the same way stored addresses were at load
    time - same function, same rules - which is what lets "eighty nine harbor
    light shores" clear the threshold against the stored "89 Harborlight
    Shores Blvd W": raw trigram similarity is 0.405; after normalising the
    spoken number into a digit, 0.625.
    """
    normalized = normalize_street(spoken_address)
    if not normalized:
        return ResolveAddressResult(
            query=spoken_address, normalized_query="", candidates=[], must_ask=True
        )

    # SET does not accept a bind parameter in Postgres ("syntax error at or
    # near $1"); the value is interpolated directly. Safe here because it is
    # the fixed module constant above, never caller input.
    session.execute(
        text(f"SET LOCAL pg_trgm.similarity_threshold = {_SQL_SIMILARITY_FLOOR}")
    )
    rows = session.execute(
        _CANDIDATE_QUERY, {"query": normalized, "limit": MAX_CANDIDATES}
    ).all()

    candidates = [
        AddressCandidate(
            canonical_id=row.canonical_id,
            display_address=_display_address(row),
            score=round(float(row.score), 4),
        )
        for row in rows
    ]

    if (
        not candidates
        or candidates[0].score < CONFIDENCE_THRESHOLD
        or (
            len(candidates) > 1
            and (candidates[0].score - candidates[1].score < AMBIGUOUS_GAP)
        )
    ):
        must_ask = True
    else:
        must_ask = False

    return ResolveAddressResult(
        query=spoken_address,
        normalized_query=normalized,
        candidates=candidates,
        must_ask=must_ask,
    )
