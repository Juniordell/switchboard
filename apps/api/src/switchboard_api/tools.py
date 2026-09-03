"""Every tool over HTTP, on one route.

`POST /tools/{name}` takes **the tool's own Pydantic request as the body** -
not an envelope around it - so the schema an agent binds and the schema the
API accepts are the same object. `GET /tools` publishes those schemas, which
is what T4.0 will bind against.

Dispatch is by signature, not by a hand-kept table: a tool that declares
`session` gets one, a tool that declares `as_of` gets the server's clock,
and `identify_caller_role`, which declares neither, gets neither. Adding a
tool to `READ_TOOLS` or `WRITE_TOOLS` is therefore the whole of exposing it.

`call_id` arrives as a header rather than in the body for the same reason it
is keyword-only in the contract: it identifies the call, it is not something
the model chooses per invocation, and it must never be confused with a tool
argument. It is required - CLAUDE.md hard rule 5.

**Responses are an envelope, requests are not.** A tool returns either a
result or a typed `ToolError`, and HTTP has to say which - so the body
carries `ok`, mirroring the `ok` in the tool call log. A `ToolError` is a
normal outcome and comes back `200`: the caller branches on the payload, as
it does in Python. A malformed body is `422`, which is the right status for
what the contract calls a defect.
"""

import datetime
import inspect
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.tools import READ_TOOLS, WRITE_TOOLS
from switchboard_core.tools.contract import ToolError

router = APIRouter(tags=["tools"])

ALL_TOOLS = {**READ_TOOLS, **WRITE_TOOLS}

_engine = None
_sessions = None


def get_session():
    """One session per request, committed on the way out.

    A write tool has already put its audit row and its state change in the
    same transaction; this is what makes them durable, and what rolls both
    back together if the handler raises.
    """
    global _engine, _sessions
    if _sessions is None:
        _engine = create_db_engine()
        _sessions = session_factory(_engine)

    session = _sessions()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class ToolDescription(BaseModel):
    name: str
    agent: str
    writes: bool
    doc: str | None
    request_schema: dict[str, Any]


class ToolEnvelope(BaseModel):
    ok: bool
    tool: str
    call_id: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def _request_model(fn) -> type[BaseModel]:
    return inspect.signature(fn).parameters["request"].annotation


@router.get("/tools")
def list_tools() -> list[ToolDescription]:
    """Every tool with its JSON Schema. This is the binding surface."""
    return [
        ToolDescription(
            name=name,
            agent=fn.tool_agent,
            writes=name in WRITE_TOOLS,
            doc=inspect.getdoc(fn),
            request_schema=_request_model(fn).model_json_schema(),
        )
        for name, fn in sorted(ALL_TOOLS.items())
    ]


@router.post("/tools/{name}")
def call_tool(
    name: str,
    body: dict[str, Any],
    x_call_id: Annotated[str, Header(alias="X-Call-Id")],
    session: Annotated[Session, Depends(get_session)],
    x_as_of: Annotated[str | None, Header(alias="X-As-Of")] = None,
) -> ToolEnvelope:
    """Invoke one tool.

    `X-As-Of` overrides the server clock for the tools that take one. It
    exists so a smoke run or an eval can be deterministic; without it the
    server's own `now()` is used, which is the real answer on a real call.
    """
    tool = ALL_TOOLS.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"no tool named {name!r}")

    try:
        request = _request_model(tool).model_validate(body)
    except ValidationError as exc:
        # include_context=False strips the raw exception objects Pydantic
        # attaches to a custom validator's error, which are not JSON
        # serialisable and would turn a clean 422 into a 500 while
        # rendering it.
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_context=False),
        ) from exc

    parameters = inspect.signature(tool).parameters
    injected: dict[str, Any] = {}
    if "session" in parameters:
        injected["session"] = session
    if "as_of" in parameters:
        injected["as_of"] = (
            datetime.datetime.fromisoformat(x_as_of)
            if x_as_of
            else datetime.datetime.now(datetime.UTC)
        )

    outcome = tool(request, call_id=x_call_id, **injected)

    if isinstance(outcome, ToolError):
        return ToolEnvelope(
            ok=False, tool=name, call_id=x_call_id, error=outcome.model_dump()
        )

    return ToolEnvelope(
        ok=True,
        tool=name,
        call_id=x_call_id,
        result=outcome.model_dump(mode="json"),
    )
