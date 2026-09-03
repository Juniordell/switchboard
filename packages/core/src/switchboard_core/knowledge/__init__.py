"""The Knowledge layer: derived at load, typed SQL tools, no model in the path.

See `docs/ARCHITECTURE.md`. Each submodule pairs a pure normalisation/derivation
function with a build step that writes `switchboard_core.db.knowledge` tables
from `source`, and a tool function agents call at request time.
"""

from sqlalchemy.orm import Session

from switchboard_core.knowledge.build_addresses import (
    build_canonical_addresses,
)
from switchboard_core.knowledge.build_install_dates import (
    INSTALL_DESCRIPTION_PREFIXES as INSTALL_DESCRIPTION_PREFIXES,
)
from switchboard_core.knowledge.build_install_dates import (
    build_install_dates,
)
from switchboard_core.knowledge.callback_chain import (
    ALL_CALLBACK_TAGS as ALL_CALLBACK_TAGS,
)
from switchboard_core.knowledge.callback_chain import (
    INSTALL_CALLBACK_TAGS as INSTALL_CALLBACK_TAGS,
)
from switchboard_core.knowledge.callback_chain import (
    SERVICE_CALLBACK_TAG as SERVICE_CALLBACK_TAG,
)
from switchboard_core.knowledge.callback_chain import (
    find_callback_source as find_callback_source,
)
from switchboard_core.knowledge.customer_balance import CustomerBalance
from switchboard_core.knowledge.customer_balance import (
    get_customer_balance as get_customer_balance,
)
from switchboard_core.knowledge.job_address import job_canonical_id as job_canonical_id
from switchboard_core.knowledge.job_address import (
    jobs_at_canonical_address as jobs_at_canonical_address,
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
from switchboard_core.knowledge.visit_history import VisitRow
from switchboard_core.knowledge.visit_history import (
    get_visit_history as get_visit_history,
)
from switchboard_core.knowledge.warranty_level_3 import (
    LABOR_WARRANTY_MONTHS as LABOR_WARRANTY_MONTHS,
)
from switchboard_core.knowledge.warranty_level_3 import Level3Result, Level3Verdict
from switchboard_core.knowledge.warranty_level_3 import (
    evaluate_level_3 as evaluate_level_3,
)
from switchboard_core.knowledge.warranty_notes import (
    NoteWarrantyClaim,
)
from switchboard_core.knowledge.warranty_notes import (
    classify_note_warranty_term as classify_note_warranty_term,
)
from switchboard_core.knowledge.warranty_status import (
    WarrantyConfidence,
    WarrantyCoverage,
    WarrantyEvidence,
    WarrantyStatusResult,
)
from switchboard_core.knowledge.warranty_status import (
    evaluate_warranty_status as evaluate_warranty_status,
)


def build_all(session: Session) -> dict[str, int]:
    """Run every knowledge-layer build step, in dependency order.

    Addresses before install dates: the latter looks up canonical_id against
    knowledge.canonical_addresses, which the former just rebuilt.
    """
    counts: dict[str, int] = {}
    counts.update(build_canonical_addresses(session))
    counts.update(build_install_dates(session))
    return counts


__all__ = [
    "ALL_CALLBACK_TAGS",
    "AMBIGUOUS_GAP",
    "CONFIDENCE_THRESHOLD",
    "INSTALL_CALLBACK_TAGS",
    "INSTALL_DESCRIPTION_PREFIXES",
    "LABOR_WARRANTY_MONTHS",
    "SERVICE_CALLBACK_TAG",
    "AddressCandidate",
    "CustomerBalance",
    "Level3Result",
    "Level3Verdict",
    "NoteWarrantyClaim",
    "ResolveAddressResult",
    "VisitRow",
    "WarrantyConfidence",
    "WarrantyCoverage",
    "WarrantyEvidence",
    "WarrantyStatusResult",
    "build_all",
    "build_canonical_addresses",
    "build_install_dates",
    "classify_note_warranty_term",
    "evaluate_level_3",
    "evaluate_warranty_status",
    "find_callback_source",
    "get_customer_balance",
    "get_visit_history",
    "job_canonical_id",
    "jobs_at_canonical_address",
    "resolve_address",
]
