"""`web_search` (Service, web) - the only tool that leaves the building.

`docs/AGENTS.md`: always returns the source, and try `search_notes` first
for anything the company may already know. The first is enforced here - a
result without a URL never reaches the caller. The second is a prompt-level
instruction, not something this tool can check, and it is stated in the
docstring the agent binds.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.errors import WebSearchUnavailableError
from switchboard_core.web.search import (
    DEFAULT_MAX_RESULTS,
    WebResult,
    WebSearchError,
    search_web,
)


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = DEFAULT_MAX_RESULTS


class WebSearchOutput(ToolResult):
    results: list[WebResult]

    def result_rows(self) -> int:
        return len(self.results)


@tool_call(kind="web", name="web_search", agent="Service")
def web_search(
    request: WebSearchRequest,
    *,
    call_id: str,
    session: Session | None = None,
) -> WebSearchOutput:
    """Weather, model numbers, supplier hours - things this company's own
    records do not contain. Try `search_notes` first for anything they
    might.

    Every result carries the URL it came from, and the agent speaks it.

    `session` is accepted and ignored so the HTTP layer and the agent
    runtime can dispatch every tool the same way; nothing here reads the
    database.
    """
    try:
        results = search_web(request.query, max_results=request.max_results)
    except WebSearchError as exc:
        raise WebSearchUnavailableError(str(exc)) from exc

    return WebSearchOutput(results=results)
