"""Engine and session factory.

The URL comes from ``DATABASE_URL``. Nothing here opens a connection at import
time, so importing the models does not require a database.
"""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:5432/switchboard"
)


def database_url() -> str:
    """Return ``DATABASE_URL``, normalised onto the psycopg 3 driver.

    ``.env.example`` carries a bare ``postgresql://`` URL because that is what
    psql and Alembic's own tooling expect. SQLAlchemy would route that to
    psycopg2, which is not installed, so the driver is pinned here rather than
    duplicated into every environment file.
    """
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def create_db_engine(url: str | None = None, **kwargs: object) -> Engine:
    return create_engine(url or database_url(), **kwargs)


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or create_db_engine(), expire_on_commit=False)
