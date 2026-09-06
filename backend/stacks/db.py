from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from stacks.snapshots import before_upgrade


def connect(path: Path):
    engine = create_engine(f"sqlite:///{path.resolve()}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")

    return engine


def initialize(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    before_upgrade(path, ScriptDirectory.from_config(config).get_current_head())
    engine = connect(path)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    try:
        with engine.connect() as connection:
            # SQLite batch rebuilds briefly drop a referenced table. Disable enforcement
            # only on this startup connection, then validate every relationship before commit.
            # An explicit BEGIN also makes SQLite DDL roll back on migration failure.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                with connection.begin():
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                        raise ValueError("Schema upgrade failed relationship validation.")
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
    except BaseException:
        engine.dispose()
        raise
    return engine, sessionmaker(engine, expire_on_commit=False)
