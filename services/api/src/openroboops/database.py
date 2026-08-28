from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def create_schema() -> None:
    from . import models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if connection.dialect.name == "postgresql":
            await _create_telemetry_partitions(connection)


async def ensure_telemetry_partitions() -> None:
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await _create_telemetry_partitions(connection)


async def _create_telemetry_partitions(connection: AsyncConnection) -> None:
    current = datetime.now(UTC)
    year, month = current.year, current.month
    for offset in range(3):
        start_index = (month - 1) + offset
        start_year = year + start_index // 12
        start_month = start_index % 12 + 1
        end_index = start_index + 1
        end_year = year + end_index // 12
        end_month = end_index % 12 + 1
        name = f"telemetry_snapshots_{start_year}_{start_month:02d}"
        await connection.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF telemetry_snapshots "
                f"FOR VALUES FROM ('{start_year}-{start_month:02d}-01') "
                f"TO ('{end_year}-{end_month:02d}-01')"
            )
        )
    await connection.execute(
        text("CREATE TABLE IF NOT EXISTS telemetry_snapshots_default PARTITION OF telemetry_snapshots DEFAULT")
    )
