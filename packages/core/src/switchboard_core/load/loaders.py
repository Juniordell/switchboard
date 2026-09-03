"""Loaders for the four source files.

Each loader reads one ``.jsonl`` and upserts every table that file feeds. No
field is dropped, including ones empty in this export. Money stays in cents.

The schema carries no CHECK constraints on ``work_status``, ``invoice.status``
or ``item.type``, so that a value this export has never seen loads rather than
failing the build. The warnings below are the condition of that freedom: an
unknown value is logged with a count and then loaded. Absence of a constraint
must not become absence of visibility.
"""

import logging
from collections import Counter
from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from switchboard_core.db.source import (
    INVOICE_ITEM_TYPES,
    INVOICE_STATUSES,
    WORK_STATUSES,
    Customer,
    CustomerAddress,
    CustomerTag,
    Employee,
    Invoice,
    InvoiceDiscount,
    InvoiceItem,
    InvoicePayment,
    InvoiceTax,
    Job,
    JobEmployee,
    JobTag,
    Note,
)
from switchboard_core.load.reader import (
    CUSTOMERS,
    EMPLOYEES,
    INVOICES,
    JOBS,
    read_jsonl,
    timestamp,
)
from switchboard_core.load.upsert import upsert

log = logging.getLogger(__name__)


def warn_unknown(field: str, values: Iterable[str], known: frozenset[str]) -> None:
    """Log every value outside ``known``, with counts. Never raises."""
    unknown = Counter(value for value in values if value not in known)
    if not unknown:
        return
    detail = ", ".join(
        f"{value!r} x{count}" for value, count in sorted(unknown.items())
    )
    log.warning(
        "%s: %d row(s) carry a value outside the known set, loaded anyway: %s",
        field,
        sum(unknown.values()),
        detail,
    )


def load_employees(session: Session) -> dict[str, int]:
    rows = [
        {
            "id": record["id"],
            "first_name": record["first_name"],
            "last_name": record["last_name"],
            "role": record["role"],
            "jobs": record["jobs"],
        }
        for record in read_jsonl(EMPLOYEES)
    ]
    return {"employees": upsert(session, Employee, rows)}


def load_customers(session: Session) -> dict[str, int]:
    customers: list[dict[str, Any]] = []
    tags: list[dict[str, Any]] = []
    addresses: list[dict[str, Any]] = []

    for record in read_jsonl(CUSTOMERS):
        customers.append(
            {
                "id": record["id"],
                "first_name": record["first_name"],
                "last_name": record["last_name"],
                "company": record["company"],
                "kind": record["kind"],
                "job_count": record["job_count"],
                "first_job": timestamp(record["first_job"]),
                "last_job": timestamp(record["last_job"]),
            }
        )
        for position, tag in enumerate(record["tags"]):
            tags.append({"customer_id": record["id"], "position": position, "tag": tag})
        for position, address in enumerate(record["addresses"]):
            addresses.append(
                {
                    "customer_id": record["id"],
                    "address_id": address["id"],
                    "position": position,
                    "street": address["street"],
                    "street_line_2": address["street_line_2"],
                    "city": address["city"],
                    "state": address["state"],
                    "zip": address["zip"],
                    "latitude": address["latitude"],
                    "longitude": address["longitude"],
                }
            )

    return {
        "customers": upsert(session, Customer, customers),
        "customer_tags": upsert(session, CustomerTag, tags),
        "customer_addresses": upsert(session, CustomerAddress, addresses),
    }


def load_jobs(session: Session) -> dict[str, int]:
    jobs: list[dict[str, Any]] = []
    tags: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    statuses: list[str] = []

    for record in read_jsonl(JOBS):
        schedule = record["schedule"]
        stamps = record["work_timestamps"]
        address = record["address"]
        statuses.append(record["work_status"])

        jobs.append(
            {
                "id": record["id"],
                # The source calls this invoice_number. It is the job number,
                # and the source name stops here. CLAUDE.md hard rule 8.
                "job_number": record["invoice_number"],
                "description": record["description"],
                "work_status": record["work_status"],
                "lead_source": record["lead_source"],
                "total_amount": record["total_amount"],
                "outstanding_balance": record["outstanding_balance"],
                "created_at": timestamp(record["created_at"]),
                "updated_at": timestamp(record["updated_at"]),
                "canceled_at": timestamp(record["canceled_at"]),
                "customer_id": record["customer"]["id"],
                "scheduled_start": timestamp(schedule["scheduled_start"]),
                "scheduled_end": timestamp(schedule["scheduled_end"]),
                "time_zone": schedule["time_zone"],
                "arrival_window": schedule["arrival_window"],
                "on_my_way_at": timestamp(stamps["on_my_way_at"]),
                "started_at": timestamp(stamps["started_at"]),
                "completed_at": timestamp(stamps["completed_at"]),
                "address_id": address["id"],
                "address_street": address["street"],
                "address_street_line_2": address["street_line_2"],
                "address_city": address["city"],
                "address_state": address["state"],
                "address_zip": address["zip"],
                "address_latitude": address["latitude"],
                "address_longitude": address["longitude"],
                "address_raw": address,
            }
        )
        for position, tag in enumerate(record["tags"]):
            tags.append({"job_id": record["id"], "position": position, "tag": tag})
        for position, employee in enumerate(record["assigned_employees"]):
            assignments.append(
                {
                    "job_id": record["id"],
                    "employee_id": employee["id"],
                    "position": position,
                }
            )
        for position, note in enumerate(record["notes"]):
            notes.append(
                {
                    "id": note["id"],
                    "job_id": record["id"],
                    "position": position,
                    "content": note["content"],
                }
            )

    warn_unknown("jobs.work_status", statuses, WORK_STATUSES)

    return {
        "jobs": upsert(session, Job, jobs),
        "job_tags": upsert(session, JobTag, tags),
        "job_employees": upsert(session, JobEmployee, assignments),
        "notes": upsert(session, Note, notes),
    }


def load_invoices(session: Session) -> dict[str, int]:
    invoices: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    discounts: list[dict[str, Any]] = []
    taxes: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    statuses: list[str] = []
    item_types: list[str] = []

    for record in read_jsonl(INVOICES):
        statuses.append(record["status"])
        invoices.append(
            {
                "id": record["id"],
                "job_id": record["job_id"],
                "invoice_number": record["invoice_number"],
                "status": record["status"],
                "amount": record["amount"],
                "subtotal": record["subtotal"],
                "due_amount": record["due_amount"],
                "paid_at": timestamp(record["paid_at"]),
                "sent_at": timestamp(record["sent_at"]),
                "service_date": timestamp(record["service_date"]),
                "invoice_date": timestamp(record["invoice_date"]),
            }
        )
        for position, item in enumerate(record["items"]):
            item_types.append(item["type"])
            items.append(
                {
                    "id": item["id"],
                    "invoice_id": record["id"],
                    "position": position,
                    "name": item["name"],
                    "type": item["type"],
                    "unit_price": item["unit_price"],
                    "qty_in_hundredths": item["qty_in_hundredths"],
                    "amount": item["amount"],
                }
            )
        for position, discount in enumerate(record["discounts"]):
            discounts.append(
                {
                    "invoice_id": record["id"],
                    "position": position,
                    "amount": discount["amount"],
                }
            )
        for position, tax in enumerate(record["taxes"]):
            taxes.append(
                {
                    "invoice_id": record["id"],
                    "position": position,
                    "amount": tax["amount"],
                }
            )
        for position, payment in enumerate(record["payments"]):
            payments.append(
                {
                    "id": payment["id"],
                    "invoice_id": record["id"],
                    "position": position,
                    "status": payment["status"],
                    "payment_method": payment["payment_method"],
                    "amount": payment["amount"],
                    "note": payment["note"],
                    "paid_at": timestamp(payment["paid_at"]),
                    "category": payment["category"],
                    "surcharge_fee_amount": payment["surcharge_fee_amount"],
                }
            )

    warn_unknown("invoices.status", statuses, INVOICE_STATUSES)
    warn_unknown("invoice_items.type", item_types, INVOICE_ITEM_TYPES)

    return {
        "invoices": upsert(session, Invoice, invoices),
        "invoice_items": upsert(session, InvoiceItem, items),
        "invoice_discounts": upsert(session, InvoiceDiscount, discounts),
        "invoice_taxes": upsert(session, InvoiceTax, taxes),
        "invoice_payments": upsert(session, InvoicePayment, payments),
    }


def load_all(session: Session) -> dict[str, int]:
    """Load every source file, parents before children.

    Customers and employees first, because a job references both.
    """
    counts: dict[str, int] = {}
    counts.update(load_customers(session))
    counts.update(load_employees(session))
    counts.update(load_jobs(session))
    counts.update(load_invoices(session))
    return counts
