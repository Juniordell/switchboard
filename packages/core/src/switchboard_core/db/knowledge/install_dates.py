"""Derived install date: one row per canonical address that has a system
install visible in the data.

There is no install date field on a job - see docs/DATA.md. This table is
built by `switchboard_core.knowledge.build_install_dates` from jobs whose
`description` identifies a whole-system install (`System Installation`,
`New System Installation`, `New Construction`), taking the most recent one's
`completed_at` per canonical address. Only **62 of the 1,337** canonical
addresses get a row: an install is a rare event inside a 6-month export, and
most addresses' units were installed before the data window or by someone
else. Level 3 of the warranty precedence rule falls through for the other
1,275 - expected, not a bug.

`canonical_id` cascades on delete from `canonical_addresses`. Every table in
`knowledge` is fully derived and rebuilt from `source` on each load - see
`build_addresses.py` - so when `build_canonical_addresses` deletes and
rebuilds `canonical_addresses` on a second run, a stale `install_dates` row
still pointing at the row about to disappear is not data worth protecting,
it is a row `build_install_dates` is about to recompute anyway in the same
transaction. Without the cascade, that second run's `DELETE FROM
canonical_addresses` fails outright with a foreign key violation, since
`install_dates` (built by an unrelated function, in the *previous* run) is
still holding a reference to it - caught by actually loading twice, not
inferred from the schema.
"""

import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import KNOWLEDGE_SCHEMA, SOURCE_SCHEMA, Base


class InstallDate(Base):
    __tablename__ = "install_dates"
    __table_args__ = {"schema": KNOWLEDGE_SCHEMA}

    canonical_id: Mapped[str] = mapped_column(
        ForeignKey(
            f"{KNOWLEDGE_SCHEMA}.canonical_addresses.canonical_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    #: The job whose completed_at produced install_date - cited when a
    #: warranty answer names "the install job", per docs/DATA.md's precedence
    #: rule. Not the only install job at this address if there was more than
    #: one; see docs/DECISIONS.md for the one address with two.
    install_job_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SOURCE_SCHEMA}.jobs.id"), index=True
    )

    install_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
