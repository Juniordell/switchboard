"""The write overlay reaching the read path.

Without this, a caller books an appointment and is told thirty seconds
later, in the same call, that they have nothing scheduled. `get_schedule`
unions `source.jobs` with `ops.booked_jobs` and applies
`ops.job_reschedules`, and these tests are what says so.
"""

import datetime

from sqlalchemy import text

from switchboard_core.tools import (
    BookJobRequest,
    MoveJobRequest,
    ScheduleRequest,
    book_job,
    get_schedule,
    move_job,
)
from switchboard_core.tools.caller_role import CallerRole

AS_OF = datetime.datetime(2026, 9, 3, 9, 0, tzinfo=datetime.UTC)
SLOT = datetime.datetime(2026, 10, 1, 14, 0, tzinfo=datetime.UTC)
CUSTOMER = "cus_overlay_test"

#: A real, future, scheduled source job: job_number 5487.
SOURCE_JOB = "job_21f9fe518d0b401ab04201534c33533c"


def _schedule(session, *, customer_id=None, role=CallerRole.OWNER, days=90):
    return get_schedule(
        ScheduleRequest(
            start=AS_OF,
            end=AS_OF + datetime.timedelta(days=days),
            role=role,
            customer_id=customer_id,
        ),
        call_id="call_1",
        session=session,
        as_of=AS_OF,
    )


class TestABookingIsVisibleImmediately:
    def test_the_caller_can_be_told_what_they_just_booked(self, write_session) -> None:
        booked = book_job(
            BookJobRequest(
                customer_id=CUSTOMER,
                scheduled_start=SLOT,
                description="no cooling upstairs",
                display_address="1 Overlay St",
                spoken_confirmation="yes, the first at two",
            ),
            call_id="call_1",
            session=write_session,
        )

        out = _schedule(write_session, customer_id=CUSTOMER)
        assert [j.job_id for j in out.jobs] == [booked.job_id]
        assert out.jobs[0].scheduled_start == SLOT
        assert out.jobs[0].agent_booked is True

    def test_an_agent_booking_has_no_job_number_to_speak(self, write_session) -> None:
        """Job numbers come from the field service system. Inventing one
        risks colliding with a real number the way invoice_number already
        collides with job_number in this dataset."""
        book_job(
            BookJobRequest(
                customer_id=CUSTOMER,
                scheduled_start=SLOT,
                description="x",
                display_address="1 Overlay St",
                spoken_confirmation="yes",
            ),
            call_id="call_1",
            session=write_session,
        )
        out = _schedule(write_session, customer_id=CUSTOMER)
        assert out.jobs[0].job_number is None

    def test_role_scoping_still_applies_to_bookings(self, write_session) -> None:
        book_job(
            BookJobRequest(
                customer_id=CUSTOMER,
                scheduled_start=SLOT,
                description="x",
                display_address="1 Overlay St",
                spoken_confirmation="yes",
            ),
            call_id="call_1",
            session=write_session,
        )
        someone_else = _schedule(write_session, customer_id="cus_somebody_else")
        assert all(j.customer_id != CUSTOMER for j in someone_else.jobs)


class TestAMoveIsVisibleImmediately:
    def test_the_schedule_answers_with_the_new_time(self, write_session) -> None:
        before = [j for j in _schedule(write_session).jobs if j.job_id == SOURCE_JOB]
        assert before, "fixture job should be in the window to begin with"
        original = before[0].scheduled_start

        new_slot = original + datetime.timedelta(days=7)
        move_job(
            MoveJobRequest(
                job_id=SOURCE_JOB,
                scheduled_start=new_slot,
                spoken_confirmation="a week later please",
            ),
            call_id="call_1",
            session=write_session,
        )

        after = [j for j in _schedule(write_session).jobs if j.job_id == SOURCE_JOB]
        assert len(after) == 1
        assert after[0].scheduled_start == new_slot
        assert after[0].rescheduled is True
        assert after[0].agent_booked is False

    def test_the_job_appears_once_not_twice(self, write_session) -> None:
        """A left join, not a union, so a moved job does not show up as
        both its old self and its new one."""
        move_job(
            MoveJobRequest(
                job_id=SOURCE_JOB,
                scheduled_start=SLOT,
                spoken_confirmation="ok",
            ),
            call_id="call_1",
            session=write_session,
        )
        matches = [j for j in _schedule(write_session).jobs if j.job_id == SOURCE_JOB]
        assert len(matches) == 1

    def test_moving_a_stale_job_into_the_future_revives_it(self, write_session) -> None:
        """A stale row is one whose start has passed while still marked
        scheduled. Moving it forward is precisely what un-abandons it, so
        staleness is judged on the effective start, not the loaded one.
        """
        stale = write_session.execute(
            text(
                "SELECT id FROM source.jobs WHERE work_status = 'scheduled' "
                "AND scheduled_start < :as_of ORDER BY scheduled_start LIMIT 1"
            ),
            {"as_of": AS_OF},
        ).scalar_one()

        assert not any(j.job_id == stale for j in _schedule(write_session).jobs)

        move_job(
            MoveJobRequest(
                job_id=stale,
                scheduled_start=SLOT,
                spoken_confirmation="reschedule it",
            ),
            call_id="call_1",
            session=write_session,
        )

        revived = [j for j in _schedule(write_session).jobs if j.job_id == stale]
        assert len(revived) == 1
        assert revived[0].scheduled_start == SLOT
