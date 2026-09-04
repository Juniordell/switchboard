"""The Reviewer: score the Extractor, and file what a human should see.

`docs/ARCHITECTURE.md`: anything below threshold becomes a proposal for a
human rather than a write, tagged `ai-ready-for-review`.

**That tag is not invented.** It is on 137 jobs in the loaded data, and 135
of those are completed work - so in this office the tag already means
"finished, and somebody should look at it", not "approve this before it
happens". What the Reviewer files reads the same way: the call is over, and
here is what deserves a second pair of eyes.

Two things put an item in the queue, and only one of them is the score.
A promise the agent made with no write behind it goes in **regardless of
confidence**, because the model's confidence about its own summary says
nothing about whether the office owes somebody a callback.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_api.async_agents.model import ask_for_json

#: The tag the office already uses.
REVIEW_TAG = "ai-ready-for-review"

#: Below this, the extraction goes to a human. `docs/HARNESS.md` uses 0.02
#: as a tolerance on judged metrics; this is a different number for a
#: different job - how sure the Reviewer is that the summary is right.
CONFIDENCE_THRESHOLD = 0.75

SYSTEM = """You are checking another model's summary of a finished phone \
call against the call itself. Return JSON:

{
  "confidence": number,     // 0 to 1, how well the summary matches the call
  "problems": [string],     // anything the summary claims the call does not show
  "missed": [string],       // anything important in the call the summary omits
  "headline": string        // one line naming what a human should check first
}

Be strict about two things. A claim the transcript does not support is a \
problem even if it sounds plausible. A promise made to the caller that no \
tool call carried out is something a human must see, and you should say so \
in "headline" when it happens.

`writes` is the audit trail of what the agent actually did - every \
customer-record write, with the caller's own words that authorised it. A \
promise covered by a write there was kept: do not report it as unconfirmed \
because the transcript alone left you unsure."""


def _writes(session: Session, call_id: str) -> list[dict[str, Any]]:
    """What the agent actually wrote on this call.

    `ops.write_audit` is the record of every customer-record write, with
    the caller's own words in `spoken_confirmation`. The Reviewer used to
    be shown the transcript and the Extractor's summary and nothing else,
    so it was reasoning about whether a booking happened from the words
    alone - and said a real, audited booking "was not confirmed".
    """
    return [
        dict(row)
        for row in session.execute(
            text(
                "SELECT tool, action, job_id, new_values, spoken_confirmation "
                "FROM ops.write_audit WHERE call_id = :c ORDER BY created_at"
            ),
            {"c": call_id},
        )
        .mappings()
        .all()
    ]


def _open_promises(facts: dict[str, Any], writes: list[dict[str, Any]]) -> list[str]:
    """Promises with nothing written behind them.

    `changed` is the Extractor's own list, compared as whole strings
    deliberately: a fuzzy match would decide on the office's behalf that a
    promise was kept, which is exactly the call a human is being asked to
    make.

    But a promise is only *open* if the call wrote nothing at all. A real
    booking - `book_job`, audited, a row in `ops.booked_jobs` - was flagged
    as unbacked because the Extractor phrased `changed` differently from
    `promised`, and a queue that cries wolf on the calls that went right is
    a queue the office stops reading.

    The limitation is deliberate and worth naming: when a call both wrote
    something and promised something else, this cannot tell which promise
    the write covers. That is the judgement the model is now given the
    writes to make, and the reason its `problems` still reach the queue.
    """
    changed = {c.strip().lower() for c in facts.get("changed") or []}
    unmatched = [
        promise
        for promise in facts.get("promised") or []
        if promise.strip().lower() not in changed
    ]
    return [] if writes else unmatched


def review(
    session: Session,
    call_id: str,
    facts: dict[str, Any],
    *,
    threshold: float = CONFIDENCE_THRESHOLD,
    **model_kwargs,
) -> dict[str, Any]:
    """Score the extraction and file it if it needs a human.

    Returns the verdict. `queued` says whether an item was written.
    """
    turns = (
        session.execute(
            text(
                "SELECT seq, role, text FROM ops.transcript_turns "
                "WHERE call_id = :c ORDER BY seq"
            ),
            {"c": call_id},
        )
        .mappings()
        .all()
    )

    writes = _writes(session, call_id)

    verdict = ask_for_json(
        SYSTEM,
        json.dumps(
            {
                "summary": facts,
                "transcript": [dict(t) for t in turns],
                # What the agent actually did, not what it said it did.
                "writes": writes,
            },
            default=str,
        ),
        **model_kwargs,
    )

    confidence = float(verdict.get("confidence", 0.0))
    promises = _open_promises(facts, writes)

    reasons = []
    if confidence < threshold:
        reasons.append(f"confidence {confidence:.2f} below {threshold:.2f}")
    if promises:
        reasons.append(f"{len(promises)} promise(s) with no write behind them")

    verdict["open_promises"] = promises
    verdict["queued"] = bool(reasons)
    verdict["reasons"] = reasons

    if reasons:
        session.execute(
            text(
                "INSERT INTO ops.review_queue "
                "(id, call_id, kind, status, title, payload) "
                "VALUES (:id, :c, :kind, 'open', :title, CAST(:p AS jsonb))"
            ),
            {
                "id": f"rev_{uuid.uuid4().hex}",
                "c": call_id,
                "kind": REVIEW_TAG,
                "title": verdict.get("headline") or "Call needs review",
                "p": json.dumps(
                    {
                        "reasons": reasons,
                        "confidence": confidence,
                        "problems": verdict.get("problems") or [],
                        "missed": verdict.get("missed") or [],
                        "open_promises": promises,
                        "facts": facts,
                    }
                ),
            },
        )

    return verdict
