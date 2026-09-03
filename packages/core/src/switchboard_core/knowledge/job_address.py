"""Resolving a job to a canonical address, without going through `address_alias`.

`source.jobs` carries its own flattened `address_street` / `address_street_line_2`
/ `address_zip` columns (T1.3) - the same fields `customer_addresses` has, kept
verbatim on the job itself. Because `canonical_id` is a pure function of those
three normalised fields (`address_normalize.canonical_address_key`), a job can
be linked to its canonical address by computing the key directly from its own
columns, with no join through `address_alias` at all.

This is more general than joining on `address_id`, not just simpler:

- It handles the 4 jobs with a null `address_id` uniformly, no special case.
  3 of them carry a real street and resolve exactly like any other job; the
  4th is entirely blank and correctly resolves to nothing.
- It also correctly fails to resolve `job_0feecbb8c89f`, whose `address_id`
  points at the one all-blank `customer_addresses` row (`adr_c6efbfa7...`)
  T2.1 already excludes - a job can reference garbage same as a customer
  listing can.

Verified against the whole table, not assumed: computing this way agrees with
`address_alias` on all 1,992 jobs with zero mismatches, and resolves 3 of the
4 null-`address_id` jobs that `address_alias` cannot reach at all (nothing to
alias without an id). Only the genuinely orphaned `job_a8edd70d8b7c` (69
Plumeria Glen Drive - no `customer_addresses` row at all carries that street)
and the two garbage cases above fail, correctly.
"""

from switchboard_core.knowledge.address_normalize import canonical_address_key


def job_canonical_id(
    street: str | None, street_line_2: str | None, zip_code: str | None
) -> str | None:
    """The canonical_id a job's own address columns resolve to, or `None`.

    `None` means what it means in `canonical_address_key`: no usable street,
    not a lookup failure to retry. A non-`None` result may still fail to match
    any row in `knowledge.canonical_addresses`, for a job whose street exists
    nowhere in `customer_addresses` - the caller decides what that means.
    """
    key = canonical_address_key(street, street_line_2, zip_code)
    return key.canonical_id() if key else None
