"""External network reads. Nothing here touches the database."""

from switchboard_core.web.search import (
    DEFAULT_MAX_RESULTS,
    TAVILY_URL,
    WebResult,
    WebSearchError,
    search_web,
)

__all__ = [
    "DEFAULT_MAX_RESULTS",
    "TAVILY_URL",
    "WebResult",
    "WebSearchError",
    "search_web",
]
