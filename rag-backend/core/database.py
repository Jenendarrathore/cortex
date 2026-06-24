from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


# ivfflat.probes must be set on the underlying sync engine's connection events.
@event.listens_for(engine.sync_engine, "connect")
def set_search_params(dbapi_conn, connection_record):
    dbapi_conn.execute("SET ivfflat.probes = 10")


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Apply the canonical schema (db/schema.sql). Idempotent — runs on startup."""
    sql = _SCHEMA_PATH.read_text()
    async with engine.begin() as conn:
        await conn.exec_driver_sql(sql)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
