"""Building `knowledge.install_dates`.

There is no install date field on a job. This derives one: among jobs whose
`description` identifies a whole-system install, the most recent per
canonical address becomes that address's install date.

**Which descriptions count as an install, and why.** Naively matching the
word "install" anywhere catches noise - fixture and part installs
("Install New Angle Stop", "Customer supplied toilet install", "Install
Rinnai RX199") that have nothing to do with an HVAC system. The three
prefixes below were chosen and checked, not guessed:

- Median invoice for a matched job is $10k-27k, against $456 for an ordinary
  "Service Calls - Repairs" job - an order of magnitude apart, the signature
  of a whole system rather than a part.
- The matched jobs carry `Registration Needed` (32) and `Registration
  Complete` (14) tags - manufacturer equipment registration, which only
  makes sense right after installing new equipment.
- Two adjacent description prefixes that also contain "install" were checked
  by reading their notes and excluded: `Zone System Installation` ("zones
  installed and operational" - dampers added to an *existing* system) and
  `System Relocation - System Installation` ("Air handler is relocated" -
  the *existing* unit moved, not a new one). Neither starts a new install
  clock.

**Coverage is thin on purpose, not by bug**: only 62 of 1,337 canonical
addresses get a row. An install is rare inside a six-month export; most
addresses' equipment predates the data window. Level 3 of the warranty
precedence rule (docs/DATA.md) falls through for the other 1,275 - that is
what should happen when no install is visible, not a sign this derivation
missed something.

Must run after `build_canonical_addresses` - it reads `canonical_addresses`
and links through `job_canonical_id`, not through `address_alias` directly,
so it also correctly finds no address for a job the alias table itself could
never resolve (a null `address_id`) as long as the job carries a real street.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from switchboard_core.db.knowledge import CanonicalAddress, InstallDate
from switchboard_core.db.source import Job
from switchboard_core.knowledge.job_address import job_canonical_id
from switchboard_core.load.upsert import upsert

log = logging.getLogger(__name__)

#: Checked against invoice amounts, registration tags and notes - see the
#: module docstring. Deliberately excludes zone/damper work and system
#: relocations, which also contain the word "install" but are not a new
#: system going in.
INSTALL_DESCRIPTION_PREFIXES = (
    "System Installation",
    "New System Installation",
    "New Construction",
)


def build_install_dates(session: Session) -> dict[str, int]:
    # canonical_id is derived from code (see build_addresses.py's docstring
    # for why that means rebuild, not upsert), and this table's primary key
    # is that same canonical_id - the same risk applies here.
    session.execute(delete(InstallDate))

    known_canonical_ids = set(
        session.execute(select(CanonicalAddress.canonical_id)).scalars()
    )

    candidates = session.execute(
        select(
            Job.id,
            Job.completed_at,
            Job.address_street,
            Job.address_street_line_2,
            Job.address_zip,
        ).where(
            Job.completed_at.is_not(None),
            Job.description.startswith(INSTALL_DESCRIPTION_PREFIXES[0])
            | Job.description.startswith(INSTALL_DESCRIPTION_PREFIXES[1])
            | Job.description.startswith(INSTALL_DESCRIPTION_PREFIXES[2]),
        )
    ).all()

    # Most recent install job per canonical address. A canonical address can
    # have more than one - one real address in this data has two, four days
    # apart, most likely two separate systems replaced on the same project.
    latest: dict[str, tuple[str, object]] = {}
    unresolved = 0
    for row in candidates:
        canonical_id = job_canonical_id(
            row.address_street, row.address_street_line_2, row.address_zip
        )
        if canonical_id is None or canonical_id not in known_canonical_ids:
            unresolved += 1
            continue
        current = latest.get(canonical_id)
        if current is None or row.completed_at > current[1]:
            latest[canonical_id] = (row.id, row.completed_at)

    if unresolved:
        log.warning(
            "%d install-candidate job(s) did not resolve to a canonical "
            "address and were excluded",
            unresolved,
        )

    rows = [
        {
            "canonical_id": canonical_id,
            "install_job_id": job_id,
            "install_date": completed_at,
        }
        for canonical_id, (job_id, completed_at) in latest.items()
    ]

    return {
        "install_dates": upsert(session, InstallDate, rows),
        "install_candidates_seen": len(candidates),
        "install_candidates_unresolved": unresolved,
    }
