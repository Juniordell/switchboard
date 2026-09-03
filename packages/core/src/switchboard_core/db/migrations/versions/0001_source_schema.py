"""Initial schema: source tables, and knowledge as an empty namespace.

``source`` mirrors ``data/*.jsonl`` row for row. Nothing here is derived; the
knowledge schema is created empty so the boundary exists from the first
migration rather than appearing when T2.2 needs somewhere to put a table.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Alembic autogenerate does not emit schema creation; the tables below all
    # target these, so they have to exist first.
    op.execute("CREATE SCHEMA IF NOT EXISTS source")
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")

    op.create_table(
        "customers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("first_job", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_job", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        schema="source",
    )
    op.create_index(
        op.f("ix_customers_kind"), "customers", ["kind"], unique=False, schema="source"
    )
    op.create_table(
        "employees",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("jobs", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        schema="source",
    )
    op.create_index(
        op.f("ix_employees_role"), "employees", ["role"], unique=False, schema="source"
    )
    op.create_table(
        "customer_addresses",
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("address_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("street", sa.String(), nullable=True),
        sa.Column("street_line_2", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("zip", sa.String(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["source.customers.id"],
            name=op.f("fk_customer_addresses_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint(
            "customer_id", "address_id", name=op.f("pk_customer_addresses")
        ),
        schema="source",
    )
    op.create_index(
        "ix_customer_addresses_address_id",
        "customer_addresses",
        ["address_id"],
        unique=False,
        schema="source",
    )
    op.create_table(
        "customer_tags",
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["source.customers.id"],
            name=op.f("fk_customer_tags_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint(
            "customer_id", "position", name=op.f("pk_customer_tags")
        ),
        schema="source",
    )
    op.create_index(
        "ix_customer_tags_tag", "customer_tags", ["tag"], unique=False, schema="source"
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_number", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("work_status", sa.String(), nullable=False),
        sa.Column("lead_source", sa.String(), nullable=True),
        sa.Column("total_amount", sa.BigInteger(), nullable=False),
        sa.Column("outstanding_balance", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_zone", sa.String(), nullable=False),
        sa.Column("arrival_window", sa.Integer(), nullable=False),
        sa.Column("on_my_way_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("address_id", sa.String(), nullable=True),
        sa.Column("address_street", sa.String(), nullable=True),
        sa.Column("address_street_line_2", sa.String(), nullable=True),
        sa.Column("address_city", sa.String(), nullable=True),
        sa.Column("address_state", sa.String(), nullable=True),
        sa.Column("address_zip", sa.String(), nullable=True),
        sa.Column("address_latitude", sa.Float(), nullable=True),
        sa.Column("address_longitude", sa.Float(), nullable=True),
        sa.Column(
            "address_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["source.customers.id"],
            name=op.f("fk_jobs_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        schema="source",
    )
    op.create_index(
        "ix_jobs_address_id", "jobs", ["address_id"], unique=False, schema="source"
    )
    op.create_index(
        op.f("ix_jobs_customer_id"),
        "jobs",
        ["customer_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        op.f("ix_jobs_job_number"), "jobs", ["job_number"], unique=True, schema="source"
    )
    op.create_index(
        "ix_jobs_scheduled_start",
        "jobs",
        ["scheduled_start"],
        unique=False,
        schema="source",
    )
    op.create_index(
        op.f("ix_jobs_work_status"),
        "jobs",
        ["work_status"],
        unique=False,
        schema="source",
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("invoice_number", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("subtotal", sa.BigInteger(), nullable=False),
        sa.Column("due_amount", sa.BigInteger(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("service_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"], ["source.jobs.id"], name=op.f("fk_invoices_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        schema="source",
    )
    op.create_index(
        op.f("ix_invoices_invoice_number"),
        "invoices",
        ["invoice_number"],
        unique=True,
        schema="source",
    )
    op.create_index(
        op.f("ix_invoices_job_id"),
        "invoices",
        ["job_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        op.f("ix_invoices_status"),
        "invoices",
        ["status"],
        unique=False,
        schema="source",
    )
    op.create_table(
        "job_employees",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("employee_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["source.employees.id"],
            name=op.f("fk_job_employees_employee_id_employees"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["source.jobs.id"], name=op.f("fk_job_employees_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("job_id", "employee_id", name=op.f("pk_job_employees")),
        schema="source",
    )
    op.create_index(
        op.f("ix_job_employees_employee_id"),
        "job_employees",
        ["employee_id"],
        unique=False,
        schema="source",
    )
    op.create_table(
        "job_tags",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["source.jobs.id"], name=op.f("fk_job_tags_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("job_id", "position", name=op.f("pk_job_tags")),
        schema="source",
    )
    op.create_index(
        "ix_job_tags_tag", "job_tags", ["tag"], unique=False, schema="source"
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["source.jobs.id"], name=op.f("fk_notes_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
        schema="source",
    )
    op.create_index(
        "ix_notes_job_id_position",
        "notes",
        ["job_id", "position"],
        unique=False,
        schema="source",
    )
    op.create_table(
        "invoice_discounts",
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["source.invoices.id"],
            name=op.f("fk_invoice_discounts_invoice_id_invoices"),
        ),
        sa.PrimaryKeyConstraint(
            "invoice_id", "position", name=op.f("pk_invoice_discounts")
        ),
        schema="source",
    )
    op.create_table(
        "invoice_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("unit_price", sa.BigInteger(), nullable=False),
        sa.Column("qty_in_hundredths", sa.Integer(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["source.invoices.id"],
            name=op.f("fk_invoice_items_invoice_id_invoices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_items")),
        schema="source",
    )
    op.create_index(
        op.f("ix_invoice_items_invoice_id"),
        "invoice_items",
        ["invoice_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        op.f("ix_invoice_items_type"),
        "invoice_items",
        ["type"],
        unique=False,
        schema="source",
    )
    op.create_table(
        "invoice_payments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payment_method", sa.String(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("surcharge_fee_amount", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["source.invoices.id"],
            name=op.f("fk_invoice_payments_invoice_id_invoices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_payments")),
        schema="source",
    )
    op.create_index(
        op.f("ix_invoice_payments_invoice_id"),
        "invoice_payments",
        ["invoice_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        op.f("ix_invoice_payments_status"),
        "invoice_payments",
        ["status"],
        unique=False,
        schema="source",
    )
    op.create_table(
        "invoice_taxes",
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["source.invoices.id"],
            name=op.f("fk_invoice_taxes_invoice_id_invoices"),
        ),
        sa.PrimaryKeyConstraint(
            "invoice_id", "position", name=op.f("pk_invoice_taxes")
        ),
        schema="source",
    )


def downgrade() -> None:
    op.drop_table("invoice_taxes", schema="source")
    op.drop_index(
        op.f("ix_invoice_payments_status"),
        table_name="invoice_payments",
        schema="source",
    )
    op.drop_index(
        op.f("ix_invoice_payments_invoice_id"),
        table_name="invoice_payments",
        schema="source",
    )
    op.drop_table("invoice_payments", schema="source")
    op.drop_index(
        op.f("ix_invoice_items_type"), table_name="invoice_items", schema="source"
    )
    op.drop_index(
        op.f("ix_invoice_items_invoice_id"), table_name="invoice_items", schema="source"
    )
    op.drop_table("invoice_items", schema="source")
    op.drop_table("invoice_discounts", schema="source")
    op.drop_index("ix_notes_job_id_position", table_name="notes", schema="source")
    op.drop_table("notes", schema="source")
    op.drop_index("ix_job_tags_tag", table_name="job_tags", schema="source")
    op.drop_table("job_tags", schema="source")
    op.drop_index(
        op.f("ix_job_employees_employee_id"),
        table_name="job_employees",
        schema="source",
    )
    op.drop_table("job_employees", schema="source")
    op.drop_index(op.f("ix_invoices_status"), table_name="invoices", schema="source")
    op.drop_index(op.f("ix_invoices_job_id"), table_name="invoices", schema="source")
    op.drop_index(
        op.f("ix_invoices_invoice_number"), table_name="invoices", schema="source"
    )
    op.drop_table("invoices", schema="source")
    op.drop_index(op.f("ix_jobs_work_status"), table_name="jobs", schema="source")
    op.drop_index("ix_jobs_scheduled_start", table_name="jobs", schema="source")
    op.drop_index(op.f("ix_jobs_job_number"), table_name="jobs", schema="source")
    op.drop_index(op.f("ix_jobs_customer_id"), table_name="jobs", schema="source")
    op.drop_index("ix_jobs_address_id", table_name="jobs", schema="source")
    op.drop_table("jobs", schema="source")
    op.drop_index("ix_customer_tags_tag", table_name="customer_tags", schema="source")
    op.drop_table("customer_tags", schema="source")
    op.drop_index(
        "ix_customer_addresses_address_id",
        table_name="customer_addresses",
        schema="source",
    )
    op.drop_table("customer_addresses", schema="source")
    op.drop_index(op.f("ix_employees_role"), table_name="employees", schema="source")
    op.drop_table("employees", schema="source")
    op.drop_index(op.f("ix_customers_kind"), table_name="customers", schema="source")
    op.drop_table("customers", schema="source")

    op.execute("DROP SCHEMA IF EXISTS knowledge")
    op.execute("DROP SCHEMA IF EXISTS source")
