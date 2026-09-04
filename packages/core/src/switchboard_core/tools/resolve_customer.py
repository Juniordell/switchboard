"""`resolve_customer` (Triage, SQL) - a spoken name or a resolved address to
customer candidates.

Returns names, `kind` and a job count. No history, no balance, no note, no
appointment: everything that describes work done or work booked lives behind
the Triage handoff (`docs/ARCHITECTURE.md`).
"""

from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from switchboard_core.knowledge.resolve_customer import ResolveCustomerResult
from switchboard_core.knowledge.resolve_customer import (
    resolve_customer as _resolve_customer,
)
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.ids import CanonicalId


class ResolveCustomerRequest(BaseModel):
    #: What the caller said their name or company was.
    name: str | None = None

    #: A `cadr_...` already resolved by `resolve_address`, if the caller
    #: gave an address first.
    canonical_id: CanonicalId | None = None

    @model_validator(mode="after")
    def _needs_something_to_go_on(self) -> "ResolveCustomerRequest":
        if not self.name and not self.canonical_id:
            raise ValueError("resolve_customer needs a name or a canonical_id")
        return self


class ResolveCustomerOutput(ToolResult):
    customer: ResolveCustomerResult

    def result_rows(self) -> int:
        return len(self.customer.candidates)


@tool_call(kind="SQL", name="resolve_customer", agent="Triage")
def resolve_customer(
    request: ResolveCustomerRequest, *, call_id: str, session: Session
) -> ResolveCustomerOutput:
    """`must_ask` is the tool's verdict on whether the agent may proceed.
    It is true more often than `resolve_address`'s is, because customer
    names in this dataset repeat: two different customers are both called
    "Starfish Hospitality", and "Lighthouse" is a name as well as the start
    of two longer ones.
    """
    return ResolveCustomerOutput(
        customer=_resolve_customer(
            session, name=request.name, canonical_id=request.canonical_id
        )
    )
