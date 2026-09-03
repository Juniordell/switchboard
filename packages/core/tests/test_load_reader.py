"""Reader and warning behaviour. No database.

The loaders themselves are exercised end to end by scripts/verify_load.py,
which needs Postgres; what is asserted here runs anywhere.
"""

import datetime
import logging

import pytest

from switchboard_core.db.source import WORK_STATUSES
from switchboard_core.load.loaders import warn_unknown
from switchboard_core.load.reader import (
    CUSTOMERS,
    EMPLOYEES,
    INVOICES,
    JOBS,
    data_dir,
    read_jsonl,
    timestamp,
)


def test_data_dir_is_found_from_the_module_not_the_cwd() -> None:
    found = data_dir()
    assert (found / JOBS).is_file()
    assert found.name == "data"


@pytest.mark.parametrize("name", [JOBS, INVOICES, CUSTOMERS, EMPLOYEES])
def test_every_source_file_reads_as_records(name: str) -> None:
    first = next(read_jsonl(name))
    assert isinstance(first, dict)
    assert first["id"]


def test_timestamp_parses_the_trailing_z_as_utc() -> None:
    parsed = timestamp("2026-03-02T14:27:15Z")
    assert parsed == datetime.datetime(2026, 3, 2, 14, 27, 15, tzinfo=datetime.UTC)


def test_timestamp_passes_none_through() -> None:
    assert timestamp(None) is None


def test_warn_unknown_is_silent_when_every_value_is_known(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        warn_unknown("jobs.work_status", ["scheduled", "in progress"], WORK_STATUSES)
    assert caplog.records == []


def test_warn_unknown_reports_the_value_and_its_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The schema has no CHECK constraints, so this warning is the visibility."""
    with caplog.at_level(logging.WARNING):
        warn_unknown(
            "jobs.work_status",
            ["scheduled", "teleported", "teleported"],
            WORK_STATUSES,
        )
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "jobs.work_status" in message
    assert "'teleported' x2" in message
    assert "loaded anyway" in message


def test_the_real_dataset_carries_no_unknown_work_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        warn_unknown(
            "jobs.work_status",
            [record["work_status"] for record in read_jsonl(JOBS)],
            WORK_STATUSES,
        )
    assert caplog.records == []
