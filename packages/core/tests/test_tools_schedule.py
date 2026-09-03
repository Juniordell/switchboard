"""`get_schedule`: role scoping, and the stale-job exclusion.

`as_of` is fixed by every test rather than taken from the clock, so what
counts as stale is a property of the fixture and not of the day the suite
happens to run.
"""

import datetime
import json
import logging
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from switchboard_core.tools.caller_role import CallerRole
from switchboard_core.tools.schedule import (
    ScheduleOutput,
    ScheduleRequest,
    get_schedule,
)

NY = ZoneInfo("America/New_York")
AS_OF = datetime.datetime(2026, 9, 3, 9, 0, tzinfo=NY)
WINDOW_END = AS_OF + datetime.timedelta(days=14)


def _call(session, **kwargs):
    request = ScheduleRequest(start=AS_OF, end=WINDOW_END, **kwargs)
    return get_schedule(request, call_id="call_1", session=session, as_of=AS_OF)


class TestRoleScoping:
    def test_a_homeowner_without_an_identity_cannot_even_ask(self) -> None:
        """The Triage boundary as a type error: no resolved customer, no
        request object, no query."""
        with pytest.raises(ValidationError, match="customer_id"):
            ScheduleRequest(start=AS_OF, end=WINDOW_END, role=CallerRole.HOMEOWNER)

    def test_a_property_manager_is_scoped_too(self) -> None:
        with pytest.raises(ValidationError, match="customer_id"):
            ScheduleRequest(
                start=AS_OF, end=WINDOW_END, role=CallerRole.PROPERTY_MANAGER
            )

    def test_an_internal_role_sees_the_whole_day(self, db_session) -> None:
        out = _call(db_session, role=CallerRole.OWNER)
        assert isinstance(out, ScheduleOutput)
        assert len(out.jobs) > 1
        assert len({j.customer_id for j in out.jobs}) > 1

    def test_a_homeowner_sees_only_their_own_jobs(self, db_session) -> None:
        everyone = _call(db_session, role=CallerRole.OWNER)
        target = everyone.jobs[0].customer_id

        theirs = _call(db_session, role=CallerRole.HOMEOWNER, customer_id=target)
        assert theirs.jobs
        assert {j.customer_id for j in theirs.jobs} == {target}
        assert len(theirs.jobs) < len(everyone.jobs)


class TestStaleJobsAreExcluded:
    def test_a_scheduled_job_in_the_past_is_never_returned(self, db_session) -> None:
        """38 of the 76 scheduled rows are abandoned. Asking from a date
        after them must not surface any as upcoming."""
        past = datetime.datetime(2026, 1, 1, tzinfo=NY)
        request = ScheduleRequest(start=past, end=WINDOW_END, role=CallerRole.OWNER)
        out = get_schedule(request, call_id="call_1", session=db_session, as_of=AS_OF)
        stale = [
            j
            for j in out.jobs
            if j.work_status == "scheduled" and j.scheduled_start < AS_OF
        ]
        assert stale == []

    def test_the_same_range_does_contain_past_non_scheduled_work(
        self, db_session
    ) -> None:
        """The exclusion is about abandoned `scheduled` rows, not about
        history - a completed job in the past is a real record."""
        past = datetime.datetime(2026, 1, 1, tzinfo=NY)
        request = ScheduleRequest(start=past, end=WINDOW_END, role=CallerRole.OWNER)
        out = get_schedule(request, call_id="call_1", session=db_session, as_of=AS_OF)
        assert any(j.scheduled_start < AS_OF for j in out.jobs)


class TestContract:
    def test_rows_are_counted_and_ordered(self, db_session) -> None:
        out = _call(db_session, role=CallerRole.OWNER)
        assert out.result_rows() == len(out.jobs)
        starts = [j.scheduled_start for j in out.jobs]
        assert starts == sorted(starts)

    def test_logs_as_a_service_tool(self, db_session, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            _call(db_session, role=CallerRole.OWNER)
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "get_schedule"
        assert record["agent"] == "Service"
        assert record["ok"] is True
