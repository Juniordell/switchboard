"""The Knowledge layer: derived at load, typed SQL tools, no model in the path.

See `docs/ARCHITECTURE.md`. Each submodule pairs a pure normalisation/derivation
function with a build step that writes `switchboard_core.db.knowledge` tables
from `source`, and a tool function agents call at request time.
"""

from switchboard_core.knowledge.build_addresses import (
    build_all,
    build_canonical_addresses,
)
from switchboard_core.knowledge.resolve_address import AMBIGUOUS_GAP as AMBIGUOUS_GAP
from switchboard_core.knowledge.resolve_address import (
    CONFIDENCE_THRESHOLD as CONFIDENCE_THRESHOLD,
)
from switchboard_core.knowledge.resolve_address import (
    AddressCandidate,
    ResolveAddressResult,
)
from switchboard_core.knowledge.resolve_address import (
    resolve_address as resolve_address,
)

__all__ = [
    "AMBIGUOUS_GAP",
    "CONFIDENCE_THRESHOLD",
    "AddressCandidate",
    "ResolveAddressResult",
    "build_all",
    "build_canonical_addresses",
    "resolve_address",
]
