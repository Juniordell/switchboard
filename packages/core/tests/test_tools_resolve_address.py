"""`resolve_address` as a tool: the contract, not the matching.

The normalisation and scoring are already covered in
`test_resolve_address.py` against 54 cases. What matters here is that the
tool wraps them without changing the verdict, counts candidates as rows,
and stays inside the Triage boundary.
"""

import json
import logging

from switchboard_core.tools.contract import ToolError
from switchboard_core.tools.resolve_address import (
    ResolveAddressOutput,
    ResolveAddressRequest,
    resolve_address,
)

HARD_REQUIREMENT = "eighty nine harbor light shores"


class TestContract:
    def test_returns_candidates_and_counts_them_as_rows(self, db_session) -> None:
        out = resolve_address(
            ResolveAddressRequest(spoken_address=HARD_REQUIREMENT),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, ResolveAddressOutput)
        assert out.address.candidates
        assert out.result_rows() == len(out.address.candidates)
        assert "Harborlight Shores" in out.address.candidates[0].display_address

    def test_returns_canonical_ids_never_a_source_address_id(self, db_session) -> None:
        out = resolve_address(
            ResolveAddressRequest(spoken_address=HARD_REQUIREMENT),
            call_id="call_1",
            session=db_session,
        )
        assert all(c.canonical_id.startswith("cadr_") for c in out.address.candidates)

    def test_an_unusable_street_is_not_an_error(self, db_session) -> None:
        """No candidates and `must_ask=True` is an answer the agent can act
        on. A ToolError here would be the tool inventing a failure."""
        out = resolve_address(
            ResolveAddressRequest(spoken_address="   "),
            call_id="call_1",
            session=db_session,
        )
        assert not isinstance(out, ToolError)
        assert out.address.candidates == []
        assert out.address.must_ask is True
        assert out.result_rows() == 0

    def test_logs_as_the_triage_tool_it_is(self, db_session, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            resolve_address(
                ResolveAddressRequest(spoken_address=HARD_REQUIREMENT),
                call_id="call_7",
                session=db_session,
            )
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "resolve_address"
        assert record["agent"] == "Triage"
        assert record["call_id"] == "call_7"
        assert record["ok"] is True
        assert record["args"] == {"spoken_address": HARD_REQUIREMENT}
        assert record["result_rows"] >= 1
