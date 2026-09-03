"""The number-provenance case. This breaks CI, not review.

`docs/HARNESS.md`: every number the agent returns must trace to a row whose
`job_id` is the resolved job's. A job number must equal that job's
`job_number`; an invoice number must be in that job's invoice set; a number
that satisfies neither is a failure **even if the rest of the turn is
perfect and the number happens to sound right**.

Grading the tool sequence would not catch this. The failure that matters is
the *right* tool returning the *wrong* number, so these two cases execute
`get_visit_history` for real and read the row. They need no model, cost
nothing, and run in the ordinary suite on every commit.

The worst case is `job_28e341b2`: job number **3611**, at Starfish
Hospitality's 45 Saltbush Bluff Ct — while invoice **3611** belongs to
Charlene Whitaker at 74 Oleander Key St, who is *also* an Osprey
Hospitality account, the same company as the other fixture's customer.
Anything that joins on the number instead of `job_id` reads Charlene
Whitaker's invoice to Starfish Hospitality, and every intermediate step
looks correct.

Each case also asserts the trap is **still a trap** - that the colliding
invoice number really does belong to somebody else. Without that, a change
in the data could make these tests pass by having nothing left to catch.
"""

import pathlib

import pytest
import yaml
from sqlalchemy import text

from switchboard_core.knowledge.job_address import job_canonical_id
from switchboard_core.knowledge.visit_history import get_visit_history

GOLDEN = pathlib.Path(__file__).parent / "golden" / "tools.yaml"


def _provenance_cases() -> list[dict]:
    cases = yaml.safe_load(GOLDEN.read_text())["cases"]
    return [c for c in cases if c.get("asserts") == "number_provenance"]


PROVENANCE_CASES = _provenance_cases()


def test_the_golden_set_still_carries_both_fixtures() -> None:
    assert {c["id"] for c in PROVENANCE_CASES} == {
        "provenance_allamanda",
        "provenance_saltbush",
    }


@pytest.fixture(params=PROVENANCE_CASES, ids=lambda c: c["id"])
def case(request) -> dict:
    return request.param


@pytest.fixture
def visit(db_session, case) -> object:
    """The row `get_visit_history` returns for the fixture's job - reached
    the way the agent reaches it, through the canonical address."""
    job_id = case["fixture"]["job_id"]
    address = db_session.execute(
        text(
            "SELECT address_street, address_street_line_2, address_zip "
            "FROM source.jobs WHERE id = :j"
        ),
        {"j": job_id},
    ).one()
    canonical_id = job_canonical_id(
        address.address_street, address.address_street_line_2, address.address_zip
    )
    assert canonical_id, f"{job_id} must resolve to a canonical address"

    rows = [
        v for v in get_visit_history(db_session, canonical_id) if v.job_id == job_id
    ]
    assert len(rows) == 1, f"expected exactly one row for {job_id}, got {len(rows)}"
    return rows[0]


class TestTheTrapIsStillATrap:
    def test_the_colliding_invoice_belongs_to_someone_else(
        self, db_session, case
    ) -> None:
        """If this ever stops being true, the tests below stop proving
        anything and would pass for the wrong reason."""
        fixture = case["fixture"]
        owner = db_session.execute(
            text("SELECT i.job_id FROM source.invoices i WHERE i.invoice_number = :n"),
            {"n": fixture["trap_invoice_number"]},
        ).scalar_one()
        assert owner != fixture["job_id"], (
            f"invoice {fixture['trap_invoice_number']} now belongs to the "
            f"fixture's own job; the collision this case exists to catch is gone"
        )

    def test_the_trap_number_equals_this_job_s_job_number(self, case) -> None:
        """The whole point: the same digits are this job's number and a
        different customer's invoice number."""
        fixture = case["fixture"]
        assert fixture["trap_invoice_number"] == fixture["correct_job_number"]


class TestEveryNumberTracesToTheResolvedJob:
    def test_the_job_number_is_this_job_s_own(self, visit, case) -> None:
        assert visit.job_number == case["fixture"]["correct_job_number"]

    def test_the_invoice_numbers_are_exactly_this_job_s(self, visit, case) -> None:
        assert sorted(visit.invoice_numbers) == sorted(
            case["fixture"]["correct_invoice_numbers"]
        )

    def test_the_other_customer_s_invoice_never_appears(self, visit, case) -> None:
        """The failure this case exists for: the right tool, the right job,
        and a number belonging to somebody else."""
        trap = case["fixture"]["trap_invoice_number"]
        assert trap not in visit.invoice_numbers, (
            f"invoice {trap} belongs to {case['fixture']['trap_belongs_to']} "
            f"and was returned as this job's"
        )

    def test_no_returned_number_is_unattributable(self, db_session, visit) -> None:
        """Stated as HARNESS.md states it: a number that is neither this
        job's job_number nor one of its invoice numbers is a failure."""
        own_invoices = set(
            db_session.execute(
                text("SELECT invoice_number FROM source.invoices WHERE job_id = :j"),
                {"j": visit.job_id},
            ).scalars()
        )
        for number in visit.invoice_numbers:
            assert number in own_invoices, (
                f"invoice number {number} does not belong to job {visit.job_id}"
            )
