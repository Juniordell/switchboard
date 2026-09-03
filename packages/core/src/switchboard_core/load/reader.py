"""Reading ``data/*.jsonl``.

Every file handle in this module is opened for reading. Nothing in this
repository writes to ``data/``: it is the provided dataset and the assignment
forbids changing it (CLAUDE.md hard rule 1).
"""

import datetime
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

#: Override the dataset location, for tests and for a container that mounts it
#: somewhere other than the repository root.
DATA_DIR_ENV = "SWITCHBOARD_DATA_DIR"

JOBS = "jobs.jsonl"
INVOICES = "invoices.jsonl"
CUSTOMERS = "customers.jsonl"
EMPLOYEES = "employees.jsonl"


def data_dir() -> Path:
    """Locate ``data/``.

    Walks up from this module rather than trusting the working directory, so
    the loader behaves the same run from the repository root, from
    ``packages/core`` or from a test.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / JOBS).is_file():
            return parent / "data"

    raise FileNotFoundError(
        f"could not find data/{JOBS} above {here}; set {DATA_DIR_ENV}"
    )


def read_jsonl(name: str) -> Iterator[dict[str, Any]]:
    """Yield one record per line. Blank lines are skipped."""
    path = data_dir() / name
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def timestamp(value: str | None) -> datetime.datetime | None:
    """Parse a source timestamp.

    The source writes UTC with a trailing ``Z``, which
    :meth:`datetime.datetime.fromisoformat` accepts from Python 3.11.
    """
    if value is None:
        return None
    return datetime.datetime.fromisoformat(value)
