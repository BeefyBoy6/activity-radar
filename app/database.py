"""SQLAlchemy engine/session setup (SQLite)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    """Improve reliability when the scheduler and dashboard overlap."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema():
    """Create tables and additively migrate columns added after first release.
    SQLite create_all doesn't add columns to existing tables."""
    from sqlalchemy import text

    Base.metadata.create_all(engine)
    added = {
        "activities": {"enriched_at": "DATETIME", "excluded": "BOOLEAN DEFAULT 0"},
        "scrape_logs": {
            "rejected_count": "INTEGER DEFAULT 0",
            "rejection_summary": "TEXT DEFAULT ''",
            "staling_skipped": "BOOLEAN DEFAULT 0",
        },
    }
    with engine.begin() as conn:
        for table, cols in added.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
