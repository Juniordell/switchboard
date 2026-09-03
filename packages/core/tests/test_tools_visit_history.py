"""`get_visit_history` as a tool: rows out, no prose, ordered."""

import json
import logging

from switchboard_core.tools.visit_history import (
    VisitHistoryOutput,
    VisitHistoryRequest,
    get_visit_history,
)

#: 8 real jobs at one canonical address - enough to prove ordering.
CANONICAL_ID = "cadr_2fa76af76a2a53d2909332ef8c0dba59"


class TestContract:
    def test_returns_rows_most_recent_first(self, db_session) -> None:
        out = get_visit_history(
            VisitHistoryRequest(canonical_id=CANONICAL_ID),
            call_id="call_1",
            session=db_session,
        )
        assert isinstance(out, VisitHistoryOutput)
        assert len(out.visits) >= 4
        dates = [v.service_date for v in out.visits]
        assert dates == sorted(dates, reverse=True)

    def test_rows_are_counted_as_rows(self, db_session) -> None:
        out = get_visit_history(
            VisitHistoryRequest(canonical_id=CANONICAL_ID),
            call_id="call_1",
            session=db_session,
        )
        assert out.result_rows() == len(out.visits)

    def test_an_address_with_no_jobs_returns_no_visits_not_an_error(
        self, db_session
    ) -> None:
        out = get_visit_history(
            VisitHistoryRequest(canonical_id="cadr_does_not_exist"),
            call_id="call_1",
            session=db_session,
        )
        assert out.visits == []
        assert out.result_rows() == 0

    def test_carries_job_numbers_and_never_invents_a_summary(self, db_session) -> None:
        """The tool returns structured rows; the agent summarises at
        speaking time. Nothing here generates a sentence."""
        out = get_visit_history(
            VisitHistoryRequest(canonical_id=CANONICAL_ID),
            call_id="call_1",
            session=db_session,
        )
        first = out.visits[0]
        assert first.job_number
        assert isinstance(first.techs, list)
        assert isinstance(first.invoice_numbers, list)
        assert not hasattr(first, "summary")

    def test_logs_as_a_service_tool(self, db_session, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            get_visit_history(
                VisitHistoryRequest(canonical_id=CANONICAL_ID),
                call_id="call_2",
                session=db_session,
            )
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "get_visit_history"
        assert record["agent"] == "Service"
        assert record["result_rows"] >= 4
        assert record["ok"] is True
        assert record["args"] == {"canonical_id": CANONICAL_ID}
