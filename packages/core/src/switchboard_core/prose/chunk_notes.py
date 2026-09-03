"""Building `prose.note_chunks` from `source.notes`. Free, no external call -
`embed_pending` (the paid half) is a separate step.

`note_id` is copied verbatim from `source.notes`, never derived from code the
way `canonical_id` is (see `build_addresses.py`'s docstring for why that
distinction decides upsert vs rebuild). `content` never changes once loaded -
`data/` is immutable (CLAUDE.md hard rule 1) - so a chunk, once written, is
written for good: `ON CONFLICT (note_id) DO NOTHING`, not an upsert that sets
every column. Setting every column on conflict would reset `embedding` back
to `NULL` on every re-run, silently discarding paid work each time this step
is repeated - the one column this insert must never touch.
"""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from switchboard_core.db.source import Note

_INSERT_CHUNK = text(
    """
    INSERT INTO prose.note_chunks (note_id, job_id, content)
    VALUES (:note_id, :job_id, :content)
    ON CONFLICT (note_id) DO NOTHING
    """
)


def chunk_notes(session: Session) -> dict[str, int]:
    """One `prose.note_chunks` row per `source.notes` row, unconditionally -
    no length threshold, no split. See the module and `NoteChunk` docstrings
    for why.
    """
    notes = session.execute(select(Note.id, Note.job_id, Note.content)).all()
    if not notes:
        return {"note_chunks": 0}

    rows = [
        {"note_id": note.id, "job_id": note.job_id, "content": note.content}
        for note in notes
    ]
    session.execute(_INSERT_CHUNK, rows)
    return {"note_chunks": len(rows)}
