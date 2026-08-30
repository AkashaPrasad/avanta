"""Database session management.

Postgres in every environment: PostGIS locally under docker compose, Supabase in
the hosted deployment. The only difference is DATABASE_URL.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.app.models.base import Base


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://avanta:avanta@localhost:5432/avanta")
    # Supabase and most managed providers hand out a bare postgresql:// URL.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def _engine_kwargs(url: str) -> dict:
    # SQLite is supported for local development only, so the science can be
    # exercised without standing up Postgres. Every deployed environment --
    # docker compose and Supabase alike -- runs Postgres.
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "connect_args": {"options": "-c timezone=utc"},
    }


_URL = database_url()
engine = create_engine(_URL, **_engine_kwargs(_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_all() -> None:
    # Importing the models registers them on Base.metadata; without this the
    # call silently creates nothing.
    from api.app.models import records  # noqa: F401

    Base.metadata.create_all(engine)
