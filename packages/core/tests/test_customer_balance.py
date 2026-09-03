"""`get_customer_balance` against the live database."""

from sqlalchemy import text

from switchboard_core.knowledge import get_customer_balance


def test_a_real_customer_with_a_positive_balance(db_session) -> None:
    """Josie McGuire, 4 jobs, $42,017.82 owed across them."""
    balance = get_customer_balance(db_session, "cus_93de03daac11405980a515166b7b97cf")
    assert balance.outstanding_balance == 4201782
    assert balance.job_count == 4


def test_matches_summing_invoice_due_amount_independently(db_session) -> None:
    """job.outstanding_balance is trusted to already equal
    SUM(invoice.due_amount) per job (verified for every multi-invoice job
    while investigating this task) - this test recomputes the customer total
    the other way, through invoices, and checks the two agree.
    """
    balance = get_customer_balance(db_session, "cus_93de03daac11405980a515166b7b97cf")
    via_invoices = db_session.execute(
        text(
            "SELECT COALESCE(sum(i.due_amount), 0) FROM source.invoices i "
            "JOIN source.jobs j ON j.id = i.job_id "
            "WHERE j.customer_id = :c"
        ),
        {"c": "cus_93de03daac11405980a515166b7b97cf"},
    ).scalar_one()
    assert balance.outstanding_balance == via_invoices


def test_a_customer_with_jobs_and_zero_balance(db_session) -> None:
    balance = get_customer_balance(db_session, "cus_0cd443839b0a42b7a14fd0342433694e")
    assert balance.outstanding_balance == 0
    assert balance.job_count == 1


def test_an_unknown_customer_id_returns_zero_not_an_error(db_session) -> None:
    balance = get_customer_balance(db_session, "cus_does_not_exist")
    assert balance.outstanding_balance == 0
    assert balance.job_count == 0
