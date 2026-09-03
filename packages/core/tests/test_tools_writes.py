"""The write machinery: the key, the audit row, and the retry that does not
book twice.

Every test writes inside a SAVEPOINT (`write_session`) and rolls it back.
The one exception is the NOTIFY test, which has to commit for Postgres to
deliver anything at all, and cleans up after itself.
"""

import datetime
import json

import pytest
from sqlalchemy import text

from switchboard_core.db.session import create_db_engine
from switchboard_core.tools import BookJobRequest, book_job
from switchboard_core.tools.writes import derived_id, idempotency_key

SLOT = datetime.datetime(2026, 10, 1, 14, 0, tzinfo=datetime.UTC)


def _request(**overrides) -> BookJobRequest:
    fields = {
        "customer_id": "cus_test",
        "scheduled_start": SLOT,
        "description": "no cooling upstairs",
        "display_address": "1 Test St",
        "spoken_confirmation": "yes, Thursday at two works",
    }
    return BookJobRequest(**{**fields, **overrides})


class TestTheKey:
    def test_the_same_parts_give_the_same_key(self) -> None:
        assert idempotency_key("a", "b") == idempotency_key("a", "b")

    def test_different_parts_give_different_keys(self) -> None:
        assert idempotency_key("a", "b") != idempotency_key("a", "c")

    def test_the_parts_cannot_be_smeared_together(self) -> None:
        """("ab", "c") and ("a", "bc") are different writes and must not
        collide into one key."""
        assert idempotency_key("ab", "c") != idempotency_key("a", "bc")

    def test_an_id_derived_from_a_key_is_stable(self) -> None:
        key = idempotency_key("call_1", SLOT.isoformat())
        assert derived_id("job_ops", key) == derived_id("job_ops", key)


class TestRetriesDoNotWriteTwice:
    def test_the_second_identical_call_is_a_replay(self, write_session) -> None:
        first = book_job(_request(), call_id="call_1", session=write_session)
        second = book_job(_request(), call_id="call_1", session=write_session)

        assert first.replayed is False
        assert second.replayed is True
        assert second.job_id == first.job_id
        assert second.audit_id == first.audit_id

    def test_only_one_row_is_written(self, write_session) -> None:
        book_job(_request(), call_id="call_1", session=write_session)
        book_job(_request(), call_id="call_1", session=write_session)

        booked = write_session.execute(
            text("SELECT count(*) FROM ops.booked_jobs WHERE call_id = 'call_1'")
        ).scalar_one()
        audited = write_session.execute(
            text("SELECT count(*) FROM ops.write_audit WHERE call_id = 'call_1'")
        ).scalar_one()
        assert booked == 1
        assert audited == 1

    def test_a_different_call_booking_the_same_slot_is_a_real_booking(
        self, write_session
    ) -> None:
        """Idempotency is scoped to the call. Two callers wanting the same
        Thursday are two appointments, not a retry."""
        first = book_job(_request(), call_id="call_1", session=write_session)
        second = book_job(_request(), call_id="call_2", session=write_session)
        assert second.replayed is False
        assert second.job_id != first.job_id

    def test_one_call_booking_two_addresses_in_one_slot_writes_both(
        self, write_session
    ) -> None:
        """A property manager booking two buildings into the same window is
        two legitimate appointments. `call_id + slot` alone would swallow
        the second as a retry, which is why the address is in the key.
        """
        first = book_job(
            _request(display_address="1 Test St"),
            call_id="call_1",
            session=write_session,
        )
        second = book_job(
            _request(display_address="2 Other Ave"),
            call_id="call_1",
            session=write_session,
        )
        assert second.replayed is False
        assert second.job_id != first.job_id


class TestTheAuditRow:
    def test_it_records_who_what_and_what_was_said(self, write_session) -> None:
        out = book_job(_request(), call_id="call_1", session=write_session)
        row = write_session.execute(
            text(
                "SELECT call_id, agent, tool, action, job_id, new_values, "
                "spoken_confirmation FROM ops.write_audit WHERE id = :i"
            ),
            {"i": out.audit_id},
        ).one()

        assert row.call_id == "call_1"
        assert row.agent == "Dispatch"
        assert row.tool == "book_job"
        assert row.action == "booked"
        assert row.job_id == out.job_id
        assert row.spoken_confirmation == "yes, Thursday at two works"
        assert row.new_values["description"] == "no cooling upstairs"

    def test_the_key_is_unique_in_the_database(self, write_session) -> None:
        """The retry guard is the constraint, not a lookup: a check before
        the insert would be a race two retries can both win."""
        constraint = write_session.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = 'ops.write_audit'::regclass AND contype = 'u'"
            )
        ).scalar_one()
        assert constraint == 1


class TestNotify:
    def test_the_trigger_is_wired_to_the_audit_table(self, db_session) -> None:
        name = db_session.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'ops.write_audit'::regclass AND NOT tgisinternal"
            )
        ).scalar_one()
        assert name == "write_audit_notify"

    def test_a_committed_write_delivers_a_notification(self) -> None:
        """Postgres holds notifications until commit, so this test commits
        for real on its own connection and deletes what it wrote. A write
        that rolls back correctly announces nothing, which is why the
        SAVEPOINT-based tests above see no notification.
        """
        engine = create_db_engine()
        listener = engine.raw_connection()
        writer = engine.raw_connection()
        audit_id = "wrt_notify_probe"
        try:
            listener.cursor().execute("LISTEN switchboard_writes")
            listener.commit()

            cursor = writer.cursor()
            cursor.execute(
                "INSERT INTO ops.write_audit (id, idempotency_key, call_id, "
                "agent, tool, action, job_id, new_values) VALUES "
                "(%s, %s, 'call_probe', 'Dispatch', 'book_job', 'booked', "
                "'job_probe', '{}')",
                (audit_id, f"probe_{audit_id}"),
            )
            writer.commit()

            driver = listener.driver_connection
            received = next(driver.notifies(timeout=5, stop_after=1))
            payload = json.loads(received.payload)

            assert received.channel == "switchboard_writes"
            assert payload["audit_id"] == audit_id
            assert payload["tool"] == "book_job"
            assert payload["call_id"] == "call_probe"
        finally:
            cleanup = writer.cursor()
            cleanup.execute("DELETE FROM ops.write_audit WHERE id = %s", (audit_id,))
            writer.commit()
            listener.close()
            writer.close()
            engine.dispose()


class TestConfirmationIsStructural:
    def test_a_booking_without_spoken_words_cannot_be_built(self) -> None:
        with pytest.raises(ValueError, match="spoken confirmation"):
            _request(spoken_confirmation="")

    def test_whitespace_is_not_a_confirmation(self) -> None:
        with pytest.raises(ValueError, match="spoken confirmation"):
            _request(spoken_confirmation="   ")
