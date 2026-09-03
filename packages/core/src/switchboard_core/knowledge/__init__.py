"""The Knowledge layer: derived at load, typed SQL tools, no model in the path.

See `docs/ARCHITECTURE.md`. Each submodule pairs a pure normalisation/derivation
function with a build step that writes `switchboard_core.db.knowledge` tables
from `source`, and a tool function agents call at request time.
"""

from switchboard_core.knowledge.build_addresses import (
    build_all,
    build_canonical_addresses,
)

__all__ = [
    "build_all",
    "build_canonical_addresses",
]
