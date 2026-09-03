"""Source tables: ``data/*.jsonl`` mirrored row for row.

Nothing in this package is computed. Every field present in the source is
represented, including ``invoice_taxes``, which is empty in this export.

Where ``data/README.md`` disagrees with the files themselves, the files win and
the divergence is recorded in docs/DATA.md as a documented trap.
"""

from switchboard_core.db.source.customers import (
    Customer,
    CustomerAddress,
    CustomerTag,
)
from switchboard_core.db.source.employees import Employee
from switchboard_core.db.source.invoices import (
    INVOICE_ITEM_TYPES,
    INVOICE_STATUSES,
    Invoice,
    InvoiceDiscount,
    InvoiceItem,
    InvoicePayment,
    InvoiceTax,
)
from switchboard_core.db.source.jobs import (
    WORK_STATUSES,
    Job,
    JobEmployee,
    JobTag,
    Note,
)

__all__ = [
    "INVOICE_ITEM_TYPES",
    "INVOICE_STATUSES",
    "WORK_STATUSES",
    "Customer",
    "CustomerAddress",
    "CustomerTag",
    "Employee",
    "Invoice",
    "InvoiceDiscount",
    "InvoiceItem",
    "InvoicePayment",
    "InvoiceTax",
    "Job",
    "JobEmployee",
    "JobTag",
    "Note",
]
