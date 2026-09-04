"""Id types that refuse the wrong kind of id.

On a real call the agent handed `handoff_to_service` a **customer** id as
the `canonical_id`, and nothing objected: `jobs_at_canonical_address` simply
found nothing, and the caller was told there was no history. A wrong answer
that looks like an empty one is the worst shape a bug can take here.

The prefixes were already a convention - `cadr_`, `cus_`, `job_` - and
`search_notes` already enforced its own. These make the convention a type,
so a request carrying the wrong kind of id cannot be constructed at all,
and the model gets a validation error it can correct on the next turn
rather than a confident empty answer.
"""

from typing import Annotated

from pydantic import AfterValidator

#: Agent bookings use `job_ops_...`, which still starts with `job_`.
_PREFIXES = {
    "canonical id": "cadr_",
    "customer id": "cus_",
    "job id": "job_",
}


def _checker(kind: str):
    prefix = _PREFIXES[kind]

    def check(value: str) -> str:
        if not value.startswith(prefix):
            raise ValueError(
                f"{value!r} is not a {kind}: expected one starting {prefix!r}"
            )
        return value

    return check


CanonicalId = Annotated[str, AfterValidator(_checker("canonical id"))]
CustomerId = Annotated[str, AfterValidator(_checker("customer id"))]
JobId = Annotated[str, AfterValidator(_checker("job id"))]
