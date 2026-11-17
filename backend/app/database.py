"""Database engine and session access.

The engine is built lazily from settings and cached per process. Auth tests
override ``get_db`` so they never touch a production database.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError


@lru_cache(maxsize=8)
def _engine_for(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


def get_engine(settings: Settings) -> Engine:
    if not settings.database_url:
        raise ApiError(503, "database_unavailable", "数据库未配置")
    return _engine_for(settings.database_url)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    settings: Settings = request.app.state.settings
    engine = get_engine(settings)
    with Session(engine) as session:
        yield session


def session_for(settings: Settings) -> Session:
    """A standalone session for workers/dispatchers (no request context)."""
    return Session(get_engine(settings))
