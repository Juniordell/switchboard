"""`get_customer_balance` as a tool: cents, per customer, zero is an answer."""

import json
import logging

from switchboard_core.tools.customer_balance import (
    CustomerBalanceOutput,
    CustomerBalanceRequest,
    get_customer_balance,
)

#: A real customer carrying a real outstanding balance across 4 jobs.
CUSTOMER_ID = "cus_93de03daac11405980a515166b7b97cf"


class TestContract:
    def test_returns_cents_and_a_job_count(self, db_session) -> None:
        out = get_customer_balance(
            CustomerBalanceRequest(customer_id=CUSTOMER_ID),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, CustomerBalanceOutput)
        assert out.balance.outstanding_balance > 0
        assert isinstance(out.balance.outstanding_balance, int)
        assert out.balance.job_count == 4

    def test_a_single_answer_counts_as_one_row(self, db_session) -> None:
        out = get_customer_balance(
            CustomerBalanceRequest(customer_id=CUSTOMER_ID),
            call_id="call_1",
            session=db_session,
        )
        assert out.result_rows() == 1

    def test_an_unknown_customer_is_zero_not_an_error(self, db_session) -> None:
        """`job_count` is what separates "owes nothing" from "no history" -
        the agent needs that difference to answer honestly."""
        out = get_customer_balance(
            CustomerBalanceRequest(customer_id="cus_does_not_exist"),
            call_id="call_1",
            session=db_session,
        )
        assert out.balance.outstanding_balance == 0
        assert out.balance.job_count == 0

    def test_logs_one_row(self, db_session, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            get_customer_balance(
                CustomerBalanceRequest(customer_id=CUSTOMER_ID),
                call_id="call_3",
                session=db_session,
            )
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "get_customer_balance"
        assert record["agent"] == "Service"
        assert record["result_rows"] == 1
        assert record["ok"] is True
