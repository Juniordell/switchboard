#!/usr/bin/env python
"""Assert the loaded database matches the measured shape in docs/DATA.md.

Run after ``python -m switchboard_core.load``::

    uv run python scripts/verify_load.py

Exits non-zero and prints every failure, not just the first. Two kinds of check
are made, and the second is the one that earns its keep:

**Counts** — the totals docs/DATA.md publishes. These catch a loader that drops
rows or double-counts.

**Traps** — the awkward rows: jobs with no address id, no invoice, no schedule,
no technician. Every one of them is a case some later query has to survive, and
a silent change to any is the kind of thing that is discovered twenty hours
later inside a warranty answer. Asserting them here means a change to the
dataset, or to the loader, breaks the load loudly instead.

The numbers here and the numbers in docs/DATA.md are the same numbers. If one
moves, both move, in the same commit.
"""

import sys
from dataclasses import dataclass

from sqlalchemy import text

from switchboard_core.db.session import create_db_engine


@dataclass(frozen=True)
class Check:
    label: str
    expected: int
    sql: str


COUNTS: tuple[Check, ...] = (
    Check("jobs", 1992, "SELECT count(*) FROM source.jobs"),
    Check("notes", 6954, "SELECT count(*) FROM source.notes"),
    Check("invoices", 1700, "SELECT count(*) FROM source.invoices"),
    Check("invoice line items", 4390, "SELECT count(*) FROM source.invoice_items"),
    Check("customers", 732, "SELECT count(*) FROM source.customers"),
    Check("employees", 23, "SELECT count(*) FROM source.employees"),
    Check(
        "distinct address ids",
        1390,
        "SELECT count(DISTINCT address_id) FROM source.customer_addresses",
    ),
    Check(
        "distinct address tuples",
        1367,
        """
        SELECT count(*) FROM (
            SELECT DISTINCT street, street_line_2, city, state, zip
            FROM source.customer_addresses
        ) AS distinct_tuples
        """,
    ),
    Check(
        "customers, homeowner",
        683,
        "SELECT count(*) FROM source.customers WHERE kind = 'homeowner'",
    ),
    Check(
        "customers, business",
        49,
        "SELECT count(*) FROM source.customers WHERE kind = 'business'",
    ),
)

TRAPS: tuple[Check, ...] = (
    Check(
        "jobs with a null address id",
        4,
        "SELECT count(*) FROM source.jobs WHERE address_id IS NULL",
    ),
    Check(
        "jobs with no invoice",
        456,
        """
        SELECT count(*) FROM source.jobs j
        WHERE NOT EXISTS (SELECT 1 FROM source.invoices i WHERE i.job_id = j.id)
        """,
    ),
    Check(
        "jobs with more than one invoice",
        135,
        """
        SELECT count(*) FROM (
            SELECT job_id FROM source.invoices
            GROUP BY job_id HAVING count(*) > 1
        ) AS multi
        """,
    ),
    Check(
        "jobs with no scheduled_start",
        94,
        "SELECT count(*) FROM source.jobs WHERE scheduled_start IS NULL",
    ),
    Check(
        "jobs with no technician",
        95,
        """
        SELECT count(*) FROM source.jobs j
        WHERE NOT EXISTS (
            SELECT 1 FROM source.job_employees a WHERE a.job_id = j.id
        )
        """,
    ),
    Check(
        "jobs with a real street but no address id",
        3,
        """
        SELECT count(*) FROM source.jobs
        WHERE address_id IS NULL AND coalesce(address_street, '') <> ''
        """,
    ),
    Check(
        "warranty line items, ILIKE '%warrant%'",
        64,
        "SELECT count(*) FROM source.invoice_items WHERE name ILIKE '%warrant%'",
    ),
    Check(
        "warranty line items on the exact prefix",
        61,
        """
        SELECT count(*) FROM source.invoice_items
        WHERE name LIKE 'WARRANTY Parts / Service - WARRANTY - %'
        """,
    ),
    # docs/DATA.md splits the calendar at midnight opening 2026-09-02: the 38
    # stale rows run 2026-03-07 to 2026-08-30, the 38 live ones start on the
    # 2nd itself. An end-of-day boundary here reads 48 and would have quietly
    # moved ten live jobs into the stale bucket.
    Check(
        "scheduled jobs dated in the past",
        38,
        """
        SELECT count(*) FROM source.jobs
        WHERE work_status = 'scheduled'
          AND scheduled_start < TIMESTAMPTZ '2026-09-02 00:00:00+00'
        """,
    ),
    Check(
        "scheduled jobs from 2026-09-02 onward",
        38,
        """
        SELECT count(*) FROM source.jobs
        WHERE work_status = 'scheduled'
          AND scheduled_start >= TIMESTAMPTZ '2026-09-02 00:00:00+00'
        """,
    ),
    Check("distinct tags", 23, "SELECT count(DISTINCT tag) FROM source.job_tags"),
)


def run(engine, checks: tuple[Check, ...]) -> list[str]:
    failures: list[str] = []
    with engine.connect() as connection:
        for check in checks:
            actual = connection.execute(text(check.sql)).scalar_one()
            ok = actual == check.expected
            marker = "  ok  " if ok else "  FAIL"
            print(f"{marker}  {check.label:44} {actual:>6} (expected {check.expected})")
            if not ok:
                failures.append(
                    f"{check.label}: got {actual}, docs/DATA.md says {check.expected}"
                )
    return failures


def main() -> int:
    engine = create_db_engine()

    print("counts")
    failures = run(engine, COUNTS)
    print("\ntraps")
    failures += run(engine, TRAPS)

    if failures:
        sys.stdout.flush()
        print(f"\n{len(failures)} check(s) failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "\nEither the loader changed shape or the dataset did. "
            "docs/DATA.md and this script move together.",
            file=sys.stderr,
        )
        return 1

    print(f"\nall {len(COUNTS) + len(TRAPS)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
