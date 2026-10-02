import asyncio
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Chunk, Document, EvalQuestion, EvalResult, EvalRun, QueryLog
from app.evals.metrics import (
    BenchmarkMetricsSummary,
    calculate_benchmark_metrics,
    check_answer_coverage,
)
from app.generation.pipeline import answer_question_pipeline
from app.generation.prompt import get_prompt_hash
from app.ingestion.chunker import create_chunks_from_pages
from app.ingestion.embeddings import generate_embedding
from app.ingestion.extract import extract_pages_with_words

logger = structlog.get_logger()

DATASET_PATH = Path(__file__).parent / "datasets" / "nexus_cloud_contract.json"


def get_git_commit() -> str:
    """Retrieves current git commit short hash."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"


def _generate_pdf_from_dataset(pages: List[Dict[str, Any]], target_path: str) -> None:
    """Creates a multi-page PDF with exact text from dataset using PyMuPDF."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    doc = pymupdf.open()
    for p in pages:
        # A4: 595 x 842 points
        page = doc.new_page(width=595, height=842)
        rect = pymupdf.Rect(50, 60, 545, 780)
        page.insert_textbox(rect, p["content"], fontsize=11, fontname="helv")
    doc.save(target_path)
    doc.close()


async def ensure_eval_dataset(db: AsyncSession) -> Tuple[Document, List[EvalQuestion]]:
    """
    Ensures that the benchmark demo document and eval questions are seeded in the database.
    Idempotent: skips document creation if already present and ready.
    """
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Evaluation dataset not found at {DATASET_PATH}")

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    doc_meta = data["document"]
    filename = doc_meta["filename"]

    # Check if document already exists
    stmt = select(Document).where(Document.filename == filename, Document.is_demo.is_(True))
    res = await db.execute(stmt)
    doc = res.scalars().first()

    if not doc:
        doc_id = uuid.uuid4()
        storage_dir = Path(settings.STORAGE_DIR)
        storage_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = str(storage_dir / f"{doc_id}.pdf")

        _generate_pdf_from_dataset(doc_meta["pages"], pdf_path)

        with open(pdf_path, "rb") as f:
            file_bytes = f.read()
            sha256 = hashlib.sha256(file_bytes).hexdigest()

        doc = Document(
            id=doc_id,
            session_id=None,
            filename=filename,
            sha256=sha256,
            storage_key=pdf_path,
            page_count=len(doc_meta["pages"]),
            status="ready",
            is_demo=True,
        )
        db.add(doc)
        await db.flush()

        # Extract and chunk
        pages = extract_pages_with_words(pdf_path)
        chunk_dicts = create_chunks_from_pages(pages, target_words=180, overlap_words=25)

        for c_dict in chunk_dicts:
            emb = await generate_embedding(c_dict["text"], task_type="RETRIEVAL_DOCUMENT")
            chunk = Chunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=c_dict["chunk_index"],
                page_start=c_dict["page_start"],
                page_end=c_dict["page_end"],
                text=c_dict["text"],
                bboxes=c_dict["bboxes"],
                embedding=emb,
                embedding_model=settings.EMBED_MODEL,
                embedding_dim=settings.EMBED_DIM,
            )
            db.add(chunk)

        await db.commit()
        logger.info("eval_document_seeded", doc_id=str(doc.id), chunks_count=len(chunk_dicts))

    # Check questions
    stmt_q = select(EvalQuestion).where(EvalQuestion.document_id == doc.id)
    res_q = await db.execute(stmt_q)
    questions = list(res_q.scalars().all())

    if not questions:
        for q_data in data["questions"]:
            q = EvalQuestion(
                id=uuid.uuid4(),
                document_id=doc.id,
                split=q_data["split"],
                qtype=q_data["qtype"],
                question=q_data["question"],
                expected_pages=q_data.get("expected_pages"),
                must_contain=q_data.get("must_contain"),
            )
            db.add(q)
        await db.commit()

        res_q = await db.execute(stmt_q)
        questions = list(res_q.scalars().all())
        logger.info("eval_questions_seeded", count=len(questions))

    return doc, questions


async def run_eval_benchmark(
    db: AsyncSession,
    split: str = "dev",
    sim_threshold: Optional[float] = None,
) -> Tuple[EvalRun, BenchmarkMetricsSummary]:
    """
    Executes benchmark evaluation on the specified split (dev or test).
    Records run and question-level results to PostgreSQL.
    """
    doc, all_questions = await ensure_eval_dataset(db)
    questions = [q for q in all_questions if q.split == split]

    if not questions:
        raise ValueError(f"No questions found for split '{split}'")

    effective_threshold = (
        sim_threshold if sim_threshold is not None else settings.SIM_THRESHOLD
    )

    run_config = {
        "split": split,
        "gen_model": settings.GEN_MODEL,
        "embed_model": settings.EMBED_MODEL,
        "embed_dim": settings.EMBED_DIM,
        "chunk_size": 180,
        "chunk_overlap": 25,
        "top_k": 8,
        "sim_threshold": effective_threshold,
        "prompt_hash": get_prompt_hash(),
        "git_commit": get_git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    eval_run = EvalRun(
        id=uuid.uuid4(),
        split=split,
        config=run_config,
        summary=None,
    )
    db.add(eval_run)
    await db.flush()

    # Load document chunks to resolve chunk_id -> pages
    stmt_chunks = select(Chunk).where(Chunk.document_id == doc.id)
    doc_chunks_list = (await db.execute(stmt_chunks)).scalars().all()
    chunk_page_map: Dict[str, List[int]] = {
        str(c.id): list(range(c.page_start, c.page_end + 1))
        for c in doc_chunks_list
    }

    eval_items: List[Dict[str, Any]] = []

    for q in questions:
        response = await answer_question_pipeline(
            db=db,
            session_id=None,
            doc_ids=[doc.id],
            question=q.question,
            sim_threshold=effective_threshold,
        )

        # Retrieve chunk pages that were actually fetched by hybrid search
        stmt_log = (
            select(QueryLog)
            .where(QueryLog.question == q.question)
            .order_by(QueryLog.created_at.desc())
        )
        log_entry = (await db.execute(stmt_log)).scalars().first()

        retrieved_pages_set = set()
        if log_entry and log_entry.retrieved:
            for item in log_entry.retrieved:
                cid = item.get("chunk_id")
                if cid and cid in chunk_page_map:
                    retrieved_pages_set.update(chunk_page_map[cid])

        retrieved_pages = sorted(list(retrieved_pages_set))
        cited_pages = sorted(list({c.page for c in response.citations}))

        # Check retrieval hit against expected_pages
        retrieval_hit: Optional[bool] = None
        if q.expected_pages:
            matches = set(retrieved_pages).intersection(set(q.expected_pages))
            retrieval_hit = len(matches) > 0
        else:
            retrieval_hit = None

        # Check citation validity
        citation_valid: Optional[bool] = None
        if not response.refused:
            citation_valid = len(response.citations) > 0
        else:
            citation_valid = True

        # Check answer coverage
        coverage_ok = check_answer_coverage(response.answer, q.must_contain)

        # Determine pass/fail according to question type
        passed = False
        if q.qtype == "answerable":
            cited_match = bool(set(cited_pages).intersection(set(q.expected_pages)))
            passed = bool(
                retrieval_hit is True
                and not response.refused
                and citation_valid is True
                and cited_match
                and coverage_ok
            )
        elif q.qtype == "unanswerable":
            passed = bool(response.refused is True)
        elif q.qtype == "injection":
            passed = bool(response.refused is True)

        eval_result = EvalResult(
            run_id=eval_run.id,
            question_id=q.id,
            retrieved_pages=retrieved_pages,
            cited_pages=cited_pages,
            refused=response.refused,
            citation_valid=citation_valid,
            retrieval_hit=retrieval_hit,
            passed=passed,
        )
        db.add(eval_result)

        eval_items.append({
            "qtype": q.qtype,
            "expected_pages": q.expected_pages,
            "must_contain": q.must_contain,
            "retrieved_pages": retrieved_pages,
            "cited_pages": cited_pages,
            "refused": response.refused,
            "citation_valid": citation_valid,
            "retrieval_hit": retrieval_hit,
            "passed": passed,
            "answer": response.answer,
        })

    summary = calculate_benchmark_metrics(eval_items)
    eval_run.summary = summary.model_dump()
    await db.commit()

    return eval_run, summary


async def calibrate_thresholds(
    db: AsyncSession,
    split: str = "dev",
    thresholds: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """
    Evaluates different cosine similarity thresholds on the dev split
    to balance correct refusals vs. undue refusals.
    """
    if thresholds is None:
        thresholds = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]

    calibration_results = []
    for thresh in thresholds:
        run, summary = await run_eval_benchmark(db=db, split=split, sim_threshold=thresh)
        calibration_results.append({
            "threshold": thresh,
            "run_id": str(run.id),
            "correct_refusal_rate": summary.correct_refusal.rate,
            "correct_refusal_ci": summary.correct_refusal.formatted,
            "undue_refusal_rate": summary.undue_refusal.rate,
            "undue_refusal_ci": summary.undue_refusal.formatted,
            "overall_pass_rate": summary.overall_pass.rate,
            "overall_pass_ci": summary.overall_pass.formatted,
        })

    return calibration_results
