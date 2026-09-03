"""`resolve_customer`: a spoken name, or an already-resolved address, to
customer candidates with confidence.

Same candidate + confidence shape as `resolve_address` (T2.1), and the same
two thresholds, for the same reason: a caller who half-says a name leaves
two real customers individually plausible and jointly indistinguishable,
and that is an ask, not a guess.

**No trigram index, deliberately.** `resolve_address` indexes because it
ranks against 1,337 canonical addresses using the `%` operator to narrow
first. There are 732 customers, and `similarity()` over 732 short strings
is a sub-millisecond sequential scan - an index and the migration to create
it would be weight this table does not need. Revisit if the customer table
ever grows by an order of magnitude.

The name this searches is the customer's company and personal name
concatenated, because the dataset does not keep them in predictable places:
"Starfish Hospitality" lives in `company` with empty names, and "Lighthouse
Hospitality" lives in `first_name`/`last_name` with an empty company. One
search string covers both without branching on `kind`, which
`docs/AGENTS.md` says is unreliable anyway.
"""

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.knowledge.resolve_address import (
    AMBIGUOUS_GAP,
    CONFIDENCE_THRESHOLD,
    MAX_CANDIDATES,
)

#: The searchable name, built the same way in every query here.
_SEARCH_NAME = (
    "trim(both ' ' from "
    "coalesce(c.company, '') || ' ' || "
    "coalesce(c.first_name, '') || ' ' || "
    "coalesce(c.last_name, ''))"
)

_BY_NAME_QUERY = text(
    f"""
    SELECT
        c.id AS customer_id,
        {_SEARCH_NAME} AS display_name,
        c.kind,
        c.job_count,
        similarity(:query, lower({_SEARCH_NAME})) AS score
    FROM source.customers c
    WHERE similarity(:query, lower({_SEARCH_NAME})) > 0
    ORDER BY score DESC, display_name
    LIMIT :limit
    """
)

#: Address to customer without touching a single job row: the alias table
#: maps the canonical address back to the source address ids, and
#: `customer_addresses` maps those to customers. Staying off `source.jobs`
#: keeps this inside the Triage boundary by construction, not by promise.
_BY_ADDRESS_QUERY = text(
    f"""
    SELECT DISTINCT
        c.id AS customer_id,
        {_SEARCH_NAME} AS display_name,
        c.kind,
        c.job_count
    FROM knowledge.address_alias al
    JOIN source.customer_addresses ca ON ca.address_id = al.address_id
    JOIN source.customers c ON c.id = ca.customer_id
    WHERE al.canonical_id = :canonical_id
    ORDER BY display_name
    """
)


class CustomerCandidate(BaseModel):
    customer_id: str
    display_name: str

    #: Straight off the record and not to be trusted on its own: 31
    #: `homeowner` rows carry a company and 48 are plainly businesses.
    #: `identify_caller_role` weighs it against other signals.
    kind: str

    #: How many jobs this customer has, from the customer record's own
    #: column. Not job data - no date, no address, no description, nothing
    #: about any individual visit - and `identify_caller_role` needs it to
    #: tell a homeowner from a property manager.
    job_count: int

    #: Trigram similarity for a name match; 1.0 for an address match, which
    #: is structural rather than fuzzy.
    score: float


class ResolveCustomerResult(BaseModel):
    query: str
    candidates: list[CustomerCandidate]
    must_ask: bool


def _verdict(candidates: list[CustomerCandidate], query: str) -> bool:
    """`must_ask`: no candidate, a weak top score, a top two close enough
    that the caller's words cannot separate them, or a name the caller may
    simply not have finished saying.

    That last rule is not in `resolve_address`, and it is here because
    trigram similarity measures length, not meaning. "lighthouse" scores
    1.0 against the customer literally named "Lighthouse" and 0.478
    against "Lighthouse Hospitality" - a gap of 0.52, decisive by the
    numeric rule and meaningless in fact, since a caller saying
    "Lighthouse" may be either one and has probably just stopped early.
    Where more than one customer's name begins with what the caller said,
    the tool asks.
    """
    if not candidates:
        return True
    if candidates[0].score < CONFIDENCE_THRESHOLD:
        return True
    if (
        len(candidates) > 1
        and (candidates[0].score - candidates[1].score) < AMBIGUOUS_GAP
    ):
        return True

    spoken = query.strip().lower()
    prefixed = [c for c in candidates if c.display_name.lower().startswith(spoken)]
    return len(prefixed) > 1


def resolve_customer(
    session: Session,
    *,
    name: str | None = None,
    canonical_id: str | None = None,
) -> ResolveCustomerResult:
    """Resolve by spoken name, by resolved address, or by both.

    With both, the address is the stronger signal and filters the name
    match rather than competing with it - a caller who gives an address and
    a partial name is describing one person, not two candidates.
    """
    if not name and not canonical_id:
        raise ValueError("resolve_customer needs a name or a canonical_id, got neither")

    by_address: list[CustomerCandidate] = []
    if canonical_id:
        by_address = [
            CustomerCandidate(
                customer_id=row.customer_id,
                display_name=row.display_name,
                kind=row.kind,
                job_count=row.job_count,
                score=1.0,
            )
            for row in session.execute(
                _BY_ADDRESS_QUERY, {"canonical_id": canonical_id}
            ).all()
        ]

    if not name:
        return ResolveCustomerResult(
            query=canonical_id or "",
            candidates=by_address[:MAX_CANDIDATES],
            # One customer at the address is an answer; several is a real
            # ambiguity the caller has to settle.
            must_ask=len(by_address) != 1,
        )

    rows = session.execute(
        _BY_NAME_QUERY, {"query": name.strip().lower(), "limit": MAX_CANDIDATES}
    ).all()
    by_name = [
        CustomerCandidate(
            customer_id=row.customer_id,
            display_name=row.display_name,
            kind=row.kind,
            job_count=row.job_count,
            score=row.score,
        )
        for row in rows
    ]

    if canonical_id:
        at_address = {c.customer_id for c in by_address}
        narrowed = [c for c in by_name if c.customer_id in at_address]
        # A name that matches nobody at that address is not evidence
        # against the address; fall back to who is actually there.
        candidates = narrowed or by_address
    else:
        candidates = by_name

    candidates = candidates[:MAX_CANDIDATES]
    return ResolveCustomerResult(
        query=name, candidates=candidates, must_ask=_verdict(candidates, name)
    )
