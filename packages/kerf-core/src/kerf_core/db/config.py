import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_database_url() -> str:
    """Resolve the default ``DATABASE_URL`` when none is configured.

    Zero-dependency install is the priority: with nothing set we point at an
    embedded SQLite file under ``~/.kerf/kerf.db`` (auto-created, WAL, foreign
    keys on).  Postgres remains a one-line opt-in — set ``DATABASE_URL`` (or
    ``KERF_DATABASE_URL``) to a ``postgres://…`` DSN and behaviour is exactly as
    before.

    The plain ``DATABASE_URL`` env var is honoured here too so that both this
    settings object and :class:`kerf_core.config.Settings` agree on the backend
    regardless of which one opened the pool.
    """
    env = os.environ.get("DATABASE_URL", "").strip()
    if env:
        return env
    return "sqlite://" + str(Path.home() / ".kerf" / "kerf.db")


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='KERF_', env_file='.env', env_file_encoding='utf-8', extra='ignore')

    database_url: str = Field(default_factory=default_database_url)
    db_max_conns: int = 10
    db_min_conns: int = 1
    db_max_conn_lifetime_minutes: int = 60
    db_max_conn_idle_time_minutes: int = 30


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


def get_database_url() -> str:
    settings = get_database_settings()
    return settings.database_url


database_url = get_database_url()


class DatabaseURL:
    def __init__(self, url: str):
        self.raw = url
        parsed = urlparse(url)
        self.scheme = parsed.scheme
        self.username = parsed.username or ""
        self.password = parsed.password or ""
        self.host = parsed.hostname or ""
        self.port = parsed.port or 5432
        self.database = parsed.path.lstrip("/") or ""
        self.query = parsed.query

    def __str__(self) -> str:
        return self.raw
