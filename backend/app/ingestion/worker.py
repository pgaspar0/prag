import asyncio
from datetime import datetime, timezone, timedelta
import structlog
from sqlalchemy import select, update, text, delete
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Chunk, Document, IngestionJob
from app.db.session import async_session_maker
from app.ingestion.chunker import create_chunks_from_pages
from app.ingestion.embeddings import generate_embeddings_batch
from app.ingestion.extract import extract_pages_with_words

logger = structlog.get_logger()


async def recover_stale_jobs():
    """
    Recovers jobs stuck in 'processing' state due to server hibernation or restart.
    Jobs older than 5 minutes in 'processing' are returned to 'queued'.
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with async_session_maker() as db:
        query = (
            update(IngestionJob)
            .where(
                IngestionJob.status == "processing",
                IngestionJob.updated_at < stale_cutoff,
            )
            .values(status="queued", updated_at=datetime.now(timezone.utc))
        )
        res = await db.execute(query)
        if res.rowcount > 0:
            logger.info("recovered_stale_ingestion_jobs", count=res.rowcount)
            await db.commit()


async def process_single_job(job_id) -> bool:
    """Processes a single ingestion job end-to-end."""
    async with async_session_maker() as db:
        # Lock job record
        query = (
            select(IngestionJob)
            .options(selectinload(IngestionJob.document))
            .where(IngestionJob.id == job_id)
            .with_for_update()
        )
        res = await db.execute(query)
        job = res.scalar_one_or_none()
        if not job or job.status != "queued":
            return False

        doc = job.document
        job.status = "processing"
        job.attempts += 1
        job.updated_at = datetime.now(timezone.utc)
        doc.status = "processing"
        await db.commit()

        logger.info("processing_document", document_id=str(doc.id), filename=doc.filename)

        try:
            # 1. Extract pages with word bboxes & strip repetitive headers/footers
            pages = await asyncio.to_thread(extract_pages_with_words, doc.storage_key)
            doc.page_count = len(pages)

            # 2. Chunk pages into ~250 token windows preserving bboxes & max 2 pages invariant
            chunks_data = create_chunks_from_pages(pages)

            # Idempotency: delete any existing chunks for this document
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))

            # 3. Generate embeddings in batches of 10
            batch_size = 10
            for i in range(0, len(chunks_data), batch_size):
                batch = chunks_data[i : i + batch_size]
                batch_texts = [c["text"] for c in batch]
                embeddings = await generate_embeddings_batch(batch_texts, task_type="RETRIEVAL_DOCUMENT")

                for chunk_info, emb in zip(batch, embeddings):
                    chunk_obj = Chunk(
                        document_id=doc.id,
                        chunk_index=chunk_info["chunk_index"],
                        page_start=chunk_info["page_start"],
                        page_end=chunk_info["page_end"],
                        text=chunk_info["text"],
                        bboxes=chunk_info["bboxes"],
                        embedding=emb,
                        embedding_model=settings.EMBED_MODEL,
                        embedding_dim=settings.EMBED_DIM,
                    )
                    db.add(chunk_obj)

                job.progress = min(len(pages), int((i + len(batch)) / max(1, len(chunks_data)) * len(pages)))
                job.updated_at = datetime.now(timezone.utc)
                await db.commit()

            # Mark as done & ready
            job.status = "done"
            job.progress = len(pages)
            job.updated_at = datetime.now(timezone.utc)
            doc.status = "ready"
            await db.commit()

            logger.info("document_ingestion_complete", document_id=str(doc.id), chunks_count=len(chunks_data))
            return True

        except Exception as exc:
            logger.error("document_ingestion_failed", document_id=str(doc.id), error=str(exc))
            job.status = "failed"
            job.last_error = str(exc)
            job.updated_at = datetime.now(timezone.utc)
            doc.status = "failed"
            doc.error = str(exc)
            await db.commit()
            return False


async def run_worker_loop():
    """Main worker loop that polls for queued jobs with SKIP LOCKED."""
    logger.info("ingestion_worker_started")
    await recover_stale_jobs()

    while True:
        try:
            async with async_session_maker() as db:
                # Find next queued job with SKIP LOCKED
                query = text(
                    """
                    SELECT id FROM ingestion_jobs
                    WHERE status = 'queued'
                    ORDER BY updated_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1;
                    """
                )
                res = await db.execute(query)
                row = res.fetchone()

            if row:
                job_id = row[0]
                await process_single_job(job_id)
            else:
                # Idle wait
                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("ingestion_worker_stopping")
            break
        except Exception as exc:
            logger.error("worker_loop_error", error=str(exc))
            await asyncio.sleep(2.0)
