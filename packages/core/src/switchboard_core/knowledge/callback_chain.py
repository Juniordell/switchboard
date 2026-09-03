"""`find_callback_source`: which job a callback-tagged job was a callback
*about*.

There is no foreign key for this in the source - a callback is discoverable
only from a tag and a date. **Two link rules, checked in order, because the
tags mean different things:**

1. **`Install callback (...)` or `Install Callback #N`** - the callback is
   about the installation. Link to the canonical address's own
   `knowledge.install_dates` row when one exists (T2.3a): the actual install
   job, not a guess.
2. **Anything else (including `Service Callback`, and an install-callback
   whose address has no `install_dates` row)** - link to the **most recent
   prior job at the same canonical address**, ranked by `completed_at`,
   among jobs that finished before this one's own service date. A callback is
   most plausibly about the visit immediately before it, not an older one -
   checked against every real multi-candidate case in the data before
   adopting this rule, not assumed.

**Coverage, measured, not estimated**: of 101 real callback-tagged jobs, 8
link via the install row, 53 via the most-recent-prior-job rule, and **40
have no findable candidate at all** - the callback is the first job on
record at that address, or no prior job there ever completed. `None` for
those, never a guess.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.knowledge.job_address import (
    job_canonical_id,
    jobs_at_canonical_address,
)

#: Exact tag spellings from the source - inconsistent casing ("Install
#: callback" vs "Install Callback #2") is the data, not a typo to fix.
INSTALL_CALLBACK_TAGS = frozenset(
    {
        "Install callback (service related)",
        "Install callback (Part Failure)",
        "Install Callback #2",
        "Install Callback #3",
        "Install Callback #4",
    }
)
SERVICE_CALLBACK_TAG = "Service Callback"
ALL_CALLBACK_TAGS = INSTALL_CALLBACK_TAGS | {SERVICE_CALLBACK_TAG}


def find_callback_source(session: Session, job_id: str) -> str | None:
    """`None` immediately for the ~1,900 jobs with no callback tag at all -
    no query beyond the tag check for the common case.
    """
    tags = set(
        session.execute(
            text("SELECT tag FROM source.job_tags WHERE job_id = :j"), {"j": job_id}
        ).scalars()
    )
    if not tags & ALL_CALLBACK_TAGS:
        return None

    job = session.execute(
        text(
            "SELECT address_street, address_street_line_2, address_zip, "
            "COALESCE(completed_at, scheduled_start, created_at) AS own_date "
            "FROM source.jobs WHERE id = :j"
        ),
        {"j": job_id},
    ).first()

    canonical_id = job_canonical_id(
        job.address_street, job.address_street_line_2, job.address_zip
    )
    if canonical_id is None:
        return None

    if tags & INSTALL_CALLBACK_TAGS:
        install_job_id = session.execute(
            text(
                "SELECT install_job_id FROM knowledge.install_dates "
                "WHERE canonical_id = :c"
            ),
            {"c": canonical_id},
        ).scalar()
        if install_job_id is not None and install_job_id != job_id:
            return install_job_id

    candidate_job_ids = jobs_at_canonical_address(session, canonical_id)
    if not candidate_job_ids:
        return None

    prior = session.execute(
        text(
            "SELECT id FROM source.jobs "
            "WHERE id = ANY(:ids) AND id != :self AND completed_at IS NOT NULL "
            "AND completed_at < :own_date "
            "ORDER BY completed_at DESC LIMIT 1"
        ),
        {"ids": candidate_job_ids, "self": job_id, "own_date": job.own_date},
    ).scalar()
    return prior
