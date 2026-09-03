"""One row per note - no split, ever. The median note is 120 characters, p95
801, max 10,076 (`docs/DATA.md`); even the longest is a few thousand
`text-embedding-3-small` tokens, nowhere near its 8,191-token limit, so
splitting would trade the tech's actual sentence for an arbitrary cut with no
upside. "Chunk" describes the pipeline stage, not a transformation of the
note - the row's `content` is the note's `content`, verbatim.

`content_tsv` is a Postgres `GENERATED ALWAYS ... STORED` column: computed and
kept in sync by Postgres itself from `content`, never by application code, so
it cannot drift from what was actually embedded.

`embedding` is nullable on purpose. Building `note_chunks` (this table, plus
`content_tsv`) costs nothing and needs no external call -
`switchboard_core.prose.build_chunks` does it as part of the normal load.
Filling `embedding` calls a paid API and needs `OPENAI_API_KEY` -
`switchboard_core.prose.embed_pending` does that as a **separate**, explicit
step, idempotent by only ever selecting rows where `embedding IS NULL`, so a
partial run or a later addition of new notes never re-pays for what is
already embedded.
"""

from sqlalchemy import Computed, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import PROSE_SCHEMA, SOURCE_SCHEMA, Base, Vector

#: text-embedding-3-small's fixed output size.
EMBEDDING_DIMENSIONS = 1536


class NoteChunk(Base):
    __tablename__ = "note_chunks"
    __table_args__ = (
        Index("ix_note_chunks_job_id", "job_id"),
        Index(
            "ix_note_chunks_content_tsv",
            "content_tsv",
            postgresql_using="gin",
        ),
        {"schema": PROSE_SCHEMA},
    )

    note_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SOURCE_SCHEMA}.notes.id"), primary_key=True
    )

    #: Denormalised from source.notes.job_id. search_notes filters on this
    #: directly - the entity scope check has to be a plain indexed column on
    #: this table, not a join, since it runs before every ranking computation
    #: (CLAUDE.md hard rule 3: entity id is required, positional, never
    #: optional).
    job_id: Mapped[str] = mapped_column(ForeignKey(f"{SOURCE_SCHEMA}.jobs.id"))

    content: Mapped[str] = mapped_column(String)

    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
    )

    #: Nullable until switchboard_core.prose.embed_pending fills it. No
    #: ANN index (HNSW/IVFFlat): ARCHITECTURE.md's own reasoning for the
    #: hybrid design is that the entity filter leaves 3-10 candidate rows,
    #: and an approximate-nearest-neighbour index exists to speed up search
    #: over a corpus too large to score exhaustively - the opposite of this
    #: table's actual access pattern, where search_notes never ranks more
    #: than a handful of already-filtered rows.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
