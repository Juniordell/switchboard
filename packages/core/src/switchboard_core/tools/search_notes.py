"""`search_notes` (Service, hybrid) - retrieval over note prose, scoped.

CLAUDE.md hard rule 3 lives here: `entity_id` is a required field with no
default, so a request object cannot even be constructed without a scope.
Hard rule 2 lives here too, by omission - this tool answers "what did you
do", never "when were you here" or "what do I owe". Those are SQL.

This is the one tool that reports partial timings: T2.5 measured the OpenAI
call at 463 ms p50 against 2-5 ms for Postgres, so `embedding_ms` and
`postgres_ms` are logged beside the total for Layer 4 to assert apart.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from switchboard_core.prose.embeddings import EmbeddingsError
from switchboard_core.prose.search_notes import (
    DEFAULT_LIMIT,
    NoteSearchResult,
    search_notes_timed,
)
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.errors import (
    InvalidEntityIdError,
    RetrievalUnavailableError,
)


class SearchNotesRequest(BaseModel):
    #: A `cadr_...` (every job at that address) or a `job_...` (that job
    #: alone). No default, not `Optional`: an unscoped search is a bug.
    entity_id: str
    query: str
    limit: int = DEFAULT_LIMIT


class SearchNotesOutput(ToolResult):
    notes: list[NoteSearchResult]
    embedding_ms: float
    postgres_ms: float

    def result_rows(self) -> int:
        return len(self.notes)

    def timings(self) -> dict[str, float]:
        return {"embedding_ms": self.embedding_ms, "postgres_ms": self.postgres_ms}


@tool_call(kind="hybrid", name="search_notes", agent="Service")
def search_notes(
    request: SearchNotesRequest, *, call_id: str, session: Session
) -> SearchNotesOutput:
    """Every date returned is `job_service_date` - the service date of the
    job a note belongs to. Notes carry no timestamp of their own, and
    `docs/AGENTS.md` requires the agent to speak it as the visit's date, not
    the note's.

    The two `ValueError`s the prose layer raises for a malformed
    `entity_id` are translated here, at the tool boundary: from inside a
    call they are a domain outcome, while the layer below keeps raising for
    the scripts and build steps that want a traceback.
    """
    try:
        notes, timings = search_notes_timed(
            session, request.entity_id, request.query, limit=request.limit
        )
    except ValueError as exc:
        raise InvalidEntityIdError(str(exc)) from exc
    except EmbeddingsError as exc:
        raise RetrievalUnavailableError(str(exc)) from exc

    return SearchNotesOutput(
        notes=notes,
        embedding_ms=timings.embedding_ms,
        postgres_ms=timings.postgres_ms,
    )
