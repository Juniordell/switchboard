"""T3.1's tool contract: a Pydantic request in, a Pydantic result out, and
the decorated function never raises to its caller - CLAUDE.md hard rule 5's
`ok` field, and the returned type, are what a caller checks, not a
try/except wrapped around the call. `tool_call` composes
`tools.call_log.log_tool_call`: every call is logged first, success or
exception, and only after that is an exception turned into the typed
`ToolError` a caller actually receives.
"""

import functools
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from switchboard_core.tools.call_log import log_tool_call


class ToolResult(BaseModel):
    """Base for a tool's success payload.

    `result_rows()` is what `log_tool_call` asks for the log's
    `result_rows` field - override it on a result carrying a list of
    candidates, visits, or notes; the default of 1 fits a single-object
    answer such as a balance or a warranty verdict.

    `timings()` is for a tool whose own budget is split across more than
    one real cost (`search_notes`: an OpenAI call and a Postgres query,
    T2.5) - override it to report the breakdown; the default reports
    nothing extra; the decorator still logs the total either way.
    """

    def result_rows(self) -> int:
        return 1

    def timings(self) -> dict[str, float]:
        return {}


class ToolError(BaseModel):
    """What a tool returns instead of raising, for an error the tool
    itself recognises as a domain outcome (see `ToolDomainError`) rather
    than a bug. `error` is a short, stable code a caller can branch on -
    the raised exception's class name; `message` is for a human: a log
    line, or something safe to fall back to out loud.
    """

    tool: str
    error: str
    message: str


class ToolDomainError(Exception):
    """Base for an error a tool raises on purpose - a caller supplied an
    address that doesn't resolve, an entity id in the wrong shape, and so
    on. `tool_call` catches only this (and its subclasses) and turns it
    into a `ToolError`.

    Anything else - `pydantic.ValidationError`, `KeyError`, a plain typo -
    is a programming error, not a domain outcome, and `tool_call` lets it
    propagate uncaught. A polite `ToolError` hiding a real bug is a worse
    failure than a loud traceback in a test.
    """


def tool_call(
    *, name: str, agent: str
) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult | ToolError]]:
    """Decorate a tool function `fn(request, *, call_id, **kwargs) ->
    ToolResult`. The wrapped version never raises for a recognised domain
    error: anything `fn` raises is logged first (`log_tool_call`, which
    always re-raises after logging), and only a `ToolDomainError` reaching
    here is converted to a `ToolError` - anything else propagates past this
    decorator too. `call_id` is required and keyword-only with no default,
    matching `search_notes`' `entity_id` (T2.5): a call with nothing to
    attribute it to is a bug, not a valid call.
    """

    def decorator(
        fn: Callable[..., ToolResult],
    ) -> Callable[..., ToolResult | ToolError]:
        logged = log_tool_call(tool=name, agent=agent)(fn)

        @functools.wraps(fn)
        def wrapper(
            request: BaseModel, *, call_id: str, **kwargs: Any
        ) -> ToolResult | ToolError:
            try:
                return logged(request, call_id=call_id, **kwargs)
            except ToolDomainError as exc:
                return ToolError(tool=name, error=type(exc).__name__, message=str(exc))

        #: What this tool was declared as, readable without unwrapping the
        #: closure. The HTTP layer publishes it and the hard-rule-4 guard
        #: asserts on it, so neither has to keep its own table in step.
        wrapper.tool_name = name
        wrapper.tool_agent = agent

        return wrapper

    return decorator
