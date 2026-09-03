"""The Extractor: structured facts out of a finished transcript.

`docs/ARCHITECTURE.md` names what it produces - what was asked, what was
promised, which entities were resolved, what changed. Those four are the
shape because they are what the Reviewer scores and what a human reads
before deciding whether to act.

It reads the transcript **and the tool calls**. A promise the agent made in
words is only half the record; whether a tool actually wrote anything is the
other half, and the interesting failure is exactly when those two disagree.
"""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_api.async_agents.model import DEFAULT_MODEL, ask_for_json

SYSTEM = """You read a finished phone call for an HVAC company and return \
JSON. Report only what the transcript and the tool calls show. Never infer a \
fact that neither contains.

Return exactly this shape:
{
  "asked": [string],        // what the caller wanted, in their terms
  "promised": [string],     // anything the agent committed to, verbatim where possible
  "resolved": {             // entities the tools actually resolved
     "canonical_id": string|null,
     "customer_id": string|null,
     "job_ids": [string]
  },
  "changed": [string],      // writes that actually happened, per the tool calls
  "unresolved": [string],   // what the caller wanted that was never answered
  "notes": string           // one sentence a human would want to read first
}

A promise with no corresponding write belongs in "promised" and not in \
"changed". That gap is the point."""


def _transcript(session: Session, call_id: str) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                "SELECT seq, role, text, agent FROM ops.transcript_turns "
                "WHERE call_id = :c ORDER BY seq"
            ),
            {"c": call_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def _tool_calls(session: Session, call_id: str) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                "SELECT agent, tool, args, result_rows, ok FROM ops.tool_calls "
                "WHERE call_id = :c ORDER BY created_at"
            ),
            {"c": call_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def extract(session: Session, call_id: str, **model_kwargs) -> dict[str, Any]:
    """Read the call, ask the model, store the answer whole.

    Stored as returned. A summary reshaped on the way in cannot be audited
    against what the model actually said.
    """
    turns = _transcript(session, call_id)
    tools = _tool_calls(session, call_id)
    if not turns and not tools:
        raise ValueError(f"call {call_id!r} has no transcript and no tool calls")

    facts = ask_for_json(
        SYSTEM,
        json.dumps({"transcript": turns, "tool_calls": tools}, default=str),
        **model_kwargs,
    )

    session.execute(
        text(
            "INSERT INTO ops.extractions (call_id, facts, model) "
            "VALUES (:c, CAST(:f AS jsonb), :m) "
            "ON CONFLICT (call_id) DO UPDATE SET facts = EXCLUDED.facts, "
            "model = EXCLUDED.model"
        ),
        {
            "c": call_id,
            "f": json.dumps(facts),
            "m": model_kwargs.get("model", DEFAULT_MODEL),
        },
    )
    return facts
