"""Structural guards on the source schema.

These read ``Base.metadata`` and never open a connection, so they run anywhere
and in milliseconds. Behaviour is the loader's problem in T1.4; what is asserted
here is shape.
"""

import pytest
from sqlalchemy import BigInteger, Float, Numeric, Table

from switchboard_core.db.base import KNOWLEDGE_SCHEMA, SOURCE_SCHEMA, Base
from switchboard_core.db.source import Job

EXPECTED_TABLES = {
    "customer_addresses",
    "customer_tags",
    "customers",
    "employees",
    "invoice_discounts",
    "invoice_items",
    "invoice_payments",
    "invoice_taxes",
    "invoices",
    "job_employees",
    "job_tags",
    "jobs",
    "notes",
}

#: Every column that holds money. Cents, always, everywhere in the database.
MONEY_COLUMNS = {
    ("jobs", "total_amount"),
    ("jobs", "outstanding_balance"),
    ("invoices", "amount"),
    ("invoices", "subtotal"),
    ("invoices", "due_amount"),
    ("invoice_items", "unit_price"),
    ("invoice_items", "amount"),
    ("invoice_discounts", "amount"),
    ("invoice_taxes", "amount"),
    ("invoice_payments", "amount"),
    ("invoice_payments", "surcharge_fee_amount"),
}

TABLES: dict[str, Table] = {
    table.name: table
    for table in Base.metadata.tables.values()
    if table.schema == SOURCE_SCHEMA
}


def test_every_source_table_is_registered() -> None:
    assert set(TABLES) == EXPECTED_TABLES


def test_nothing_is_derived_yet() -> None:
    """T1.3 creates the knowledge namespace but puts nothing in it."""
    derived = [t for t in Base.metadata.tables.values() if t.schema == KNOWLEDGE_SCHEMA]
    assert derived == []


@pytest.mark.parametrize(("table_name", "column_name"), sorted(MONEY_COLUMNS))
def test_money_is_stored_in_cents_as_bigint(table_name: str, column_name: str) -> None:
    column = TABLES[table_name].columns[column_name]
    assert isinstance(column.type, BigInteger), (
        f"{table_name}.{column_name} holds money and must be BigInteger cents"
    )


def test_no_money_column_is_a_float_or_decimal() -> None:
    """Latitude and longitude are the only approximate numbers in the schema."""
    approximate = {
        f"{table.name}.{column.name}"
        for table in TABLES.values()
        for column in table.columns
        if isinstance(column.type, Float | Numeric)
    }
    assert approximate == {
        "customer_addresses.latitude",
        "customer_addresses.longitude",
        "jobs.address_latitude",
        "jobs.address_longitude",
    }


@pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
def test_every_join_column_is_indexed(table_name: str) -> None:
    """Foreign keys are join columns, and join columns are indexed now.

    A column counts as indexed when it leads an index, a primary key or a
    unique constraint: Postgres can use a composite from its leading column, so
    a second single-column index would cost writes for nothing.
    """
    table = TABLES[table_name]
    leading = {index.columns.keys()[0] for index in table.indexes if index.columns}
    if table.primary_key.columns:
        leading.add(table.primary_key.columns.keys()[0])

    unindexed = sorted(
        column.name
        for column in table.columns
        if column.foreign_keys and column.name not in leading
    )
    assert not unindexed, f"{table_name}: join columns without an index: {unindexed}"


def test_the_job_number_is_not_called_invoice_number() -> None:
    """CLAUDE.md hard rule 8, at the level this task can assert it.

    The source field named invoice_number is the job number. The AST guard that
    makes the wrong join unwritable across all of packages/core is T1.3a.
    """
    assert "job_number" in Job.__table__.columns
    assert "invoice_number" not in Job.__table__.columns
