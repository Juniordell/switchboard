"""The booking task group: collect, confirm, write - and the step-back.

What matters here is what has *not* happened yet. Every path short of an
explicit spoken confirmation must leave the database untouched, and these
tests assert that against the real `ops` tables rather than against the
task's own state.

`AgentTask` wants a running loop even to construct, so each scenario runs
inside one `asyncio.run`. That is also why there is no `pytest-asyncio`
here: a test dependency for four `await`s is not a trade worth making.
"""

import asyncio
import datetime

from sqlalchemy import text

from switchboard_agent.booking import BookingTask

SLOT = "2026-12-03T14:00:00+00:00"
CALL_ID = "call_booking_test"


def _task() -> BookingTask:
    return BookingTask(
        call_id=CALL_ID,
        customer_id="cus_test",
        canonical_id="cadr_test",
        description="no cooling upstairs",
        display_address="1 Test St",
    )


def _rows(session) -> int:
    return session.execute(
        text("SELECT count(*) FROM ops.booked_jobs WHERE call_id = :c"),
        {"c": CALL_ID},
    ).scalar_one()


class TestCollecting:
    def test_a_proposed_slot_is_held_not_written(self, db_session) -> None:
        async def scenario():
            task = _task()
            await task.propose_slot(SLOT)
            return task.slot

        held = asyncio.run(scenario())
        assert held == datetime.datetime.fromisoformat(SLOT)
        assert _rows(db_session) == 0

    def test_an_unreadable_time_is_refused(self) -> None:
        async def scenario():
            task = _task()
            answer = await task.propose_slot("sometime thursday-ish")
            return answer, task.slot

        answer, slot = asyncio.run(scenario())
        assert slot is None
        assert "not a time" in answer


class TestTheStepBackPath:
    def test_changing_the_slot_clears_it_and_writes_nothing(self, db_session) -> None:
        """The reason this is a task group at all: a caller changes their
        mind mid-booking, and an agent that has already written is an agent
        apologising."""

        async def scenario():
            task = _task()
            await task.propose_slot(SLOT)
            answer = await task.change_the_slot()
            return answer, task.slot

        answer, slot = asyncio.run(scenario())
        assert slot is None
        assert "nothing was written" in answer
        assert _rows(db_session) == 0

    def test_a_second_slot_can_be_proposed_after_a_change(self) -> None:
        later = "2026-12-05T10:00:00+00:00"

        async def scenario():
            task = _task()
            await task.propose_slot(SLOT)
            await task.change_the_slot()
            await task.propose_slot(later)
            return task.slot

        assert asyncio.run(scenario()) == datetime.datetime.fromisoformat(later)


class TestNothingIsWrittenWithoutConfirmation:
    def test_confirming_with_no_slot_held_writes_nothing(self, db_session) -> None:
        async def scenario():
            return await _task().confirm_booking(spoken_confirmation="yes go ahead")

        assert "no slot is held" in asyncio.run(scenario())
        assert _rows(db_session) == 0

    def test_an_empty_confirmation_writes_nothing(self, db_session) -> None:
        """The tool underneath requires the caller's own words; the task
        refuses before it ever gets there, so the caller hears a question
        rather than the agent hitting a validation error."""

        async def scenario():
            task = _task()
            await task.propose_slot(SLOT)
            return await task.confirm_booking(spoken_confirmation="   ")

        assert "not agreed in words" in asyncio.run(scenario())
        assert _rows(db_session) == 0
