"""Logs every tool invocation with the fields CLAUDE.md hard rule 5
requires - `call_id`, `agent`, `tool`, `args`, `duration_ms`, `result_rows`,
`ok` - including on failure. This is the one thing every tool from T3.2
onward is built on: `tools.contract.tool_call` wraps this decorator to add
the "never raises to its caller" guarantee, but the logging here works
standalone and is exercised in its own tests against a plain function that
still raises.

`duration_ms` is the total wall time of the call, always present. A tool
whose own budget is split across more than one real cost - `search_notes`
measured in T2.5 at 463 ms for the OpenAI embedding call against 2-5 ms for
Postgres - can report that breakdown too: a result that defines
`timings() -> dict[str, float]` has those keys merged into the same log
record, alongside the total, not instead of it. Layer 4 (`docs/HARNESS.md`)
needs the network leg asserted separately from the database leg; a single
`duration_ms` cannot answer that on its own.
"""

import functools
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

log = logging.getLogger("switchboard_core.tools")

#: The seven fields CLAUDE.md hard rule 5 names. A result's `timings()` keys
#: are merged in around them, so a badly-named custom timing can never
#: clobber one of these.
_RESERVED_KEYS = frozenset(
    {"call_id", "agent", "tool", "args", "duration_ms", "result_rows", "ok"}
)


def _result_rows(result: Any) -> int:
    """A result that knows its own shape (`ToolResult.result_rows`, from
    `tools.contract`) reports it; anything else counts as the one object it
    is. The error case never reaches this function - the caller passes 0
    for that directly, since there is no result to ask.
    """
    counter = getattr(result, "result_rows", None)
    return counter() if callable(counter) else 1


def _timings(result: Any) -> dict[str, float]:
    """A result that knows its own partial costs (`ToolResult.timings`)
    reports them; most tools don't override it, and get just the total.
    """
    getter = getattr(result, "timings", None)
    return getter() if callable(getter) else {}


def log_tool_call(
    *, tool: str, agent: str
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap `fn(request, *, call_id, **kwargs)`. Every call is logged as one
    JSON line - success or exception - and then the exception, if any, is
    re-raised unchanged. This decorator does not decide what a caller ends
    up seeing on failure; it only guarantees the call is on record either
    way. `tool` and `agent` are fixed per tool (`docs/AGENTS.md`'s tool
    table), so they are decoration-time arguments, not per-call ones.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(request: BaseModel, *, call_id: str, **kwargs: Any) -> Any:
            args = request.model_dump(mode="json")
            t0 = time.perf_counter()
            try:
                result = fn(request, call_id=call_id, **kwargs)
            except Exception:
                _emit(call_id, agent, tool, args, t0, {}, result_rows=0, ok=False)
                raise
            _emit(
                call_id,
                agent,
                tool,
                args,
                t0,
                _timings(result),
                result_rows=_result_rows(result),
                ok=True,
            )
            return result

        return wrapper

    return decorator


def _emit(
    call_id: str,
    agent: str,
    tool: str,
    args: dict[str, Any],
    t0: float,
    timings: dict[str, float],
    *,
    result_rows: int,
    ok: bool,
) -> None:
    record: dict[str, Any] = {
        "call_id": call_id,
        "agent": agent,
        "tool": tool,
        "args": args,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        "result_rows": result_rows,
        "ok": ok,
    }
    for key, value in timings.items():
        if key not in _RESERVED_KEYS:
            record[key] = value
    log.log(logging.INFO if ok else logging.WARNING, json.dumps(record))
