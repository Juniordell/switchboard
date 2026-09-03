"""`find_availability`: the assumed working day, enforced.

Nothing here asserts that a particular tech is free on a particular day -
that changes with the data. What it asserts is that the rule in
`docs/SCOPE.md` is the rule the code follows.
"""

import datetime
import json
import logging
from zoneinfo import ZoneInfo

from switchboard_core.knowledge.availability import (
    SLOT_MINUTES,
    WORKDAY_END_HOUR,
    WORKDAY_START_HOUR,
)
from switchboard_core.tools.availability import (
    AvailabilityOutput,
    AvailabilityRequest,
    find_availability,
)

NY = ZoneInfo("America/New_York")
#: A Thursday.
AS_OF = datetime.datetime(2026, 9, 3, 9, 0, tzinfo=NY)


def _call(session, *, start=AS_OF, days=5, limit=10, as_of=AS_OF):
    request = AvailabilityRequest(
        start=start, end=start + datetime.timedelta(days=days), limit=limit
    )
    return find_availability(request, call_id="call_1", session=session, as_of=as_of)


class TestTheAssumedWorkingDay:
    def test_slots_are_inside_business_hours(self, db_session) -> None:
        out = _call(db_session)
        assert out.slots
        for slot in out.slots:
            local = slot.start.astimezone(NY)
            assert WORKDAY_START_HOUR <= local.hour < WORKDAY_END_HOUR
            assert slot.end.astimezone(NY).hour <= WORKDAY_END_HOUR

    def test_every_window_is_the_dominant_arrival_window(self, db_session) -> None:
        out = _call(db_session)
        for slot in out.slots:
            assert (slot.end - slot.start).total_seconds() == SLOT_MINUTES * 60

    def test_sunday_is_never_offered(self, db_session) -> None:
        """The 108 historical Sunday jobs are emergency work; a caller
        asking for one gets a human, not an invented slot."""
        sunday = datetime.datetime(2026, 9, 6, 0, 0, tzinfo=NY)
        out = _call(db_session, start=sunday, days=1, as_of=sunday)
        assert out.slots == []

    def test_a_slot_already_past_is_not_offered(self, db_session) -> None:
        """08:00 has gone by when the caller rings at 09:00."""
        out = _call(db_session)
        first = out.slots[0].start.astimezone(NY)
        assert first >= AS_OF

    def test_only_field_techs_are_offered(self, db_session) -> None:
        """Office staff and admin are not bookable; "Team Phone" is a
        shared line, not a person."""
        out = _call(db_session, limit=25)
        names = {s.tech_name for s in out.slots}
        assert "Team Phone" not in names


class TestShape:
    def test_one_row_per_window_not_one_per_tech(self, db_session) -> None:
        """15 techs free at 10:00 is one option to offer a caller, not 15."""
        out = _call(db_session, limit=10)
        starts = [s.start for s in out.slots]
        assert len(starts) == len(set(starts))

    def test_soonest_first(self, db_session) -> None:
        out = _call(db_session)
        starts = [s.start for s in out.slots]
        assert starts == sorted(starts)

    def test_the_caveat_travels_with_the_slots(self, db_session) -> None:
        """The agent cannot offer a time without having been handed the
        fact that the calendar behind it is assumed."""
        out = _call(db_session)
        assert isinstance(out, AvailabilityOutput)
        assert "assumption" in out.assumed_calendar

    def test_logs_as_a_dispatch_tool(self, db_session, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            _call(db_session)
        record = json.loads(caplog.records[0].message)
        assert record["tool"] == "find_availability"
        assert record["agent"] == "Dispatch"
        assert record["result_rows"] > 0
