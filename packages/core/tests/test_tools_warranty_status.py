"""`get_warranty_status` as a tool: never a bare yes/no, and `as_of` is
injected rather than invented.

The precedence rule itself is covered by 38 tests in
`test_warranty_status.py` and `test_warranty_level_3.py`. This file asserts
the tool contract around it.
"""

import datetime
import json
import logging

import pytest

from switchboard_core.tools.warranty_status import (
    WarrantyStatusOutput,
    WarrantyStatusRequest,
    get_warranty_status,
)

CANONICAL_ID = "cadr_2fa76af76a2a53d2909332ef8c0dba59"
AS_OF = datetime.datetime(2026, 9, 3, tzinfo=datetime.UTC)


class TestContract:
    def test_always_returns_a_level_and_a_basis(self, db_session) -> None:
        out = get_warranty_status(
            WarrantyStatusRequest(canonical_id=CANONICAL_ID),
            call_id="call_1",
            session=db_session,
            as_of=AS_OF,
        )
        assert isinstance(out, WarrantyStatusOutput)
        assert 1 <= out.warranty.level <= 6
        assert out.warranty.basis
        assert out.warranty.covered in ("yes", "no", "unknown")
        assert out.warranty.confidence

    def test_covered_is_never_a_bare_bool(self, db_session) -> None:
        out = get_warranty_status(
            WarrantyStatusRequest(canonical_id=CANONICAL_ID),
            call_id="call_1",
            session=db_session,
            as_of=AS_OF,
        )
        assert not isinstance(out.warranty.covered, bool)

    def test_as_of_is_echoed_so_the_answer_can_be_audited(self, db_session) -> None:
        out = get_warranty_status(
            WarrantyStatusRequest(canonical_id=CANONICAL_ID),
            call_id="call_1",
            session=db_session,
            as_of=AS_OF,
        )
        assert out.as_of == AS_OF

    def test_as_of_cannot_be_omitted(self, db_session) -> None:
        """The rule never defaults to "now" internally; the tool does not
        relax that at its boundary."""
        with pytest.raises(TypeError, match="as_of"):
            get_warranty_status(
                WarrantyStatusRequest(canonical_id=CANONICAL_ID),
                call_id="call_1",
                session=db_session,
            )

    def test_as_of_is_not_an_llm_visible_argument(self) -> None:
        """It is injected by the runtime, so it must not appear in the
        request schema an agent fills in."""
        assert "as_of" not in WarrantyStatusRequest.model_fields

    def test_logs_one_row_as_a_service_tool(self, db_session, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            get_warranty_status(
                WarrantyStatusRequest(canonical_id=CANONICAL_ID, equipment="condenser"),
                call_id="call_4",
                session=db_session,
                as_of=AS_OF,
            )
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "get_warranty_status"
        assert record["agent"] == "Service"
        assert record["result_rows"] == 1
        assert record["args"]["equipment"] == "condenser"
