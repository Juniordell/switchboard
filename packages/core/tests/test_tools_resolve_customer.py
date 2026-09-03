"""`resolve_customer`: the candidate shape, and when it refuses to guess.

Every fixture is a real customer found by querying the loaded database, not
an invented name.
"""

import json
import logging

import pytest
from pydantic import ValidationError

from switchboard_core.tools.resolve_customer import (
    ResolveCustomerOutput,
    ResolveCustomerRequest,
    resolve_customer,
)

#: A unique full name: nobody else is called this, and it is nobody's prefix.
UNIQUE_NAME = "Serena Weeks"
UNIQUE_ID = "cus_8ef5a202ca904cb8a87c0b263e9dcb27"

#: Two different customers carry this exact name in the real data.
DUPLICATED_NAME = "Starfish Hospitality"

#: A name that is also the start of two longer ones.
PREFIX_NAME = "Lighthouse"


class TestConfidentResolution:
    def test_a_unique_name_resolves_without_asking(self, db_session) -> None:
        out = resolve_customer(
            ResolveCustomerRequest(name=UNIQUE_NAME),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, ResolveCustomerOutput)
        assert out.customer.must_ask is False
        assert out.customer.candidates[0].customer_id == UNIQUE_ID
        assert out.customer.candidates[0].score == pytest.approx(1.0)

    def test_candidates_are_counted_as_rows(self, db_session) -> None:
        out = resolve_customer(
            ResolveCustomerRequest(name=UNIQUE_NAME),
            call_id="call_1",
            session=db_session,
        )
        assert out.result_rows() == len(out.customer.candidates)


class TestRefusesToGuess:
    def test_two_customers_with_the_same_name_must_be_asked_about(
        self, db_session
    ) -> None:
        out = resolve_customer(
            ResolveCustomerRequest(name=DUPLICATED_NAME),
            call_id="call_1",
            session=db_session,
        )
        top_two = out.customer.candidates[:2]
        assert [c.display_name for c in top_two] == [DUPLICATED_NAME] * 2
        assert len({c.customer_id for c in top_two}) == 2
        assert out.customer.must_ask is True

    def test_an_unfinished_name_must_be_asked_about(self, db_session) -> None:
        """Trigram similarity scores "Lighthouse" 1.0 against the customer
        of that exact name and ~0.48 against "Lighthouse Hospitality" - a
        gap the numeric rule calls decisive and a caller would not. More
        than one name starting with what was said is an ask.
        """
        out = resolve_customer(
            ResolveCustomerRequest(name=PREFIX_NAME),
            call_id="call_1",
            session=db_session,
        )
        assert out.customer.candidates[0].score == pytest.approx(1.0)
        assert out.customer.must_ask is True

    def test_a_name_nobody_has_must_be_asked_about(self, db_session) -> None:
        out = resolve_customer(
            ResolveCustomerRequest(name="Zzqxjklw Nonesuch"),
            call_id="call_1",
            session=db_session,
        )
        assert out.customer.must_ask is True


class TestScope:
    def test_a_request_with_nothing_to_go_on_cannot_be_built(self) -> None:
        with pytest.raises(ValidationError):
            ResolveCustomerRequest()

    def test_returns_no_job_invoice_or_schedule_data(self, db_session) -> None:
        """The Triage boundary, asserted on the shape rather than promised
        in a docstring."""
        out = resolve_customer(
            ResolveCustomerRequest(name=UNIQUE_NAME),
            call_id="call_1",
            session=db_session,
        )
        fields = set(type(out.customer.candidates[0]).model_fields)
        assert fields == {"customer_id", "display_name", "kind", "job_count", "score"}

    def test_logs_as_a_triage_tool(self, db_session, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            resolve_customer(
                ResolveCustomerRequest(name=UNIQUE_NAME),
                call_id="call_8",
                session=db_session,
            )
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "resolve_customer"
        assert record["agent"] == "Triage"
        assert record["ok"] is True
