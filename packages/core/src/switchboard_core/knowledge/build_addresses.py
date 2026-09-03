"""Building `knowledge.canonical_addresses` and `knowledge.address_alias`.

Reads every row of `source.customer_addresses` (1,390), groups them by
canonical key, and writes one `canonical_addresses` row per group plus one
`address_alias` row per source `address.id`.

**Why this deletes and rebuilds rather than upserting in place**, unlike the
source loaders: `canonical_id` is `uuid5(NAMESPACE, normalised key)`, so it is
stable across runs only while the normalisation function is unchanged. It is
not, in general - abbreviation tables get new entries, a bug in
`normalize_street` gets fixed. When the function changes, every affected row
gets a *new* `canonical_id`, and upserting on that id leaves the *old* one
behind: nothing deletes a primary key an incoming batch simply stopped
producing. Caught in exactly this shape while building this module - switching
the abbreviation direction (see `address_normalize`) left 1,275 orphaned rows
in `canonical_addresses` that `address_alias` no longer pointed to, invisible
to the row-count idempotency check because that check only compares two runs
of the *same* code, never a run against the code's own prior output.

`address_alias` does not have this problem: its primary key is `address_id`,
copied verbatim from the source, so it is stable regardless of what the
normalisation function does with it, and upserting it is correct and
sufficient. `canonical_addresses` deletes first, child table before parent to
respect the foreign key, then rebuilds from scratch, inside the same
transaction as everything else `python -m switchboard_core.load` does - so a
failure mid-build leaves the previous complete state rather than a partial
rebuild. T2.2 onward should follow the same rule: any Knowledge table whose key
is derived from code rather than copied from a source id needs a rebuild, not
an upsert.

Must run after `switchboard_core.load.load_all` - it reads `source`, and
`source` is empty before that.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from switchboard_core.db.knowledge import AddressAlias, CanonicalAddress
from switchboard_core.db.source import CustomerAddress
from switchboard_core.knowledge.address_normalize import (
    CanonicalKey,
    canonical_address_key,
)
from switchboard_core.load.upsert import upsert

log = logging.getLogger(__name__)


@dataclass
class _SourceRow:
    address_id: str
    street: str | None
    street_line_2: str | None
    city: str | None
    state: str | None
    zip: str | None
    latitude: float | None
    longitude: float | None


def build_canonical_addresses(session: Session) -> dict[str, int]:
    # Child before parent: address_alias's foreign key references
    # canonical_addresses, so it must go first.
    session.execute(delete(AddressAlias))
    session.execute(delete(CanonicalAddress))

    rows = [
        _SourceRow(
            address_id=r.address_id,
            street=r.street,
            street_line_2=r.street_line_2,
            city=r.city,
            state=r.state,
            zip=r.zip,
            latitude=r.latitude,
            longitude=r.longitude,
        )
        for r in session.execute(select(CustomerAddress)).scalars()
    ]

    groups: dict[CanonicalKey, list[_SourceRow]] = defaultdict(list)
    skipped = 0
    for row in rows:
        key = canonical_address_key(row.street, row.street_line_2, row.zip)
        if key is None:
            skipped += 1
            log.warning(
                "customer_addresses.address_id=%s has no usable street; "
                "excluded from canonical_addresses and address_alias",
                row.address_id,
            )
            continue
        groups[key].append(row)

    canonical_rows: list[dict[str, object]] = []
    alias_rows: list[dict[str, object]] = []

    for key, members in groups.items():
        canonical_id = key.canonical_id()
        # Deterministic representative: the lowest address_id in the group, so
        # a re-run always picks the same display fields regardless of query
        # result order.
        representative = min(members, key=lambda m: m.address_id)
        canonical_rows.append(
            {
                "canonical_id": canonical_id,
                "street_normalized": key.street,
                "unit_normalized": key.unit,
                "zip": key.zip,
                "display_street": representative.street,
                "display_unit": representative.street_line_2,
                "display_city": representative.city,
                "display_state": representative.state,
                "latitude": representative.latitude,
                "longitude": representative.longitude,
            }
        )
        for member in members:
            alias_rows.append(
                {"address_id": member.address_id, "canonical_id": canonical_id}
            )

    return {
        "canonical_addresses": upsert(session, CanonicalAddress, canonical_rows),
        "address_alias": upsert(session, AddressAlias, alias_rows),
        "addresses_skipped_no_street": skipped,
    }


def build_all(session: Session) -> dict[str, int]:
    """Run every knowledge-layer build step, in dependency order.

    Only addresses today. T2.2-T2.4 extend this as visit_history,
    warranty_status and the rest of the Knowledge layer come online.
    """
    counts: dict[str, int] = {}
    counts.update(build_canonical_addresses(session))
    return counts
