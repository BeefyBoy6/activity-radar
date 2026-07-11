"""SQLAlchemy engine/session setup (SQLite)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
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
    }
    with engine.begin() as conn:
        for table, cols in added.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
