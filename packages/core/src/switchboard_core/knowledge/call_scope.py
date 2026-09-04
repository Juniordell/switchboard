"""Whose property a caller may be told about.

`docs/AGENTS.md`: **no answer about another customer's property, ever,
regardless of what the caller claims.** That was a line in a prompt until a
real call walked straight through it - the caller was resolved at 8504 E
Old Mangrove (Starfish Hospitality), said "that's my neighbor" about
another street out loud, and the agent read out the visit history of 9800
Seahorse Ridge (Lighthouse Hospitality).

The rule cannot be "only the address they gave": one customer legitimately
owns several. 38 canonical addresses in this dataset are shared by more
than one customer, and a property manager may ask about any of theirs. So
the boundary is the **customer**, not the address: another address is in
scope when it shares a customer with the identity the call established.

This module answers that question against the database. Enforcing it is
the tool bridge's job, the same way `__init_subclass__` enforces the write
boundary - a rule the agent cannot decline to apply.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

_CUSTOMERS_AT = text(
    """
    SELECT DISTINCT j.customer_id
    FROM knowledge.address_alias a
    JOIN source.jobs j ON j.address_id = a.address_id
    WHERE a.canonical_id = :canonical_id AND j.customer_id IS NOT NULL
    """
)


def customers_at(session: Session, canonical_id: str) -> set[str]:
    """Every customer with a job at this canonical address."""
    return set(session.scalars(_CUSTOMERS_AT, {"canonical_id": canonical_id}).all())


def in_scope(
    session: Session,
    *,
    canonical_id: str,
    scope_canonical_ids: set[str],
    scope_customer_ids: set[str],
) -> bool:
    """May this call be told about `canonical_id`?

    An address already established on the call is in scope by definition.
    Any other address is in scope only if a customer of it is a customer of
    the call - which is what makes a second property of the same owner
    reachable and a neighbour's not.

    An address nobody has ever had a job at has no customer to compare, and
    is refused: there is nothing to tell about it anyway, and the open case
    is the dangerous one.
    """
    if canonical_id in scope_canonical_ids:
        return True

    here = customers_at(session, canonical_id)
    if not here:
        return False

    if here & scope_customer_ids:
        return True

    for established in scope_canonical_ids:
        if here & customers_at(session, established):
            return True
    return False
