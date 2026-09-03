"""Filling `embedding` for every `prose.note_chunks` row that doesn't have
one yet. The paid half of building Prose, kept out of
`switchboard_core.load` and `switchboard_core.knowledge.build_all` on
purpose - see `chunk_notes.py`'s docstring. Run explicitly:

    uv run python -m switchboard_core.prose.build

Idempotent by construction: the selection is always `WHERE embedding IS
NULL`, so a prior partial run, an interrupted one, or new notes added later
all just mean fewer rows this time - never a re-embed, never a re-charge.
Commits after every batch, not once at the end, so an API failure partway
through a large run keeps everything already embedded rather than rolling it
back with the rest.
"""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.prose.embeddings import BATCH_SIZE, embed_texts

log = logging.getLogger(__name__)

_SELECT_PENDING = text(
    """
    SELECT note_id, content FROM prose.note_chunks
    WHERE embedding IS NULL
    ORDER BY note_id
    LIMIT :batch_size
    """
)

_UPDATE_EMBEDDING = text(
    "UPDATE prose.note_chunks SET embedding = (:embedding)::vector "
    "WHERE note_id = :note_id"
)


def embed_pending(session: Session) -> dict[str, int]:
    """Embed every row with `embedding IS NULL`, `BATCH_SIZE` at a time,
    committing after each batch.
    """
    total = 0
    while True:
        batch = session.execute(_SELECT_PENDING, {"batch_size": BATCH_SIZE}).all()
        if not batch:
            break

        vectors = embed_texts([row.content for row in batch])
        for row, vector in zip(batch, vectors, strict=True):
            literal = "[" + ",".join(repr(float(x)) for x in vector) + "]"
            session.execute(
                _UPDATE_EMBEDDING, {"note_id": row.note_id, "embedding": literal}
            )
        session.commit()

        total += len(batch)
        log.info("embedded %d note(s) (%d so far)", len(batch), total)

    return {"note_chunks_embedded": total}
