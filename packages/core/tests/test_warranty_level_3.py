"""Level 3 of the warranty precedence rule. Pure-logic tests first; the real
no-install-date address is in `TestARealAddressWithNoInstallHistory`, which
needs the database.
"""

import datetime

import pytest
from sqlalchemy import text

from switchboard_core.knowledge import (
    LABOR_WARRANTY_MONTHS,
    Level3Verdict,
    evaluate_level_3,
)


def dt(iso: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(iso)


def test_the_verdict_type_cannot_express_a_denial() -> None:
    """The whole point of this module: "not covered" is not a value this
    enum can hold, so nothing downstream can be handed one by accident.
    """
    assert {member.value for member in Level3Verdict} == {"covered", "no_verdict"}
    assert not any(
        "not" in member.value or "no_cov" in member.value for member in Level3Verdict
    )


class TestNoInstallDateOnFile:
    """The exact case docs/DECISIONS.md locks down: 95.4% of addresses."""

    def test_verdict_is_no_verdict_not_a_denial(self) -> None:
        result = evaluate_level_3(
            install_job_id=None, install_date=None, as_of=dt("2026-09-03")
        )
        assert result.verdict is Level3Verdict.NO_VERDICT

    def test_basis_says_no_record_not_no_coverage(self) -> None:
        result = evaluate_level_3(
            install_job_id=None, install_date=None, as_of=dt("2026-09-03")
        )
        assert "no install date on file" in result.basis
        assert "not covered" not in result.basis
        assert "no coverage" not in result.basis


class TestARecentInstall:
    def test_the_day_of_install_is_covered(self) -> None:
        result = evaluate_level_3(
            install_job_id="job_x",
            install_date=dt("2026-01-15"),
            as_of=dt("2026-01-15"),
        )
        assert result.verdict is Level3Verdict.COVERED
        assert result.install_job_id == "job_x"

    def test_a_month_after_install_is_covered(self) -> None:
        result = evaluate_level_3(
            install_job_id="job_x",
            install_date=dt("2026-01-15"),
            as_of=dt("2026-02-15"),
        )
        assert result.verdict is Level3Verdict.COVERED

    def test_the_basis_cites_the_job_and_date(self) -> None:
        result = evaluate_level_3(
            install_job_id="job_dd4866dec6f44342b2f25bf506e4e9ff",
            install_date=dt("2026-03-02T22:13:00+00:00"),
            as_of=dt("2026-06-01T00:00:00+00:00"),
        )
        assert "2026-03-02" in result.basis
        assert "job_dd4866dec6f44342b2f25bf506e4e9ff" in result.basis


class TestTheTwelveMonthBoundary:
    def test_exactly_twelve_months_later_is_still_covered(self) -> None:
        result = evaluate_level_3(
            install_job_id="job_x",
            install_date=dt("2025-09-03"),
            as_of=dt("2026-09-03"),
        )
        assert result.verdict is Level3Verdict.COVERED

    def test_one_day_past_twelve_months_is_no_verdict_not_a_denial(self) -> None:
        """The case this task is really about, once an install date *is* on
        file: the boundary is crossed, and level 3 still does not say "not
        covered" - it says nothing, matching docs/DATA.md's "falls through."
        """
        result = evaluate_level_3(
            install_job_id="job_x",
            install_date=dt("2025-09-03"),
            as_of=dt("2026-09-04"),
        )
        assert result.verdict is Level3Verdict.NO_VERDICT
        assert result.install_date == dt("2025-09-03")
        assert "more than 12 months old" in result.basis

    def test_a_leap_year_february_anniversary_does_not_crash(self) -> None:
        """Feb 29 install + 12 months has no Feb 29 the next year; clamps to
        Feb 28 rather than raising.
        """
        result = evaluate_level_3(
            install_job_id="job_x",
            install_date=dt("2028-02-29"),
            as_of=dt("2029-02-28"),
        )
        assert result.verdict is Level3Verdict.COVERED


def test_labor_warranty_months_is_twelve() -> None:
    assert LABOR_WARRANTY_MONTHS == 12


@pytest.mark.parametrize(
    "as_of",
    ["2021-02-02", "2021-07-02", "2025-01-02"],
    ids=["13-months", "18-months", "5-years"],
)
def test_well_past_the_boundary_is_still_no_verdict_never_a_denial(
    as_of: str,
) -> None:
    """Parametrized specifically because "never a denial" has to hold no
    matter how old the install is - a 5-year-old install must not become
    "not covered" just because the gap is large and obvious.
    """
    result = evaluate_level_3(
        install_job_id="job_x", install_date=dt("2020-01-01"), as_of=dt(as_of)
    )
    assert result.verdict is Level3Verdict.NO_VERDICT


class TestARealAddressWithNoInstallHistory:
    """305 Orchid Pointe Cir (cadr_00053582119758b8806564a1475843e8): three
    real service visits in the data - a repair call, a rated job, a
    diagnostic dispatch - and zero install jobs. One of the 1,275 addresses
    (95.4%) `knowledge.install_dates` has no row for, because most equipment
    here predates the six-month export window, not because it was never
    installed or never covered.

    A system that let "no row in install_dates" leak into "not covered"
    would be wrong for the majority of this platform's warranty questions.
    This is the case docs/DECISIONS.md locks down.
    """

    CANONICAL_ID = "cadr_00053582119758b8806564a1475843e8"

    def test_the_address_genuinely_has_no_install_date_row(self, db_session) -> None:
        """Confirms the fixture is what it claims to be, not stale."""
        row = db_session.execute(
            text("SELECT 1 FROM knowledge.install_dates WHERE canonical_id = :c"),
            {"c": self.CANONICAL_ID},
        ).first()
        assert row is None

    def test_the_address_has_real_service_history(self, db_session) -> None:
        """Not an address with no history at all - one with history and no
        install visible in it, the case that actually matters.
        """
        count = db_session.execute(
            text(
                "SELECT count(*) FROM source.jobs "
                "WHERE address_street = '305 Orchid Pointe Cir' "
                "  AND address_zip = '33162'"
            )
        ).scalar_one()
        assert count == 3

    def test_level_3_returns_no_verdict_never_a_denial(self, db_session) -> None:
        row = db_session.execute(
            text(
                "SELECT install_job_id, install_date FROM knowledge.install_dates "
                "WHERE canonical_id = :c"
            ),
            {"c": self.CANONICAL_ID},
        ).first()
        install_job_id = row.install_job_id if row else None
        install_date = row.install_date if row else None

        result = evaluate_level_3(
            install_job_id=install_job_id,
            install_date=install_date,
            as_of=datetime.datetime(2026, 9, 3, tzinfo=datetime.UTC),
        )

        assert result.verdict is Level3Verdict.NO_VERDICT
        assert result.verdict is not Level3Verdict.COVERED
        # The type itself has no member spelling "not covered" - see
        # test_the_verdict_type_cannot_express_a_denial - so there is no
        # third value this assertion needs to rule out.
        assert "no install date on file" in result.basis
