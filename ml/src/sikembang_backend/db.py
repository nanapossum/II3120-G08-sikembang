"""SQLite engine, explicit schema initialization and session factory."""

import sqlite3
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event, inspect
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


def _missing_provenance_columns(inspector: Inspector) -> list[tuple[str, str]]:
    columns = (("order_revisions", "source"), ("iot_telemetry_logs", "device_source"))
    return [(table, column) for table, column in columns
            if column not in {info["name"] for info in inspector.get_columns(table)}]


def schema_is_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        inspector = inspect(connection)
        return (Base.metadata.tables.keys() <= set(inspector.get_table_names())
                and not _missing_provenance_columns(inspector))


def _enable_foreign_keys(connection: sqlite3.Connection, _record: object) -> None:
    # SQLite ignores this pragma during a transaction. Restore transactional mode before use.
    autocommit = connection.autocommit
    connection.autocommit = True
    try:
        connection.execute("PRAGMA foreign_keys=ON").close()
    finally:
        connection.autocommit = autocommit


def create_database(path: Path | str) -> Engine:
    """Configure the engine without opening a connection or creating a file."""
    connect_args = {"autocommit": False}
    if str(path) == ":memory:":
        engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={**connect_args, "check_same_thread": False})
    else:
        url = URL.create("sqlite", database=str(Path(path).resolve()))
        engine = create_engine(url, connect_args=connect_args)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def initialize(engine: Engine) -> None:
    """Create missing tables and upgrade 6A provenance columns in place."""
    path = engine.url.database
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        for table, column in _missing_provenance_columns(inspect(connection)):
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR")


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
