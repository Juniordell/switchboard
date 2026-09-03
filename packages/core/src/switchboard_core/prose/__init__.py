"""The Prose layer: one chunk per note, hybrid search, entity-scoped only.

Two build steps, deliberately separate - see `chunk_notes.py`'s docstring:
`chunk_notes` (free, part of every load) and `embed_pending` (paid, run
explicitly via `python -m switchboard_core.prose`).
"""

from switchboard_core.prose.chunk_notes import chunk_notes
from switchboard_core.prose.embed_pending import embed_pending
from switchboard_core.prose.embeddings import (
    BATCH_SIZE,
    EMBEDDING_MODEL,
    EmbeddingsError,
    embed_texts,
)
from switchboard_core.prose.search_notes import (
    DEFAULT_LIMIT,
    RRF_K,
    SNIPPET_MAX_CHARS,
    NoteSearchResult,
)
from switchboard_core.prose.search_notes import rank_candidates as rank_candidates
from switchboard_core.prose.search_notes import search_notes as search_notes

__all__ = [
    "BATCH_SIZE",
    "DEFAULT_LIMIT",
    "EMBEDDING_MODEL",
    "RRF_K",
    "SNIPPET_MAX_CHARS",
    "EmbeddingsError",
    "NoteSearchResult",
    "chunk_notes",
    "embed_pending",
    "embed_texts",
    "rank_candidates",
    "search_notes",
]
