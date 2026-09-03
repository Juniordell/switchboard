"""Core tools as LiveKit function tools.

One implementation, bound three ways: the FastAPI layer (T3.5), the T4.0
text client, and here. All three read the same Pydantic request models, so
the schema the voice agent offers is the schema the harness graded.

The bridge is `raw_schema`, not a hand-written wrapper per tool. LiveKit
accepts a JSON Schema directly, and `model_json_schema()` already produces
one, so adding a tool to `READ_TOOLS` or `WRITE_TOOLS` is again the whole of
exposing it - no signature to restate, nothing to drift.

The exclusion list is the same one the text client uses, imported rather
than restated: a tool the harness never offered the model must not appear
in production either, or Layer 1 graded a different agent than the one
that answers the phone.

What the bridge injects is what the model must not choose: the database
session, the clock, and the `call_id`. `call_id` is the LiveKit room name,
so every row in `ops.write_audit` and every line in the tool call log traces
back to a specific call (CLAUDE.md hard rule 5).
"""

import datetime
import inspect
import json
import logging
from typing import Any

from livekit.agents import RunContext, function_tool
from pydantic import ValidationError

from switchboard_agent.text_client import NOT_MODEL_SELECTABLE
from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.tools import CONTROL_TOOLS, READ_TOOLS, WRITE_TOOLS

log = logging.getLogger("switchboard_agent.tools")

#: Layer 3b asserts **which agent handled which turn**. The tool call log
#: records the agent a tool was *declared* on (T3.1); this records the agent
#: that actually made the call, which is a different question and the only
#: one a permissions boundary can be checked against.
turns = logging.getLogger("switchboard_agent.turns")

ALL_TOOLS = {**READ_TOOLS, **WRITE_TOOLS, **CONTROL_TOOLS}

_engine = None
_sessions = None


def _session():
    global _engine, _sessions
    if _sessions is None:
        _engine = create_db_engine()
        _sessions = session_factory(_engine)
    return _sessions()


def _request_model(fn):
    return inspect.signature(fn).parameters["request"].annotation


def call_core_tool(fn, request, *, call_id: str, handled_by: str):
    """Run one core tool, injecting what the model must not choose.

    The single place a core tool is invoked from the agent: the raw-schema
    bridge below goes through it, and so does the booking task, so the
    session handling, the clock and the turn record cannot diverge between
    a tool the model picked and one the task group calls directly.
    """
    turns.info(
        json.dumps({"call_id": call_id, "agent": handled_by, "tool": fn.tool_name})
    )
    parameters = inspect.signature(fn).parameters
    injected: dict[str, Any] = {}
    session = _session() if "session" in parameters else None
    if session is not None:
        injected["session"] = session
    if "as_of" in parameters:
        injected["as_of"] = datetime.datetime.now(datetime.UTC)

    try:
        outcome = fn(request, call_id=call_id, **injected)
        if session is not None:
            session.commit()
        return outcome
    except Exception:
        if session is not None:
            session.rollback()
        raise
    finally:
        if session is not None:
            session.close()


def _build(name: str, fn, call_id: str, handled_by: str):
    schema = _request_model(fn).model_json_schema()

    async def run(raw_arguments: dict[str, Any], context: RunContext) -> str:
        try:
            request = _request_model(fn).model_validate(raw_arguments)
        except ValidationError as exc:
            # The model filled the arguments wrong. Handing the error back
            # lets it correct itself on the next turn, which is the whole
            # reason tool-arg validation exists in an LLM loop.
            return f"invalid arguments for {name}: {exc.errors(include_url=False)}"

        outcome = call_core_tool(fn, request, call_id=call_id, handled_by=handled_by)
        # A typed ToolError is an outcome the agent speaks around, not a
        # crash. It is already logged with ok=false.
        return outcome.model_dump_json()

    run.__name__ = name
    return function_tool(
        run,
        raw_schema={
            "name": name,
            "description": (inspect.getdoc(fn) or "").split("\n\n")[0],
            "parameters": schema,
        },
    )


def build_tools_for(agent_name: str, tool_names: list[str], call_id: str) -> list:
    """Bind exactly the named tools, recording which agent holds them.

    `switchboard_agent.agents` validates `tool_names` against the
    permissions boundary at class-definition time, so by the time a name
    reaches here it has already been checked. Nothing is filtered again -
    a second check here would suggest the first one is not trusted.
    """
    return [
        _build(name, ALL_TOOLS[name], call_id, agent_name)
        for name in tool_names
        if name not in NOT_MODEL_SELECTABLE
    ]


def build_tools(call_id: str, *, include_writes: bool = True) -> list:
    """Every tool, for the single-agent shape T5.1 used.

    Kept because the T5.1 tests and the smoke path still describe an agent
    that holds everything. The split agents use `build_tools_for`.
    """
    registry = {
        **READ_TOOLS,
        **(WRITE_TOOLS if include_writes else {}),
        **CONTROL_TOOLS,
    }
    return [
        _build(name, fn, call_id, "single")
        for name, fn in sorted(registry.items())
        if name not in NOT_MODEL_SELECTABLE
    ]
