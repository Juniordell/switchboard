"""Loading ``data/*.jsonl`` into the source schema."""

from switchboard_core.load.loaders import (
    load_all,
    load_customers,
    load_employees,
    load_invoices,
    load_jobs,
)
from switchboard_core.load.reader import data_dir, read_jsonl, timestamp
from switchboard_core.load.upsert import upsert

__all__ = [
    "data_dir",
    "load_all",
    "load_customers",
    "load_employees",
    "load_invoices",
    "load_jobs",
    "read_jsonl",
    "timestamp",
    "upsert",
]
