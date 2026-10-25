from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

# Master Engine (appuser) - for application metadata and dynamic table management
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False
)

# Read-Only Engine (readonly_user) - strictly for executing user-generated queries
readonly_engine = create_engine(
    settings.readonly_database_url,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
ReadonlySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=readonly_engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields an administrative database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_readonly_db() -> Generator[Session, None, None]:
    """Dependency that yields a least-privilege read-only database session."""
    db = ReadonlySessionLocal()
    try:
        yield db
    finally:
        db.close()

