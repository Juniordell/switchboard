"""`log_tool_call` in isolation: no contract, no error handling - a plain
function that may still raise, wrapped only for observability. Every
assertion here reads the actual JSON line the decorator emitted via
`caplog`, not a mock of the logging call.
"""

import json
import logging
import time

import pytest
from pydantic import BaseModel

from switchboard_core.tools.call_log import log_tool_call


class _Request(BaseModel):
    street: str
    zip: str


class _PlainResult(BaseModel):
    value: int


class _ListResult(BaseModel):
    candidates: list[str]

    def result_rows(self) -> int:
        return len(self.candidates)


class _TimedResult(BaseModel):
    value: int

    def timings(self) -> dict[str, float]:
        return {"embedding_ms": 12.5, "postgres_ms": 3.1}


def _record(caplog: pytest.LogCaptureFixture) -> dict:
    assert len(caplog.records) == 1
    return json.loads(caplog.records[0].message)


class TestSuccess:
    def test_logs_the_seven_required_fields(self, caplog) -> None:
        @log_tool_call(tool="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _PlainResult:
            return _PlainResult(value=1)

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            fn(_Request(street="89 Harborlight Shores", zip="33162"), call_id="call_1")

        record = _record(caplog)
        assert record["call_id"] == "call_1"
        assert record["agent"] == "Triage"
        assert record["tool"] == "resolve_address"
        assert record["args"] == {"street": "89 Harborlight Shores", "zip": "33162"}
        assert record["ok"] is True
        assert isinstance(record["duration_ms"], float)
        assert record["duration_ms"] >= 0

    def test_result_rows_defaults_to_one_without_the_hook(self, caplog) -> None:
        @log_tool_call(tool="get_customer_balance", agent="Service")
        def fn(request: _Request, *, call_id: str) -> _PlainResult:
            return _PlainResult(value=1)

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            fn(_Request(street="x", zip="x"), call_id="call_1")

        assert _record(caplog)["result_rows"] == 1

    def test_result_rows_uses_the_result_s_own_count_when_present(self, caplog) -> None:
        @log_tool_call(tool="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _ListResult:
            return _ListResult(candidates=["a", "b", "c"])

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            fn(_Request(street="x", zip="x"), call_id="call_1")

        assert _record(caplog)["result_rows"] == 3

    def test_duration_ms_reflects_real_elapsed_time(self, caplog) -> None:
        @log_tool_call(tool="search_notes", agent="Service")
        def fn(request: _Request, *, call_id: str) -> _PlainResult:
            time.sleep(0.02)
            return _PlainResult(value=1)

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            fn(_Request(street="x", zip="x"), call_id="call_1")

        assert _record(caplog)["duration_ms"] >= 20

    def test_partial_timings_are_merged_alongside_the_total(self, caplog) -> None:
        """search_notes' shape (T2.5): the embedding call and Postgres are
        two different real costs, and Layer 4 needs to assert them
        separately - `duration_ms` alone can't answer that.
        """

        @log_tool_call(tool="search_notes", agent="Service")
        def fn(request: _Request, *, call_id: str) -> _TimedResult:
            return _TimedResult(value=1)

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            fn(_Request(street="x", zip="x"), call_id="call_1")

        record = _record(caplog)
        assert record["embedding_ms"] == 12.5
        assert record["postgres_ms"] == 3.1
        assert "duration_ms" in record  # the total is still reported too

    def test_a_timing_key_cannot_clobber_a_reserved_field(self, caplog) -> None:
        class _HostileResult(BaseModel):
            def timings(self) -> dict[str, float]:
                return {"ok": 999.0, "duration_ms": -1.0}

        @log_tool_call(tool="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _HostileResult:
            return _HostileResult()

        with caplog.at_level(logging.INFO, logger="switchboard_core.tools"):
            fn(_Request(street="x", zip="x"), call_id="call_1")

        record = _record(caplog)
        assert record["ok"] is True
        assert record["duration_ms"] != -1.0


class TestFailure:
    def test_logs_ok_false_and_zero_rows_then_reraises(self, caplog) -> None:
        @log_tool_call(tool="resolve_address", agent="Triage")
        def fn(request: _Request, *, call_id: str) -> _PlainResult:
            raise ValueError("boom")

        with (
            caplog.at_level(logging.WARNING, logger="switchboard_core.tools"),
            pytest.raises(ValueError, match="boom"),
        ):
            fn(_Request(street="x", zip="x"), call_id="call_1")

        record = _record(caplog)
        assert record["ok"] is False
        assert record["result_rows"] == 0
        assert record["call_id"] == "call_1"

    def test_failure_carries_no_partial_timings(self, caplog) -> None:
        """There is no result to ask on an exception - nothing invented in
        its place."""

        @log_tool_call(tool="search_notes", agent="Service")
        def fn(request: _Request, *, call_id: str) -> _TimedResult:
            raise RuntimeError("api down")

        with (
            caplog.at_level(logging.WARNING, logger="switchboard_core.tools"),
            pytest.raises(RuntimeError),
        ):
            fn(_Request(street="x", zip="x"), call_id="call_1")

        record = _record(caplog)
        assert "embedding_ms" not in record
        assert "postgres_ms" not in record
