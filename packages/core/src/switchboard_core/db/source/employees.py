"""``data/employees.jsonl`` — 23 rows."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import SOURCE_SCHEMA, Base


class Employee(Base):
    """Everyone assigned to a job in the window.

    ``Team Phone`` is the shared office line rather than a person, and is
    excluded from availability. That exclusion belongs to T2.4, not here: this
    table mirrors the file.
    """

    __tablename__ = "employees"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, index=True)

    #: Named ``jobs`` in the source: a count of jobs touched, not a collection.
    #: Kept under the source name rather than renamed to job_count, because the
    #: only field this repo renames is the job's invoice_number (hard rule 8).
    jobs: Mapped[int] = mapped_column()
