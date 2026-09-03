"""The minimal text tool client.

The model call is stubbed with a real `httpx.MockTransport`, so the request
that would go out - the schemas, the prompt, the utterance - is built for
real and asserted on. Only the network is replaced.

One live test exists and is skipped unless `HARNESS_LIVE=1`, because every
run of it costs a real API call.
"""

import json
import os

import httpx
import pytest

from switchboard_agent.text_client import (
    SYSTEM_PROMPT,
    ToolCall,
    choose_tools,
    tool_schemas,
)
from switchboard_core.tools import READ_TOOLS, WRITE_TOOLS


def _reply(tool_calls: list[dict]) -> dict:
    return {"choices": [{"message": {"tool_calls": tool_calls}}]}


def _call(name: str, arguments: dict) -> dict:
    return {"function": {"name": name, "arguments": json.dumps(arguments)}}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


#: Captured before the stub fixture below overwrites the variable, so the
#: live test can put the real key back. Without this the autouse stub
#: reaches the live class too and it can only ever 401.
_REAL_KEY = os.environ.get("OPENAI_API_KEY", "")


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


class TestTheSchemasItBinds:
    def test_every_tool_is_offered_to_the_model(self) -> None:
        offered = {s["function"]["name"] for s in tool_schemas()}
        assert offered == set(READ_TOOLS) | set(WRITE_TOOLS)

    def test_each_carries_the_tool_s_own_pydantic_schema(self) -> None:
        """The same models the HTTP layer validates against - one schema,
        not a hand-written copy that can drift from it."""
        by_name = {s["function"]["name"]: s for s in tool_schemas()}
        params = by_name["search_notes"]["function"]["parameters"]
        assert params["type"] == "object"
        assert "entity_id" in params["properties"]
        assert "entity_id" in params["required"]

    def test_each_carries_a_description(self) -> None:
        for schema in tool_schemas():
            assert schema["function"]["description"]


class TestTheRequestItSends:
    def test_it_sends_the_utterance_the_prompt_and_the_tools(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.read()))
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json=_reply([]))

        choose_tools(
            "when were you last at 89 harborlight shores", client=_client(handler)
        )

        assert seen["auth"] == "Bearer sk-test"
        assert seen["messages"][0]["role"] == "system"
        assert seen["messages"][0]["content"] == SYSTEM_PROMPT
        assert seen["messages"][1]["content"] == (
            "when were you last at 89 harborlight shores"
        )
        assert len(seen["tools"]) == len(READ_TOOLS) + len(WRITE_TOOLS)
        assert seen["tool_choice"] == "auto"


class TestWhatItReturns:
    def test_it_returns_the_calls_the_model_chose_in_order(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_reply(
                    [
                        _call("resolve_address", {"spoken_address": "89 harborlight"}),
                        _call("get_visit_history", {"canonical_id": "cadr_x"}),
                    ]
                ),
            )

        calls = choose_tools("when were you last there", client=_client(handler))
        assert [c.name for c in calls] == ["resolve_address", "get_visit_history"]
        assert calls[0].arguments == {"spoken_address": "89 harborlight"}
        assert all(isinstance(c, ToolCall) for c in calls)

    def test_choosing_no_tool_is_an_empty_list_not_an_error(self) -> None:
        """A caller who has not said enough to act on gets a question, not
        a tool. Layer 1 has to be able to assert that."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {}}]})

        assert choose_tools("hello?", client=_client(handler)) == []

    def test_it_executes_nothing(self) -> None:
        """A golden case may assert on a book_job call without booking
        anything - selection and execution are different jobs."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_reply(
                    [
                        _call(
                            "book_job",
                            {
                                "customer_id": "cus_x",
                                "scheduled_start": "2026-11-05T14:00:00+00:00",
                                "description": "x",
                                "display_address": "1 Test St",
                                "spoken_confirmation": "yes",
                            },
                        )
                    ]
                ),
            )

        calls = choose_tools("book me thursday", client=_client(handler))
        assert calls[0].name == "book_job"
        # Nothing was written: the client returns the request, never runs it.
        from sqlalchemy import text

        from switchboard_core.db.session import create_db_engine, session_factory

        engine = create_db_engine()
        with session_factory(engine)() as session, session.begin():
            booked = session.execute(
                text("SELECT count(*) FROM ops.booked_jobs WHERE customer_id = 'cus_x'")
            ).scalar_one()
        engine.dispose()
        assert booked == 0


class TestFailures:
    def test_a_missing_key_says_so(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "")
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            choose_tools("anything")

    def test_an_http_error_propagates(self) -> None:
        """The client is harness plumbing, not a tool: a broken model call
        is a defect the runner should see, not a polite empty list."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="upstream boom")

        with pytest.raises(httpx.HTTPStatusError):
            choose_tools("anything", client=_client(handler))


@pytest.mark.skipif(
    os.environ.get("HARNESS_LIVE") != "1",
    reason="costs a real API call; set HARNESS_LIVE=1 to run",
)
class TestAgainstTheRealModel:
    @pytest.fixture(autouse=True)
    def _use_the_real_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", _REAL_KEY)

    def test_it_resolves_the_address_before_reading_history(self) -> None:
        """`docs/HARNESS.md`'s own Layer 1 example: this utterance must
        produce resolve_address and must not open with search_notes."""
        calls = choose_tools("when were you last at 89 harborlight shores")
        assert calls
        assert calls[0].name == "resolve_address"
        assert calls[0].name != "search_notes"
