"""Prose tables: one row per note, vector + tsvector.

Reached only through `search_notes(entity_id, query)` with a resolved entity
id - see `switchboard_core.prose`.
"""

from switchboard_core.db.prose.note_chunks import EMBEDDING_DIMENSIONS, NoteChunk

__all__ = ["EMBEDDING_DIMENSIONS", "NoteChunk"]
