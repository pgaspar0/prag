from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db, engine

import asyncio
from app.ingestion.worker import run_worker_loop

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info(
        "server_starting",
        env=settings.ENV,
        gen_model=settings.GEN_MODEL,
        embed_model=settings.EMBED_MODEL,
        embed_dim=settings.EMBED_DIM,
    )
    worker_task = asyncio.create_task(run_worker_loop())
    yield
    # Shutdown actions
    logger.info("server_shutting_down")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(
    title="PRAG - Precise RAG API",
    description="Precise RAG with verifiable citations, deterministic refusal, and evaluation benchmarks",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware configured from settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api import documents
app.include_router(documents.router)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check():
    """Liveness probe: returns 200 without database overhead."""
    return {"status": "ok", "app": "PRAG"}


@app.get("/ready", status_code=status.HTTP_200_OK, tags=["Health"])
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness probe: executes SELECT 1 to verify DB connection and wake up Neon."""
    try:
        result = await db.execute(text("SELECT 1;"))
        value = result.scalar()
        if value == 1:
            return {"status": "ready", "database": "connected"}
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "database": "unexpected_result"},
        )
    except Exception as exc:
        logger.error("database_readiness_failed", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "database": "error", "detail": str(exc)},
        )
