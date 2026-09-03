"""`add_note`: a note attributed to the agent and the call that produced it.

Lands in `ops.agent_notes`. `scripts/verify_load.py` asserts `source.notes`
holds exactly 6,954 rows, and one of these tests asserts the same thing
from the other side of a write.
"""

from sqlalchemy import text

from switchboard_core.tools import AddNoteRequest, ToolError, add_note

#: A real, future, scheduled job: job_number 5487.
JOB_ID = "job_21f9fe518d0b401ab04201534c33533c"


class TestAddNote:
    def test_the_note_is_attributed_to_the_call(self, write_session) -> None:
        out = add_note(
            AddNoteRequest(job_id=JOB_ID, content="caller says the unit is icing up"),
            call_id="call_7",
            session=write_session,
        )
        row = write_session.execute(
            text(
                "SELECT job_id, content, call_id, agent FROM ops.agent_notes "
                "WHERE note_id = :n"
            ),
            {"n": out.note_id},
        ).one()
        assert row.job_id == JOB_ID
        assert row.call_id == "call_7"
        assert row.agent == "Dispatch"
        assert row.content == "caller says the unit is icing up"

    def test_source_notes_are_never_appended_to(self, write_session) -> None:
        """verify_load.py asserts source.notes holds exactly 6,954 rows."""
        before = write_session.execute(
            text("SELECT count(*) FROM source.notes")
        ).scalar_one()
        add_note(
            AddNoteRequest(job_id=JOB_ID, content="anything"),
            call_id="call_1",
            session=write_session,
        )
        after = write_session.execute(
            text("SELECT count(*) FROM source.notes")
        ).scalar_one()
        assert after == before == 6954

    def test_the_same_note_twice_on_one_call_is_a_replay(self, write_session) -> None:
        first = add_note(
            AddNoteRequest(job_id=JOB_ID, content="same words"),
            call_id="call_1",
            session=write_session,
        )
        second = add_note(
            AddNoteRequest(job_id=JOB_ID, content="same words"),
            call_id="call_1",
            session=write_session,
        )
        assert second.replayed is True
        assert second.note_id == first.note_id

    def test_two_different_notes_on_one_call_both_land(self, write_session) -> None:
        first = add_note(
            AddNoteRequest(job_id=JOB_ID, content="first thing"),
            call_id="call_1",
            session=write_session,
        )
        second = add_note(
            AddNoteRequest(job_id=JOB_ID, content="a different thing"),
            call_id="call_1",
            session=write_session,
        )
        assert second.replayed is False
        assert second.note_id != first.note_id

    def test_an_unknown_job_is_a_typed_error(self, write_session) -> None:
        out = add_note(
            AddNoteRequest(job_id="job_nope", content="anything"),
            call_id="call_1",
            session=write_session,
        )
        assert isinstance(out, ToolError)
        assert out.error == "JobNotFoundError"
