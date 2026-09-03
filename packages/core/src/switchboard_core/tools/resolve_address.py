"""`resolve_address` (Triage, SQL) - spoken street to canonical candidates.

Returns address candidates and nothing else: no history, no balance, no
appointment. That is the Triage boundary in `docs/ARCHITECTURE.md`, and it
holds here by construction, since the underlying query only ever reads
`knowledge.canonical_addresses`.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from switchboard_core.knowledge.resolve_address import ResolveAddressResult
from switchboard_core.knowledge.resolve_address import (
    resolve_address as _resolve_address,
)
from switchboard_core.tools.contract import ToolResult, tool_call


class ResolveAddressRequest(BaseModel):
    spoken_address: str


class ResolveAddressOutput(ToolResult):
    address: ResolveAddressResult

    def result_rows(self) -> int:
        return len(self.address.candidates)


@tool_call(name="resolve_address", agent="Triage")
def resolve_address(
    request: ResolveAddressRequest, *, call_id: str, session: Session
) -> ResolveAddressOutput:
    """Up to 3 candidates with scores and `canonical_id`, never a source
    `address_id`. `must_ask` is the tool's own verdict on whether the agent
    may proceed - below 0.55, or within 0.05 of the runner-up, it must ask.
    An empty or unusable street is not an error: it comes back as no
    candidates and `must_ask=True`, which is the same instruction to the
    agent either way.
    """
    return ResolveAddressOutput(
        address=_resolve_address(session, request.spoken_address)
    )
