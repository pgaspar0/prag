import asyncio
import uuid
from typing import Any, Dict, List, Optional
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalQuestion, EvalResult, EvalRun
from app.db.session import async_session_maker, get_db
from app.evals.runner import run_eval_benchmark

logger = structlog.get_logger()
router = APIRouter(prefix="/evals", tags=["evals"])


class RunEvalRequest(BaseModel):
    split: str = Field(default="dev", pattern="^(dev|test)$")
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class EvalRunListItem(BaseModel):
    id: uuid.UUID
    split: str
    config: Dict[str, Any]
    summary: Optional[Dict[str, Any]]
    created_at: str


class EvalResultItem(BaseModel):
    question_id: uuid.UUID
    question: str
    qtype: str
    expected_pages: Optional[List[int]]
    must_contain: Optional[List[str]]
    retrieved_pages: Optional[List[int]]
    cited_pages: Optional[List[int]]
    refused: Optional[bool]
    citation_valid: Optional[bool]
    retrieval_hit: Optional[bool]
    passed: Optional[bool]


class EvalRunDetail(BaseModel):
    id: uuid.UUID
    split: str
    config: Dict[str, Any]
    summary: Optional[Dict[str, Any]]
    created_at: str
    results: List[EvalResultItem]


async def _run_benchmark_background(split: str, threshold: Optional[float]) -> None:
    """Background worker for eval benchmark execution."""
    try:
        async with async_session_maker() as db:
            run, summary = await run_eval_benchmark(
                db=db, split=split, sim_threshold=threshold
            )
            logger.info("eval_run_completed", run_id=str(run.id), split=split)
    except Exception as exc:
        logger.error("eval_run_background_failed", error=str(exc))


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_eval_run(
    payload: RunEvalRequest,
    background_tasks: BackgroundTasks,
):
    """
    Triggers an automated benchmark evaluation run in the background.
    Returns 202 Accepted.
    """
    background_tasks.add_task(
        _run_benchmark_background,
        split=payload.split,
        threshold=payload.threshold,
    )
    return {
        "status": "queued",
        "split": payload.split,
        "message": f"Benchmark run on split '{payload.split}' has been queued.",
    }


@router.get("/runs", response_model=List[EvalRunListItem])
async def list_eval_runs(
    limit: int = Query(20, ge=1, le=100),
    split: Optional[str] = Query(None, pattern="^(dev|test)$"),
    db: AsyncSession = Depends(get_db),
):
    """Lists history of benchmark evaluation runs."""
    stmt = select(EvalRun).order_by(desc(EvalRun.created_at)).limit(limit)
    if split:
        stmt = stmt.where(EvalRun.split == split)

    res = await db.execute(stmt)
    runs = res.scalars().all()

    return [
        EvalRunListItem(
            id=r.id,
            split=r.split,
            config=r.config,
            summary=r.summary,
            created_at=r.created_at.isoformat(),
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=EvalRunDetail)
async def get_eval_run_detail(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieves full detail of an evaluation run including per-question results."""
    stmt_run = select(EvalRun).where(EvalRun.id == run_id)
    res_run = await db.execute(stmt_run)
    run = res_run.scalars().first()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation run '{run_id}' not found.",
        )

    # Join results with question metadata
    stmt_results = (
        select(EvalResult, EvalQuestion)
        .join(EvalQuestion, EvalResult.question_id == EvalQuestion.id)
        .where(EvalResult.run_id == run.id)
        .order_by(EvalQuestion.qtype, EvalQuestion.question)
    )
    res_results = await db.execute(stmt_results)
    rows = res_results.all()

    result_items = [
        EvalResultItem(
            question_id=q.id,
            question=q.question,
            qtype=q.qtype,
            expected_pages=q.expected_pages,
            must_contain=q.must_contain,
            retrieved_pages=r.retrieved_pages,
            cited_pages=r.cited_pages,
            refused=r.refused,
            citation_valid=r.citation_valid,
            retrieval_hit=r.retrieval_hit,
            passed=r.passed,
        )
        for r, q in rows
    ]

    return EvalRunDetail(
        id=run.id,
        split=run.split,
        config=run.config,
        summary=run.summary,
        created_at=run.created_at.isoformat(),
        results=result_items,
    )
