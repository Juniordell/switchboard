"""The contract on top of `log_tool_call`: Pydantic in, Pydantic out, a
recognised domain error returned as a typed `ToolError`, and a programming
error left to explode.

The boundary in `TestProgrammingErrorsPropagate` is the deliberate part. A
tool that answers every failure with a polite `ToolError` cannot be told
apart, from the outside, from a tool with a bug in it - so only
`ToolDomainError` is caught, and `pydantic.ValidationError`, `KeyError` and
anything else reach the caller (and the test suite) as themselves.
"""

import json
import logging

import pytest
from pydantic import BaseModel, ValidationError

from switchboard_core.tools.contract import (
    ToolDomainError,
    ToolError,
    ToolResult,
    tool_call,
)


class _Request(BaseModel):
    street: str


class _Result(ToolResult):
    value: int


class _Candidates(ToolResult):
    candidates: list[str]

    def result_rows(self) -> int:
        return len(self.candidates)


class _AddressNotFoundError(ToolDomainError):
    """A domain outcome a real tool would raise: nothing resolved."""


class TestSuccess:
    def test_returns_the_result_unchanged(self) -> None:
        @tool_call(kind="SQL", name="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _Result:
            return _Result(value=7)

        result = fn(_Request(street="x"), call_id="call_1")
        assert isinstance(result, _Result)
        assert result.value == 7

    def test_extra_keyword_arguments_reach_the_tool(self) -> None:
        """A real tool takes its `session` this way - injected by the
        caller, and deliberately not part of the logged `args`."""

        @tool_call(kind="SQL", name="get_visit_history", agent="Service")
        def fn(request: _Request, *, call_id: str, session: str) -> _Result:
            return _Result(value=len(session))

        result = fn(_Request(street="x"), call_id="call_1", session="abcd")
        assert result.value == 4

    def test_the_call_is_logged_through_the_composed_decorator(self, caplog) -> None:
        @tool_call(kind="SQL", name="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _Candidates:
            return _Candidates(candidates=["a", "b"])

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            fn(_Request(street="89 Harborlight"), call_id="call_9")

        record = json.loads(caplog.records[0].message)
        assert record["call_id"] == "call_9"
        assert record["tool"] == "resolve_address"
        assert record["result_rows"] == 2
        assert record["ok"] is True
        assert record["args"] == {"street": "89 Harborlight"}
        assert "session" not in record["args"]
        assert "call_id" not in record["args"]


class TestCallIdIsMandatory:
    """Same structural rule as `search_notes`' `entity_id` in T2.5: not a
    convention, an argument you cannot leave out."""

    def test_omitting_call_id_is_a_type_error(self) -> None:
        @tool_call(kind="SQL", name="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _Result:
            return _Result(value=1)

        with pytest.raises(TypeError, match="call_id"):
            fn(_Request(street="x"))

    def test_call_id_cannot_be_passed_positionally(self) -> None:
        @tool_call(kind="SQL", name="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _Result:
            return _Result(value=1)

        with pytest.raises(TypeError):
            fn(_Request(street="x"), "call_1")


class TestDomainErrorsBecomeTypedResults:
    def test_a_domain_error_is_returned_not_raised(self) -> None:
        @tool_call(kind="SQL", name="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _Result:
            raise _AddressNotFoundError("no candidate above 0.55")

        result = fn(_Request(street="nowhere"), call_id="call_1")
        assert isinstance(result, ToolError)
        assert result.tool == "resolve_address"
        assert result.error == "_AddressNotFoundError"
        assert result.message == "no candidate above 0.55"

    def test_the_failure_is_logged_before_it_becomes_a_result(self, caplog) -> None:
        @tool_call(kind="SQL", name="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _Result:
            raise _AddressNotFoundError("nothing resolved")

        with caplog.at_level(logging.WARNING, logger="switchboard_core.tools"):
            fn(_Request(street="nowhere"), call_id="call_1")

        record = json.loads(caplog.records[0].message)
        assert record["ok"] is False
        assert record["result_rows"] == 0


class TestProgrammingErrorsPropagate:
    """The deliberate boundary: these are bugs, and a bug must fail loudly
    in a test rather than arrive as a polite sentence on a phone call."""

    def test_validation_error_propagates(self) -> None:
        @tool_call(kind="SQL", name="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _Result:
            return _Result(value="not an int")  # the tool's own bug

        with pytest.raises(ValidationError):
            fn(_Request(street="x"), call_id="call_1")

    def test_key_error_propagates(self) -> None:
        @tool_call(kind="SQL", name="get_visit_history", agent="Service")
        def fn(request: _Request, *, call_id: str) -> _Result:
            return _Result(value={}["missing"])

        with pytest.raises(KeyError):
            fn(_Request(street="x"), call_id="call_1")

    def test_a_bare_value_error_is_not_treated_as_a_domain_outcome(self) -> None:
        """A plain ValueError is not a domain error by default - a tool
        that means one raises a `ToolDomainError` subclass and says so.
        The knowledge and prose modules built in Phase 2 still raise bare
        ValueErrors; bridging those is T3.2's job, when each is actually
        wrapped as a tool.
        """

        @tool_call(kind="SQL", name="search_notes", agent="Service")
        def fn(request: _Request, *, call_id: str) -> _Result:
            raise ValueError("entity_id must be a canonical_id or a job_id")

        with pytest.raises(ValueError, match="entity_id"):
            fn(_Request(street="x"), call_id="call_1")

    def test_a_propagating_error_is_still_logged(self, caplog) -> None:
        @tool_call(kind="SQL", name="get_visit_history", agent="Service")
        def fn(request: _Request, *, call_id: str) -> _Result:
            raise KeyError("missing")

        with (
            caplog.at_level(logging.WARNING, logger="switchboard_core.tools"),
            pytest.raises(KeyError),
        ):
            fn(_Request(street="x"), call_id="call_1")

        record = json.loads(caplog.records[0].message)
        assert record["ok"] is False
        assert record["tool"] == "get_visit_history"


class TestToolResultHooks:
    def test_result_rows_defaults_to_one(self) -> None:
        assert _Result(value=1).result_rows() == 1

    def test_timings_default_to_nothing_extra(self) -> None:
        assert _Result(value=1).timings() == {}

    def test_a_result_can_report_its_own_split_costs(self) -> None:
        class _SearchResult(ToolResult):
            embedding_ms: float
            postgres_ms: float

            def timings(self) -> dict[str, float]:
                return {
                    "embedding_ms": self.embedding_ms,
                    "postgres_ms": self.postgres_ms,
                }

        assert _SearchResult(embedding_ms=463.0, postgres_ms=2.3).timings() == {
            "embedding_ms": 463.0,
            "postgres_ms": 2.3,
        }
