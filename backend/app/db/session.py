from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    connect_args = {"connect_timeout": 2} if settings.database_url.startswith("postgresql") else {}
    return create_engine(settings.database_url, pool_pre_ping=True, future=True, connect_args=connect_args)


@lru_cache
def get_sandbox_engine():
    settings = get_settings()
    connect_args = {"connect_timeout": 1} if settings.sandbox_database_url.startswith("postgresql") else {}
    return create_engine(settings.sandbox_database_url, pool_pre_ping=True, future=True, connect_args=connect_args)


@lru_cache
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
