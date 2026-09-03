"""Tavily search, over `httpx`, one POST.

The SDK is not used for the same reason the OpenAI one was not in T2.5
(`docs/DECISIONS.md` 69): this is a single endpoint with a JSON body, and
`httpx` is already a dependency. No new package.

**Every result carries its source.** `docs/AGENTS.md` requires `web_search`
to always return the source, so `url` is a required field and a result
Tavily returns without one is dropped rather than passed on. A claim the
agent cannot attribute is worse than one it does not make - and there is no
"unknown source" state for it to fall into.
"""

import os

import httpx
from pydantic import BaseModel

TAVILY_URL = "https://api.tavily.com/search"

DEFAULT_MAX_RESULTS = 5

#: Tavily's own cap on a basic search.
MAX_RESULTS_LIMIT = 20

REQUEST_TIMEOUT_SECONDS = 10.0


class WebSearchError(RuntimeError):
    """Tavily is unreachable, unauthorised, or not configured."""


class WebResult(BaseModel):
    title: str

    #: Required, never optional. This is the source the agent must speak.
    url: str

    snippet: str

    #: Tavily's own relevance score, passed through unchanged rather than
    #: rescaled - this module ranks nothing.
    score: float | None = None


def _api_key() -> str:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise WebSearchError(
            "TAVILY_API_KEY is not set. web_search needs it; every other tool "
            "reads the database and does not."
        )
    return key


def search_web(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    client: httpx.Client | None = None,
) -> list[WebResult]:
    """Search the web and return sourced results, most relevant first.

    `client` is injectable so a test can drive a real `httpx` transport
    without a network call - the request that would go out is still built
    and asserted on, rather than the whole function being mocked away.
    """
    key = _api_key()
    payload = {
        "query": query,
        "max_results": min(max_results, MAX_RESULTS_LIMIT),
        "search_depth": "basic",
    }
    headers = {"Authorization": f"Bearer {key}"}

    owned = client is None
    http = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = http.post(TAVILY_URL, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise WebSearchError(f"Tavily request failed: {exc}") from exc
    finally:
        if owned:
            http.close()

    if response.status_code != httpx.codes.OK:
        raise WebSearchError(
            f"Tavily returned {response.status_code}: {response.text[:200]}"
        )

    results = []
    for item in response.json().get("results", []):
        url = (item.get("url") or "").strip()
        if not url:
            # No source, no result: see the module docstring.
            continue
        results.append(
            WebResult(
                title=item.get("title") or url,
                url=url,
                snippet=item.get("content") or "",
                score=item.get("score"),
            )
        )
    return results
