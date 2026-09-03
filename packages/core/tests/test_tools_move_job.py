"""`move_job`: a new slot for an existing job, without touching it.

The job itself is never mutated. The reschedule lives in `ops`, and
`source` comes out of every test here exactly as it went in - which is the
whole reason the overlay exists.
"""

import datetime

from sqlalchemy import text

from switchboard_core.tools import (
    BookJobRequest,
    MoveJobRequest,
    ToolError,
    book_job,
    move_job,
)

#: A real, future, scheduled job: job_number 5487, 2026-09-03 17:00 UTC.
JOB_ID = "job_21f9fe518d0b401ab04201534c33533c"
NEW_SLOT = datetime.datetime(2026, 10, 8, 14, 0, tzinfo=datetime.UTC)


class TestMoveJob:
    def test_it_records_where_the_job_was_and_where_it_went(
        self, write_session
    ) -> None:
        out = move_job(
            MoveJobRequest(
                job_id=JOB_ID,
                scheduled_start=NEW_SLOT,
                spoken_confirmation="yeah move it to the eighth",
            ),
            call_id="call_1",
            session=write_session,
        )
        assert out.scheduled_start == NEW_SLOT
        assert out.previous_start is not None
        assert out.previous_start != NEW_SLOT

        row = write_session.execute(
            text("SELECT old_values, new_values FROM ops.write_audit WHERE id = :i"),
            {"i": out.audit_id},
        ).one()
        assert row.old_values["scheduled_start"] == out.previous_start.isoformat()
        assert row.new_values["scheduled_start"] == NEW_SLOT.isoformat()

    def test_the_source_row_is_never_touched(self, write_session) -> None:
        before = write_session.execute(
            text("SELECT scheduled_start FROM source.jobs WHERE id = :i"),
            {"i": JOB_ID},
        ).scalar_one()

        move_job(
            MoveJobRequest(
                job_id=JOB_ID,
                scheduled_start=NEW_SLOT,
                spoken_confirmation="move it",
            ),
            call_id="call_1",
            session=write_session,
        )

        after = write_session.execute(
            text("SELECT scheduled_start FROM source.jobs WHERE id = :i"),
            {"i": JOB_ID},
        ).scalar_one()
        assert after == before

    def test_moving_twice_keeps_one_overlay_row(self, write_session) -> None:
        """The latest move wins; the audit log keeps both steps."""
        later = NEW_SLOT + datetime.timedelta(days=1)
        move_job(
            MoveJobRequest(
                job_id=JOB_ID, scheduled_start=NEW_SLOT, spoken_confirmation="ok"
            ),
            call_id="call_1",
            session=write_session,
        )
        move_job(
            MoveJobRequest(
                job_id=JOB_ID, scheduled_start=later, spoken_confirmation="ok"
            ),
            call_id="call_1",
            session=write_session,
        )

        rows = write_session.execute(
            text("SELECT scheduled_start FROM ops.job_reschedules WHERE job_id = :i"),
            {"i": JOB_ID},
        ).all()
        assert len(rows) == 1
        assert rows[0].scheduled_start == later

        audited = write_session.execute(
            text("SELECT count(*) FROM ops.write_audit WHERE job_id = :i"),
            {"i": JOB_ID},
        ).scalar_one()
        assert audited == 2

    def test_a_retry_of_the_same_move_is_a_replay(self, write_session) -> None:
        first = move_job(
            MoveJobRequest(
                job_id=JOB_ID, scheduled_start=NEW_SLOT, spoken_confirmation="ok"
            ),
            call_id="call_1",
            session=write_session,
        )
        second = move_job(
            MoveJobRequest(
                job_id=JOB_ID, scheduled_start=NEW_SLOT, spoken_confirmation="ok"
            ),
            call_id="call_1",
            session=write_session,
        )
        assert first.replayed is False
        assert second.replayed is True

    def test_an_unknown_job_is_a_typed_error(self, write_session) -> None:
        out = move_job(
            MoveJobRequest(
                job_id="job_does_not_exist",
                scheduled_start=NEW_SLOT,
                spoken_confirmation="ok",
            ),
            call_id="call_1",
            session=write_session,
        )
        assert isinstance(out, ToolError)
        assert out.error == "JobNotFoundError"

    def test_an_agent_booking_can_be_moved_too(self, write_session) -> None:
        """The overlay does not care which table the job came from."""
        booked = book_job(
            BookJobRequest(
                customer_id="cus_test",
                scheduled_start=NEW_SLOT,
                description="new install quote",
                display_address="9 Overlay Ln",
                spoken_confirmation="yes",
            ),
            call_id="call_1",
            session=write_session,
        )
        moved = move_job(
            MoveJobRequest(
                job_id=booked.job_id,
                scheduled_start=NEW_SLOT + datetime.timedelta(days=2),
                spoken_confirmation="actually the tenth",
            ),
            call_id="call_1",
            session=write_session,
        )
        assert not isinstance(moved, ToolError)
        assert moved.previous_start == NEW_SLOT
