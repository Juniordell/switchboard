"""`identify_caller_role` (Triage, logic) - homeowner, property manager,
tech, or owner.

`kind=logic` in `docs/AGENTS.md` means no data access, so the whole tool is
here rather than delegating to `knowledge/`: there is nothing to derive from
`source`. Every signal it weighs is passed in - what the caller said, plus
the fields `resolve_customer` already returned.

**`kind` is never read on its own.** 31 customers marked `homeowner` carry a
company, 14 marked `business` do not, and 48 marked `homeowner` are plainly
businesses (`docs/AGENTS.md`). It contributes, weakly, and loses to anything
the caller actually says.

**"Owner" is the company's owner, not the homeowner.** The four roles come
from `docs/AGENTS.md`, where `owner` is an internal role at Gulf Breeze Air.
"I own the house" is a homeowner; "I own the company" is the owner. The
phrase lists below keep those apart deliberately, because getting it wrong
hands an internal role to a customer.
"""

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from switchboard_core.tools.contract import ToolResult, tool_call


class CallerRole(StrEnum):
    HOMEOWNER = "homeowner"
    PROPERTY_MANAGER = "property_manager"
    TECH = "tech"
    OWNER = "owner"


#: Phrases a caller uses about themselves, weighted by how little else they
#: could mean. Matched on word boundaries against the lowercased utterance.
_UTTERANCE_SIGNALS: dict[CallerRole, tuple[tuple[str, int], ...]] = {
    CallerRole.TECH: (
        (r"i'?m (a|the) tech", 3),
        (r"i'?m (a|the) technician", 3),
        (r"this is .{0,20} in the field", 3),
        (r"\bon site for\b", 2),
        (r"\bmy truck\b", 2),
        (r"\bthe shop\b", 1),
        (r"\bwork order\b", 1),
    ),
    CallerRole.OWNER: (
        (r"i own the (company|business)", 3),
        (r"i'?m the owner of (the )?(company|business|gulf breeze)", 3),
        (r"i run the (company|business)", 3),
        (r"\bmy techs?\b", 2),
        (r"\bmy crew\b", 2),
    ),
    CallerRole.PROPERTY_MANAGER: (
        (r"property manager", 3),
        # Up to two words may sit between "I" and "manage" ("I also
        # manage", "I currently manage"). This does not read negation -
        # "I don't manage" scores as if it did - which is left to the
        # `must_ask` margin rather than a negation parser this tool has no
        # business containing.
        (r"i (?:\w+ ){0,2}manage (?:the|this|a|several|our)\b", 3),
        (r"\bmy tenants?\b", 3),
        (r"\bthe tenants?\b", 2),
        (r"\bhoa\b", 2),
        (r"\bassociation\b", 2),
        (r"\bone of (my|our) (buildings|properties|units)\b", 3),
        (r"\bthe building\b", 1),
    ),
    CallerRole.HOMEOWNER: (
        (r"\bmy house\b", 3),
        (r"\bmy home\b", 3),
        (r"i live (here|there|at)\b", 3),
        (r"i own the (house|home|place|condo)", 3),
        (r"\bmy (ac|a/c|air conditioner|furnace|unit)\b", 2),
        (r"\bmy wife\b|\bmy husband\b", 1),
    ),
}

#: A company on the record plus this many jobs is a portfolio, not a house.
#: The median customer here has 1 job; 145 is the largest.
_PORTFOLIO_JOB_COUNT = 10

#: Below this margin between the top two roles, the signals disagree and
#: `docs/AGENTS.md` is explicit that the tool asks rather than picks.
_DECISIVE_MARGIN = 2


class CallerRoleRequest(BaseModel):
    #: What the caller said. The only strong signal there is.
    utterance: str

    #: From `resolve_customer`, when identity resolved first. All optional:
    #: a caller the system has never seen still has a role.
    display_name: str | None = None
    company: str | None = None
    customer_kind: str | None = None
    job_count: int | None = None


class CallerRoleOutput(ToolResult):
    role: CallerRole | None
    confidence: Literal["high", "medium", "low"]

    #: Which signals fired, in the order they were weighed. Returned for
    #: the same reason the warranty rule returns its basis: an answer this
    #: heuristic must be auditable by whoever reads the transcript.
    basis: list[str]

    #: True when the signals disagree or none is strong enough. The agent
    #: asks; it does not pick the higher score anyway.
    must_ask: bool


def _score(request: CallerRoleRequest) -> tuple[dict[CallerRole, int], list[str]]:
    utterance = request.utterance.lower()
    scores = dict.fromkeys(CallerRole, 0)
    basis: list[str] = []

    for role, patterns in _UTTERANCE_SIGNALS.items():
        for pattern, weight in patterns:
            if re.search(pattern, utterance):
                scores[role] += weight
                basis.append(f"said {pattern!r} ({role}, +{weight})")

    has_company = bool(request.company and request.company.strip())
    many_jobs = (request.job_count or 0) >= _PORTFOLIO_JOB_COUNT

    if has_company and many_jobs:
        scores[CallerRole.PROPERTY_MANAGER] += 2
        basis.append(
            f"record: company set and {request.job_count} jobs (property_manager, +2)"
        )
    elif many_jobs:
        scores[CallerRole.PROPERTY_MANAGER] += 1
        basis.append(f"record: {request.job_count} jobs (property_manager, +1)")
    elif not has_company and request.job_count is not None:
        scores[CallerRole.HOMEOWNER] += 1
        basis.append("record: no company (homeowner, +1)")

    if request.customer_kind:
        basis.append(
            f"record: kind={request.customer_kind!r} (noted, not scored - "
            f"unreliable in this dataset)"
        )

    return scores, basis


@tool_call(name="identify_caller_role", agent="Triage")
def identify_caller_role(
    request: CallerRoleRequest, *, call_id: str
) -> CallerRoleOutput:
    """Weigh what the caller said against what the record says, and refuse
    to pick when they disagree.

    Takes no `session`: it reads nothing. That is what makes it `logic` in
    the tool table, and what lets the harness exercise it with no database
    at all.
    """
    scores, basis = _score(request)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top_role, top_score), (_, runner_up_score) = ranked[0], ranked[1]

    if top_score == 0:
        return CallerRoleOutput(
            role=None,
            confidence="low",
            basis=basis or ["no signal in the utterance and no record fields"],
            must_ask=True,
        )

    margin = top_score - runner_up_score
    if margin < _DECISIVE_MARGIN:
        return CallerRoleOutput(
            role=top_role,
            confidence="low",
            basis=[
                *basis,
                f"margin {margin} below {_DECISIVE_MARGIN}: signals disagree",
            ],
            must_ask=True,
        )

    return CallerRoleOutput(
        role=top_role,
        confidence="high" if top_score >= 3 else "medium",
        basis=basis,
        must_ask=False,
    )
