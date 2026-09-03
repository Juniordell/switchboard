"""`identify_caller_role`: the four roles, and the refusal.

No database: the tool reads nothing, and these tests pass no session, which
is itself the assertion that `kind=logic` is true of the implementation and
not just of the table in `docs/AGENTS.md`.
"""

import json
import logging

from switchboard_core.tools.caller_role import (
    CallerRole,
    CallerRoleRequest,
    identify_caller_role,
)


def _role(utterance: str, **record) -> object:
    return identify_caller_role(
        CallerRoleRequest(utterance=utterance, **record), call_id="call_1"
    )


class TestNoDataAccess:
    def test_takes_no_session(self) -> None:
        out = _role("my house is not cooling")
        assert out.role is CallerRole.HOMEOWNER


class TestTheFourRoles:
    def test_homeowner(self) -> None:
        out = _role("hi, my house is not cooling and I live here")
        assert out.role is CallerRole.HOMEOWNER
        assert out.must_ask is False

    def test_property_manager(self) -> None:
        out = _role("I'm the property manager, one of my tenants has no AC")
        assert out.role is CallerRole.PROPERTY_MANAGER
        assert out.must_ask is False

    def test_tech(self) -> None:
        out = _role("hey it's Marco, I'm a tech, I'm on site for the Ibis job")
        assert out.role is CallerRole.TECH
        assert out.must_ask is False

    def test_owner(self) -> None:
        out = _role("this is Ray, I own the company, where are my techs today")
        assert out.role is CallerRole.OWNER
        assert out.must_ask is False


class TestOwnerIsNotHomeowner:
    """`owner` is an internal role at the company. Confusing it with a
    homeowner hands company-level questions to a customer."""

    def test_owning_the_house_is_a_homeowner(self) -> None:
        assert _role("I own the house on Marlin Cay").role is CallerRole.HOMEOWNER

    def test_owning_the_company_is_the_owner(self) -> None:
        assert _role("I own the business, this is Ray").role is CallerRole.OWNER


class TestRefusesWhenSignalsDisagree:
    def test_an_utterance_with_no_signal_asks(self) -> None:
        out = _role("hi, yeah, hello? can you hear me")
        assert out.role is None
        assert out.must_ask is True
        assert out.confidence == "low"

    def test_conflicting_signals_ask_rather_than_pick(self) -> None:
        out = _role("it's my house but I also manage the building next door")
        assert out.must_ask is True
        assert out.confidence == "low"

    def test_the_basis_says_what_fired(self) -> None:
        out = _role("my tenants have no AC", company="Starfish", job_count=145)
        assert out.basis
        assert any("tenant" in b for b in out.basis)


class TestKindIsNeverTrustedAlone:
    def test_kind_alone_decides_nothing(self) -> None:
        """A `homeowner` kind with a 145-job portfolio is one of the 48
        mislabelled rows; the record's job count outweighs the label."""
        out = _role(
            "calling about the AC",
            customer_kind="homeowner",
            company="Starfish Hospitality",
            job_count=145,
        )
        assert out.role is CallerRole.PROPERTY_MANAGER

    def test_kind_is_reported_but_not_scored(self) -> None:
        out = _role("my house is warm", customer_kind="business")
        assert any("not scored" in b for b in out.basis)
        assert out.role is CallerRole.HOMEOWNER


class TestContract:
    def test_logs_as_a_triage_tool_with_one_row(self, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            _role("my house is not cooling")
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "identify_caller_role"
        assert record["agent"] == "Triage"
        assert record["result_rows"] == 1
        assert record["ok"] is True
