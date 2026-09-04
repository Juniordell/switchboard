"""`evaluate_warranty_status`: the six-level precedence rule from
`docs/DATA.md`, combined.

**Scope is the canonical address plus the equipment named, never a job.** A
caller asks about a compressor at a house; the evidence for it is scattered
across several jobs at that address. `jobs_at_canonical_address` gathers every
job there first; every level below searches across all of them, not one.

**The return is never a bare boolean.** Every result carries `covered`
(`yes` / `no` / `unknown` - three states, because absence of evidence and an
explicit denial are different facts and must never collapse into the same
value), `level` (1-6, which rule fired - `docs/AGENTS.md`'s refusal rules
name levels 4, 5 and 6 directly, so the agent needs this to decide how to
speak the answer), `basis` (human-readable), `evidence` (the one row that
justifies it - a job, an invoice, or a note, never more than one), and
`confidence`.

**Order, and it is checked in this order, top to bottom:**

1. An explicit warranty term in a note ("under warranty until 2030", "out of
   warranty") - the only level that can produce `covered=no`. See
   `warranty_notes.py`.
2. A `WARRANTY` invoice line item - historical evidence the part *was*
   covered, never a denial.
3. A derived install within 12 months (`warranty_level_3.py`) - never a
   denial either: no install on file, or one older than 12 months, both
   produce `NO_VERDICT` and fall through, because absence of a derivable
   install date is not evidence of absence of coverage (95.4% of addresses
   have no row at all - see `docs/DECISIONS.md` 50-54).
4. `Warranty Claim` or `Registration Needed` - something is in flight;
   `covered=unknown`, offer a human, never assert an outcome.
5. `Warranty Complete` - **neutral**, never checked as its own branch with a
   verdict. Recorded if seen, and mentioned as context if the cascade falls
   all the way to level 6, but it never produces `covered=no` on its own -
   the whole point of this task. See `TestWarrantyCompleteIsNeverADenial`.
6. Nothing found - `covered=unknown`.
"""

import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.knowledge.job_address import jobs_at_canonical_address
from switchboard_core.knowledge.warranty_level_3 import Level3Verdict, evaluate_level_3
from switchboard_core.knowledge.warranty_notes import (
    NoteWarrantyClaim,
    classify_note_warranty_term,
)


class WarrantyCoverage(StrEnum):
    """Four states, not three, and not a boolean.

    `WAS_COVERED` exists because of a real call. Level 2 used to return
    `YES` with a `basis` that carefully explained the coverage was
    historical, and the agent read the field and said "yes, the TXV is
    under warranty" - present tense, about a 2023 invoice. The prose was
    right and got ignored, which is what prose does when a structured
    field next to it says something simpler.

    `docs/AGENTS.md`: "Level 2 is stated as historical: the part *was*
    covered on that visit, which is not the same as covered today." That
    sentence is now a value rather than a paragraph in a prompt.
    """

    YES = "yes"
    WAS_COVERED = "was_covered"
    NO = "no"
    UNKNOWN = "unknown"


class WarrantyConfidence(StrEnum):
    HIGH = "high"
    HIGH_HISTORICAL = "high_historical"
    MEDIUM = "medium"
    UNKNOWN = "unknown"


class WarrantyEvidence(BaseModel):
    kind: Literal["job", "invoice", "note"]
    id: str

    #: How the agent refers to this aloud. `id` is what the dashboard
    #: links to; for a job it is the internal `job_...` id, and a real
    #: caller was told their warranty was "associated with job number
    #: job_92c15112f0524b9f9ce428c420297fea". The tool layer fills this
    #: with the job number, the invoice number, or the visit - never an
    #: id - and the agent is told to speak this field and nothing else.
    spoken: str = ""


class WarrantyStatusResult(BaseModel):
    covered: WarrantyCoverage
    level: int
    basis: str
    evidence: WarrantyEvidence | None
    confidence: WarrantyConfidence


_LEVEL_4_TAGS = ("Warranty Claim", "Registration Needed")
_LEVEL_5_TAG = "Warranty Complete"


def _level_1_notes(
    session: Session, job_ids: list[str], equipment: str | None
) -> WarrantyStatusResult | None:
    if not job_ids:
        return None
    rows = session.execute(
        text(
            "SELECT n.id AS note_id, n.content, n.job_id, "
            "COALESCE(j.completed_at, j.scheduled_start, j.created_at) AS job_date "
            "FROM source.notes n JOIN source.jobs j ON j.id = n.job_id "
            "WHERE n.job_id = ANY(:job_ids) AND n.content ILIKE '%warrant%'"
        ),
        {"job_ids": job_ids},
    ).all()

    matches = []
    for row in rows:
        if equipment and equipment.lower() not in row.content.lower():
            continue
        claim = classify_note_warranty_term(row.content)
        if claim is not None:
            matches.append((row.job_date, row.note_id, row.job_id, row.content, claim))

    if not matches:
        return None

    # Most recent statement wins: warranty facts change over time, and a
    # later "out of warranty" note supersedes an earlier "still covered" one.
    job_date, note_id, _job_id, content, claim = max(matches, key=lambda m: m[0])
    covered = (
        WarrantyCoverage.YES
        if claim is NoteWarrantyClaim.COVERED
        else WarrantyCoverage.NO
    )
    service_date = job_date.date().isoformat() if job_date else "an unknown date"
    return WarrantyStatusResult(
        covered=covered,
        level=1,
        basis=(f"tech's note from the visit on {service_date}: {content.strip()!r}"),
        evidence=WarrantyEvidence(kind="note", id=note_id),
        confidence=WarrantyConfidence.HIGH,
    )


def _level_2_invoice_items(
    session: Session, job_ids: list[str], equipment: str | None
) -> WarrantyStatusResult | None:
    if not job_ids:
        return None
    rows = session.execute(
        text(
            "SELECT ii.name, i.invoice_number, "
            "COALESCE(i.service_date, i.invoice_date) AS item_date "
            "FROM source.invoice_items ii "
            "JOIN source.invoices i ON i.id = ii.invoice_id "
            "WHERE i.job_id = ANY(:job_ids) AND ii.name ILIKE '%warrant%'"
        ),
        {"job_ids": job_ids},
    ).all()

    matches = [
        row for row in rows if not equipment or equipment.lower() in row.name.lower()
    ]
    if not matches:
        return None

    row = max(matches, key=lambda r: r.item_date or datetime.datetime.min)
    date_str = row.item_date.date().isoformat() if row.item_date else "an unknown date"
    return WarrantyStatusResult(
        covered=WarrantyCoverage.WAS_COVERED,
        level=2,
        basis=(
            f"invoice {row.invoice_number} ({date_str}) billed "
            f"{row.name!r} as manufacturer-covered - historical evidence "
            f"this part was covered on that visit, not proof of coverage today"
        ),
        evidence=WarrantyEvidence(kind="invoice", id=row.invoice_number),
        confidence=WarrantyConfidence.HIGH_HISTORICAL,
    )


def _level_3_install_date(
    session: Session, canonical_id: str, as_of: datetime.datetime
) -> WarrantyStatusResult | None:
    row = session.execute(
        text(
            "SELECT install_job_id, install_date FROM knowledge.install_dates "
            "WHERE canonical_id = :c"
        ),
        {"c": canonical_id},
    ).first()

    result = evaluate_level_3(
        install_job_id=row.install_job_id if row else None,
        install_date=row.install_date if row else None,
        as_of=as_of,
    )
    if result.verdict is not Level3Verdict.COVERED:
        return None

    return WarrantyStatusResult(
        covered=WarrantyCoverage.YES,
        level=3,
        basis=f"labor warranty: {result.basis}",
        evidence=WarrantyEvidence(kind="job", id=result.install_job_id),
        confidence=WarrantyConfidence.HIGH,
    )


def _level_4_claim_or_registration(
    session: Session, job_ids: list[str]
) -> WarrantyStatusResult | None:
    if not job_ids:
        return None
    rows = session.execute(
        text(
            "SELECT t.job_id, t.tag, "
            "COALESCE(j.completed_at, j.scheduled_start, j.created_at) AS job_date "
            "FROM source.job_tags t JOIN source.jobs j ON j.id = t.job_id "
            "WHERE t.job_id = ANY(:job_ids) AND t.tag = ANY(:tags)"
        ),
        {"job_ids": job_ids, "tags": list(_LEVEL_4_TAGS)},
    ).all()
    if not rows:
        return None

    row = max(rows, key=lambda r: r.job_date or datetime.datetime.min)
    return WarrantyStatusResult(
        covered=WarrantyCoverage.UNKNOWN,
        level=4,
        basis=(
            f"job {row.job_id} is tagged {row.tag!r} - a claim or "
            f"registration is in flight; the outcome is not yet known"
        ),
        evidence=WarrantyEvidence(kind="job", id=row.job_id),
        confidence=WarrantyConfidence.MEDIUM,
    )


def _level_5_warranty_complete_job_id(
    session: Session, job_ids: list[str]
) -> str | None:
    if not job_ids:
        return None
    return session.execute(
        text(
            "SELECT job_id FROM source.job_tags "
            "WHERE job_id = ANY(:job_ids) AND tag = :tag LIMIT 1"
        ),
        {"job_ids": job_ids, "tag": _LEVEL_5_TAG},
    ).scalar()


def evaluate_warranty_status(
    session: Session,
    canonical_id: str,
    *,
    equipment: str | None = None,
    as_of: datetime.datetime,
) -> WarrantyStatusResult:
    """Evaluate warranty coverage for one canonical address, optionally
    scoped to one named piece of equipment.

    `as_of` is required and never defaulted to "now" internally - the caller
    (the live call, or a test with a fixed instant) decides what moment this
    is evaluated against, same reasoning as `evaluate_level_3`.
    """
    job_ids = jobs_at_canonical_address(session, canonical_id)

    level_1 = _level_1_notes(session, job_ids, equipment)
    if level_1 is not None:
        return level_1

    level_2 = _level_2_invoice_items(session, job_ids, equipment)
    if level_2 is not None:
        return level_2

    level_3 = _level_3_install_date(session, canonical_id, as_of)
    if level_3 is not None:
        return level_3

    level_4 = _level_4_claim_or_registration(session, job_ids)
    if level_4 is not None:
        return level_4

    # Level 5 never returns on its own - it is neutral context, not a
    # verdict. Only remembered so level 6's basis can mention it.
    warranty_complete_job_id = _level_5_warranty_complete_job_id(session, job_ids)

    if warranty_complete_job_id is not None:
        return WarrantyStatusResult(
            covered=WarrantyCoverage.UNKNOWN,
            level=6,
            basis=(
                "not known. A related visit "
                f"(job {warranty_complete_job_id}) was tagged 'Warranty "
                "Complete', meaning warranty work was finished on that "
                "visit - not that coverage has ended. Offer to have "
                "someone check."
            ),
            evidence=WarrantyEvidence(kind="job", id=warranty_complete_job_id),
            confidence=WarrantyConfidence.UNKNOWN,
        )

    return WarrantyStatusResult(
        covered=WarrantyCoverage.UNKNOWN,
        level=6,
        basis="not known. Offer to have someone check.",
        evidence=None,
        confidence=WarrantyConfidence.UNKNOWN,
    )
