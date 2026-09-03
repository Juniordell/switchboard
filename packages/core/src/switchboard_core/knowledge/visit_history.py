"""`get_visit_history`: every visit at one canonical address, structured, no
generated prose.

**Query-time function, not a materialised table.** Like `resolve_address`
(T2.1) and `evaluate_warranty_status` (T2.3b), and for the same reason:
there is no reduction here - install_dates collapsed many candidate jobs down
to one row per address, which is what justified precomputing it, but a visit
history keeps every job as its own row. Materialising a 1:1-ish reshape of
`source.jobs` would duplicate data already there for no benefit; a canonical
address has 1.4-1.5 jobs on average, so the join is trivial at query time.

**Zero generated prose.** Every field is a fact traceable to a source column:
service date, tech names, description, job number, invoice numbers, balance,
and the job this one was a callback from, if any. A pre-computed summary
would be a model sitting inside the layer that promises not to have one
(`docs/ARCHITECTURE.md`: "Knowledge... no model in the path"). The agent
summarises the rows at speaking time, with the caller's actual question in
front of it; this function never does.

**`job_number`, never `invoice_number`.** `job.invoice_number` is the job
number and joining on it instead of `job_id` lands on another customer's
invoice 1,682 times out of 1,687 - CLAUDE.md hard rule 8. Every invoice
referenced here is reached through `Invoice.job_id == Job.id`, nothing else.

Ordered by service date, most recent first, so "the last time" is the first
row, not a claim the caller has to verify.
"""

import datetime

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.knowledge.callback_chain import find_callback_source
from switchboard_core.knowledge.job_address import jobs_at_canonical_address


class VisitRow(BaseModel):
    job_id: str
    job_number: str
    service_date: datetime.datetime
    work_status: str
    description: str
    techs: list[str]
    invoice_numbers: list[str]
    outstanding_balance: int
    callback_from_job_id: str | None


_VISIT_QUERY = text(
    """
    SELECT
        j.id AS job_id,
        j.job_number,
        COALESCE(j.completed_at, j.scheduled_start, j.created_at) AS service_date,
        j.work_status,
        j.description,
        j.outstanding_balance,
        (
            SELECT array_agg(e.first_name || ' ' || e.last_name ORDER BY je.position)
            FROM source.job_employees je
            JOIN source.employees e ON e.id = je.employee_id
            WHERE je.job_id = j.id
        ) AS techs,
        (
            SELECT array_agg(i.invoice_number ORDER BY i.invoice_number)
            FROM source.invoices i
            WHERE i.job_id = j.id
        ) AS invoice_numbers
    FROM source.jobs j
    WHERE j.id = ANY(:job_ids)
    ORDER BY service_date DESC
    """
)


def get_visit_history(session: Session, canonical_id: str) -> list[VisitRow]:
    """Every job at `canonical_id`, most recent service date first."""
    job_ids = jobs_at_canonical_address(session, canonical_id)
    if not job_ids:
        return []

    rows = session.execute(_VISIT_QUERY, {"job_ids": job_ids}).all()

    return [
        VisitRow(
            job_id=row.job_id,
            job_number=row.job_number,
            service_date=row.service_date,
            work_status=row.work_status,
            description=row.description,
            techs=row.techs or [],
            invoice_numbers=row.invoice_numbers or [],
            outstanding_balance=row.outstanding_balance,
            callback_from_job_id=find_callback_source(session, row.job_id),
        )
        for row in rows
    ]
