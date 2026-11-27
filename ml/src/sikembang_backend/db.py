"""SQLite engine, explicit schema initialization and session factory."""

import sqlite3
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


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
    """Create missing tables without replacing database contents."""
    path = engine.url.database
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
