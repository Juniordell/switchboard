"""Knowledge tables: derived at load, never loaded verbatim.

Nothing here comes from `data/` directly. Every row traces back to a `source`
row through a foreign key or a build step that reads one.
"""

from switchboard_core.db.knowledge.addresses import AddressAlias, CanonicalAddress
from switchboard_core.db.knowledge.install_dates import InstallDate

__all__ = ["AddressAlias", "CanonicalAddress", "InstallDate"]
