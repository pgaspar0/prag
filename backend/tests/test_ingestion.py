import math
import uuid
from datetime import datetime, timezone, timedelta
import fitz
import pytest
from sqlalchemy import select

from app.db.models import Chunk, Document, IngestionJob
from app.db.session import async_session_maker
from app.ingestion.chunker import create_chunks_from_pages
from app.ingestion.embeddings import generate_synthetic_embedding, normalize_l2
from app.ingestion.extract import extract_pages_with_words
from app.ingestion.worker import process_single_job, recover_stale_jobs
from app.services.storage import save_file_locally


def create_sample_multi_page_pdf(num_pages: int = 4) -> bytes:
    doc = fitz.open()
    for p in range(num_pages):
        page = doc.new_page(width=595, height=842)
        # Repetitive header in top 10% (y = 30)
        page.insert_text((50, 30), "EMPRESA EXEMPLO S.A. - CONFIDENCIAL")

        # Body text
        body = (
            f"Seção {p + 1}: Termos Gerais de Prestação de Serviços. "
            f"O presente contrato regula os direitos e deveres na página {p + 1}. "
            "Todas as faturas deverão ser liquidadas no prazo de 30 dias a contar da emissão. "
            "A penalização por incumprimento contratual é fixada em 5 por cento do valor total da adjudicação. "
        ) * 3
        page.insert_text((50, 200), body)

        # Repetitive footer in bottom 10% (y = 800)
        page.insert_text((250, 800), "Página Oficial do Contrato")

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_embedding_l2_normalization():
    vec = [1.0, 2.0, 3.0, 4.0, 5.0]
    norm_vec = normalize_l2(vec)
    length = math.sqrt(sum(x * x for x in norm_vec))
    assert abs(length - 1.0) < 1e-6

    synthetic = generate_synthetic_embedding("texto de teste", dim=768)
    assert len(synthetic) == 768
    syn_len = math.sqrt(sum(x * x for x in synthetic))
    assert abs(syn_len - 1.0) < 1e-6


def test_chunker_invariants():
    # Mock 3 pages of words
    pages = [
        {
            "page_num": 1,
            "width": 595,
            "height": 842,
            "words": [(50, 100, 100, 120, f"w1_{i}", 0, 0, i) for i in range(150)],
        },
        {
            "page_num": 2,
            "width": 595,
            "height": 842,
            "words": [(50, 100, 100, 120, f"w2_{i}", 0, 0, i) for i in range(150)],
        },
        {
            "page_num": 3,
            "width": 595,
            "height": 842,
            "words": [(50, 100, 100, 120, f"w3_{i}", 0, 0, i) for i in range(150)],
        },
    ]

    chunks = create_chunks_from_pages(pages, target_words=100, overlap_words=20)
    assert len(chunks) > 0

    for chunk in chunks:
        # INVARIANT: never spans more than 2 pages
        assert chunk["page_end"] - chunk["page_start"] <= 1
        # Bounding boxes present
        assert len(chunk["bboxes"]) > 0
        assert all("page" in b and "x0" in b and "y0" in b for b in chunk["bboxes"])
        # Text is non-empty
        assert len(chunk["text"]) > 0


@pytest.mark.asyncio
async def test_end_to_end_worker_ingestion(tmp_path):
    pdf_bytes = create_sample_multi_page_pdf(num_pages=3)
    doc_id = uuid.uuid4()
    rand_suffix = uuid.uuid4().hex[:8]
    storage_key = await save_file_locally(str(doc_id), pdf_bytes)

    async with async_session_maker() as db:
        doc = Document(
            id=doc_id,
            session_id=f"test_worker_session_{rand_suffix}",
            filename="contrato_demo.pdf",
            sha256=f"dummy_sha_worker_{rand_suffix}",
            storage_key=storage_key,
            page_count=3,
            status="queued",
            is_demo=False,
        )
        db.add(doc)

        job = IngestionJob(
            document_id=doc_id,
            status="queued",
            progress=0,
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    # Run the worker processor on the job
    success = await process_single_job(job_id)
    assert success is True

    # Verify database state
    async with async_session_maker() as db:
        res_doc = await db.execute(select(Document).where(Document.id == doc_id))
        updated_doc = res_doc.scalar_one()
        assert updated_doc.status == "ready"
        assert updated_doc.page_count == 3

        res_job = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
        updated_job = res_job.scalar_one()
        assert updated_job.status == "done"
        assert updated_job.progress == 3

        res_chunks = await db.execute(
            select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
        )
        chunks = res_chunks.scalars().all()
        assert len(chunks) >= 3

        for ch in chunks:
            assert ch.embedding is not None
            assert len(ch.embedding) == 768
            assert ch.embedding_dim == 768
            assert ch.embedding_model is not None
            assert ch.page_end - ch.page_start <= 1
            assert len(ch.bboxes) > 0


@pytest.mark.asyncio
async def test_recover_stale_jobs():
    doc_id = uuid.uuid4()
    rand_suffix = uuid.uuid4().hex[:8]
    async with async_session_maker() as db:
        doc = Document(
            id=doc_id,
            session_id=f"test_stale_session_{rand_suffix}",
            filename="stale.pdf",
            sha256=f"stale_sha_{rand_suffix}",
            storage_key="dummy_path",
            status="processing",
        )
        db.add(doc)

        job = IngestionJob(
            document_id=doc_id,
            status="processing",
            # Simulated crash 10 minutes ago
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    # Run recovery
    await recover_stale_jobs()

    async with async_session_maker() as db:
        res = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
        recovered_job = res.scalar_one()
        assert recovered_job.status == "queued"
