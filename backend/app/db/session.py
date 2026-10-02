from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sqlalchemy.pool import NullPool
from app.config import settings

# In asyncpg with pgbouncer (Neon), statement cache must be disabled
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.ENV == "development"),
    connect_args={"statement_cache_size": 0},
    poolclass=NullPool,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
