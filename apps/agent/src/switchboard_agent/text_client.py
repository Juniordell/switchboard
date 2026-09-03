"""The minimal text tool client (T4.0).

Schemas in, an utterance in, the tool calls the model chose out. No audio,
no LiveKit session, no `Agent` class, no TTS - none of that exists until
Phase 5, and Layer 1 of `docs/HARNESS.md` needs something that chooses tools
before then.

**It does not execute anything.** Layer 1 asserts which tools were selected
and with what arguments; running them is the runner's business (T4.2), and
keeping execution out of here is what lets a golden case assert on a
`book_job` call without booking anything.

Phase 5 replaces this module with the real cascade agent. The seam is
`choose_tools(utterance) -> list[ToolCall]`: as long as that signature
holds, the runner does not change.
"""

import inspect
import json
import os
from typing import Any

import httpx
from pydantic import BaseModel

from switchboard_core.tools import READ_TOOLS, WRITE_TOOLS

CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("HARNESS_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT_SECONDS = 30.0

ALL_TOOLS = {**READ_TOOLS, **WRITE_TOOLS}

#: Only the rules that change which tool gets picked. The full instructions
#: are Phase 5's; what Layer 1 grades is selection, and a prompt longer than
#: the thing it is testing would be grading the prompt instead.
SYSTEM_PROMPT = """You are the front desk for Gulf Breeze Air, an HVAC company.
Choose tools to answer the caller. Rules:
- Dates, counts, schedules, balances and warranty come from SQL tools, never
  from note search.
- Resolve the address or the customer before reading any job, invoice, note
  or schedule data.
- search_notes needs a resolved entity id. Never call it first.
- Try search_notes before web_search for anything this company would know.
- Never write without the caller's spoken confirmation in hand."""


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


def tool_schemas() -> list[dict[str, Any]]:
    """Every tool as an OpenAI function definition, straight from the same
    Pydantic models the HTTP layer validates against."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": (inspect.getdoc(fn) or "").split("\n\n")[0],
                "parameters": inspect.signature(fn)
                .parameters["request"]
                .annotation.model_json_schema(),
            },
        }
        for name, fn in sorted(ALL_TOOLS.items())
    ]


def choose_tools(
    utterance: str,
    *,
    model: str = DEFAULT_MODEL,
    system: str = SYSTEM_PROMPT,
    client: httpx.Client | None = None,
) -> list[ToolCall]:
    """The tool calls the model asked for, in the order it asked for them."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": utterance},
        ],
        "tools": tool_schemas(),
        "tool_choice": "auto",
    }
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set; the text client needs it")
    headers = {"Authorization": f"Bearer {key}"}

    http = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = http.post(CHAT_URL, json=payload, headers=headers)
    finally:
        if client is None:
            http.close()
    response.raise_for_status()

    chosen = response.json()["choices"][0]["message"].get("tool_calls") or []
    return [
        ToolCall(
            name=call["function"]["name"],
            arguments=json.loads(call["function"]["arguments"] or "{}"),
        )
        for call in chosen
    ]
