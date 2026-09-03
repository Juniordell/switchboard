"""`get_customer_balance`: what one customer owes, across every job.

`job.outstanding_balance` sums correctly to `SUM(invoice.due_amount)` even
for the 135 jobs with more than one invoice - verified against every
multi-invoice job in the dataset, not assumed from the single-invoice case
already checked in T1.5. Summing `job.outstanding_balance` per
`customer_id` is therefore both correct and simpler than joining invoices at
all: `customer_id` is a plain source id, never derived, so there is no
canonicalisation question here the way there is for an address.

231 of 732 customers carry a balance above zero.
"""

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session


class CustomerBalance(BaseModel):
    customer_id: str
    outstanding_balance: int
    job_count: int


_BALANCE_QUERY = text(
    """
    SELECT
        count(*) AS job_count,
        COALESCE(sum(outstanding_balance), 0) AS outstanding_balance
    FROM source.jobs
    WHERE customer_id = :customer_id
    """
)


def get_customer_balance(session: Session, customer_id: str) -> CustomerBalance:
    """Cents owed across every job this customer has, paid or not.

    Returns a zero balance for a customer with no jobs at all rather than
    raising - `job_count` distinguishes "owes nothing" from "no history
    found" for a caller that needs to.
    """
    row = session.execute(_BALANCE_QUERY, {"customer_id": customer_id}).one()
    return CustomerBalance(
        customer_id=customer_id,
        outstanding_balance=row.outstanding_balance,
        job_count=row.job_count,
    )
