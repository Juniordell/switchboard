"""Level 3 of the warranty precedence rule, on its own — locked down ahead of
T2.3b, which will call this as one of six checks.

**The rule this file exists to enforce**: absence of a derivable install date
is not evidence of absence of warranty coverage. 1,275 of the 1,337 canonical
addresses (95.4%) have no row in `knowledge.install_dates` — most equipment in
this dataset was installed before the six-month export window, not
"never installed" or "never covered." Level 3 answering "not covered" for any
of those 1,275 would be confidently wrong on the majority of this system's
warranty questions.

So level 3 has exactly two outcomes, encoded so the third is not just untested
but **inexpressible**: `Level3Verdict.COVERED`, asserted only when an install
within the last 12 months is on file, or `Level3Verdict.NO_VERDICT` —
everything else, including "no install date at all" and "an install date on
file, just an old one." `Level3Verdict` has no `NOT_COVERED` member; there is
nothing this module can return that a caller could misread as a denial.
`NO_VERDICT` means exactly what `docs/DATA.md`'s precedence table already
says for a level that doesn't fire: fall through to level 4, not "no."

**Spoken text must carry the same distinction.** `NO_VERDICT` is "I don't have
an install date on file for this address — I can have someone check," never
"you're not covered." Enforcing that in what gets said out loud is a Phase 5
concern; this module only guarantees the value handed to Phase 5 cannot be
confused for a denial in the first place.
"""

import calendar
import datetime
from dataclasses import dataclass
from enum import StrEnum

#: The warranty term. A judgement call on the boundary, not stated in
#: docs/DATA.md: covered through the exact 12-month anniversary, not up to
#: the day before it.
LABOR_WARRANTY_MONTHS = 12


class Level3Verdict(StrEnum):
    """Exactly two members, on purpose. See the module docstring."""

    COVERED = "covered"
    NO_VERDICT = "no_verdict"


@dataclass(frozen=True)
class Level3Result:
    verdict: Level3Verdict
    install_job_id: str | None
    install_date: datetime.datetime | None
    basis: str


def _add_months(moment: datetime.datetime, months: int) -> datetime.datetime:
    """Calendar-correct month addition, standard library only.

    No new dependency for this (hard rule 6): `dateutil.relativedelta` would
    be the obvious library, but `calendar.monthrange` does the one thing
    needed - clamping to the shorter month when the anniversary day doesn't
    exist there (e.g. Jan 31 + 1 month -> Feb 28) - without adding one.
    """
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def evaluate_level_3(
    *,
    install_job_id: str | None,
    install_date: datetime.datetime | None,
    as_of: datetime.datetime,
) -> Level3Result:
    """Evaluate level 3 for one canonical address at one point in time.

    `install_date`/`install_job_id` come from `knowledge.install_dates` for a
    canonical address - both `None` together when that table has no row for
    it, per its foreign key. `as_of` is the moment to evaluate against (the
    call's own time in production; a fixed instant in a test), never defaulted
    to "now" internally, so this stays deterministic and testable against
    historical fixtures rather than the wall clock.
    """
    if install_date is None:
        return Level3Result(
            verdict=Level3Verdict.NO_VERDICT,
            install_job_id=None,
            install_date=None,
            basis="no install date on file for this address",
        )

    expires_at = _add_months(install_date, LABOR_WARRANTY_MONTHS)
    if as_of <= expires_at:
        return Level3Result(
            verdict=Level3Verdict.COVERED,
            install_job_id=install_job_id,
            install_date=install_date,
            basis=(
                f"install on {install_date.date().isoformat()} "
                f"(job {install_job_id}) is within {LABOR_WARRANTY_MONTHS} months"
            ),
        )

    return Level3Result(
        verdict=Level3Verdict.NO_VERDICT,
        install_job_id=install_job_id,
        install_date=install_date,
        basis=(
            f"install on file ({install_date.date().isoformat()}, "
            f"job {install_job_id}) is more than {LABOR_WARRANTY_MONTHS} "
            f"months old"
        ),
    )
