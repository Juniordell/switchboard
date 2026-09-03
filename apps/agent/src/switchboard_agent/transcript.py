"""Persist what was said, so the call log has words in it.

A list of tool calls with no conversation around them tells an office
manager what the machine did and nothing about what the caller wanted. This
subscribes to the session's `conversation_item_added` event and writes each
turn.

Best effort, like the call row itself: a database the agent cannot reach is
a reason to answer the phone without a transcript, not a reason to drop the
call.
"""

import contextlib
import itertools
import logging
import uuid

from sqlalchemy import text

from switchboard_core.db.session import create_db_engine, session_factory

log = logging.getLogger(__name__)

_INSERT = text(
    """
    INSERT INTO ops.transcript_turns (id, call_id, seq, role, text, agent)
    VALUES (:id, :call_id, :seq, :role, :text, :agent)
    """
)


def capture_transcript(session, call_id: str) -> None:
    """Write every conversation item on this session to `ops.transcript_turns`.

    `seq` comes from a counter rather than the clock: the agent can answer
    inside the same millisecond it was asked, and "which came first" has to
    survive that.
    """
    engine = create_db_engine()
    sessions = session_factory(engine)
    counter = itertools.count()

    @session.on("conversation_item_added")
    def _on_item(event) -> None:
        item = getattr(event, "item", event)
        content = getattr(item, "text_content", None) or ""
        role = getattr(item, "role", "") or ""
        if not content.strip():
            return

        agent = None
        with contextlib.suppress(Exception):
            current = session.current_agent
            agent = getattr(current, "NAME", None)

        with contextlib.suppress(Exception), sessions() as db, db.begin():
            db.execute(
                _INSERT,
                {
                    "id": f"trn_{uuid.uuid4().hex}",
                    "call_id": call_id,
                    "seq": next(counter),
                    "role": str(role),
                    "text": content,
                    "agent": agent,
                },
            )
