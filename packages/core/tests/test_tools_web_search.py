"""`web_search`: the source requirement, and what happens with no key.

No live Tavily call. The request that would go out is built for real and
asserted on through an `httpx.MockTransport`, so the URL, the bearer header
and the body are the real ones - what is stubbed is the network, not the
function under test.
"""

import sys

import httpx
import pytest

from switchboard_core.tools.contract import ToolError
from switchboard_core.tools.web_search import (
    WebSearchOutput,
    WebSearchRequest,
    web_search,
)
from switchboard_core.web.search import (
    TAVILY_URL,
    WebSearchError,
    search_web,
)

#: `tools/__init__.py` re-exports a function named `web_search`, shadowing
#: the submodule of the same name, so the dotted string form of monkeypatch
#: resolves to the function. Same wart as `prose.search_notes` - the module
#: object is the thing to patch.
_WEB_SEARCH_MODULE = sys.modules["switchboard_core.tools.web_search"]

_TAVILY_BODY = {
    "results": [
        {
            "title": "R-410A phase-out",
            "url": "https://example.com/r410a",
            "content": "R-410A is being phased down under the AIM Act.",
            "score": 0.93,
        },
        {
            "title": "Sourceless",
            "url": "",
            "content": "a claim with nowhere to attribute it",
            "score": 0.9,
        },
    ]
}


@pytest.fixture
def tavily_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestTheRequestItSends:
    def test_it_posts_the_query_with_a_bearer_token(self, tavily_key) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization")
            seen["body"] = request.read().decode()
            return httpx.Response(200, json=_TAVILY_BODY)

        search_web("r410a phase out", client=_client(handler))

        assert seen["url"] == TAVILY_URL
        assert seen["auth"] == "Bearer tvly-test-key"
        assert "r410a phase out" in seen["body"]


class TestEveryResultCarriesItsSource:
    def test_results_come_back_with_urls(self, tavily_key) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_TAVILY_BODY)

        results = search_web("r410a", client=_client(handler))
        assert all(r.url for r in results)

    def test_a_result_without_a_url_is_dropped_not_passed_on(self, tavily_key) -> None:
        """A claim the agent cannot attribute is worse than one it does not
        make, and there is no "unknown source" for it to fall into."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_TAVILY_BODY)

        results = search_web("r410a", client=_client(handler))
        assert len(results) == 1
        assert results[0].url == "https://example.com/r410a"

    def test_url_is_a_required_field(self) -> None:
        from switchboard_core.web.search import WebResult

        assert WebResult.model_fields["url"].is_required()


class TestFailuresAreTyped:
    def test_no_key_configured_is_a_domain_error(self, monkeypatch) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "")
        with pytest.raises(WebSearchError, match="TAVILY_API_KEY"):
            search_web("anything")

    def test_the_tool_returns_a_typed_error_rather_than_raising(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "")
        out = web_search(WebSearchRequest(query="anything"), call_id="call_1")
        assert isinstance(out, ToolError)
        assert out.error == "WebSearchUnavailableError"
        assert out.tool == "web_search"

    def test_an_http_error_is_a_domain_error(self, tavily_key) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorised")

        with pytest.raises(WebSearchError, match="401"):
            search_web("anything", client=_client(handler))


class TestContract:
    def test_results_are_counted_as_rows(self, tavily_key, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_TAVILY_BODY)

        monkeypatch.setattr(
            _WEB_SEARCH_MODULE,
            "search_web",
            lambda q, max_results=5: search_web(
                q, max_results=max_results, client=_client(handler)
            ),
        )
        out = web_search(WebSearchRequest(query="r410a"), call_id="call_1")
        assert isinstance(out, WebSearchOutput)
        assert out.result_rows() == len(out.results) == 1

    def test_it_needs_no_database(self, tavily_key, monkeypatch) -> None:
        """The only tool that reads nothing local. It still accepts a
        session so the HTTP layer can dispatch every tool identically."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_TAVILY_BODY)

        monkeypatch.setattr(
            _WEB_SEARCH_MODULE,
            "search_web",
            lambda q, max_results=5: search_web(
                q, max_results=max_results, client=_client(handler)
            ),
        )
        out = web_search(WebSearchRequest(query="r410a"), call_id="call_1")
        assert out.results
