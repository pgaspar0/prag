from datetime import datetime
from typing import Any, Dict, List, Optional
import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QueryLog
from app.db.session import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/stats", tags=["stats"])


class LatencyAverages(BaseModel):
    embed_ms: float
    retrieve_ms: float
    generate_ms: float
    verify_ms: float
    total_ms: float
    p50_total_ms: float
    p95_total_ms: float


class RefusalBreakdown(BaseModel):
    total_refused: int
    total_answered: int
    refusal_rate: float
    by_reason: Dict[str, int]


class TokenAndCostStats(BaseModel):
    total_tokens_in: int
    total_tokens_out: int
    estimated_cost_usd: float
    tokens_saved_by_early_refusal: int
    estimated_savings_usd: float


class RecentQueryItem(BaseModel):
    id: str
    question: str
    refused: bool
    refusal_reason: Optional[str]
    latency_total_ms: int
    created_at: str


class SystemStatsResponse(BaseModel):
    total_queries: int
    refusals: RefusalBreakdown
    latencies: LatencyAverages
    token_cost: TokenAndCostStats
    recent_queries: List[RecentQueryItem]


@router.get("", response_model=SystemStatsResponse)
async def get_system_stats(
    db: AsyncSession = Depends(get_db),
):
    """
    Computes real-time system performance and observational analytics from query_log.
    Returns latency breakdown by phase, refusal rates, token metrics, and cost estimations.
    """
    # 1. Total count
    total_res = await db.execute(select(func.count(QueryLog.id)))
    total_queries = total_res.scalar() or 0

    if total_queries == 0:
        return SystemStatsResponse(
            total_queries=0,
            refusals=RefusalBreakdown(
                total_refused=0,
                total_answered=0,
                refusal_rate=0.0,
                by_reason={},
            ),
            latencies=LatencyAverages(
                embed_ms=0.0,
                retrieve_ms=0.0,
                generate_ms=0.0,
                verify_ms=0.0,
                total_ms=0.0,
                p50_total_ms=0.0,
                p95_total_ms=0.0,
            ),
            token_cost=TokenAndCostStats(
                total_tokens_in=0,
                total_tokens_out=0,
                estimated_cost_usd=0.0,
                tokens_saved_by_early_refusal=0,
                estimated_savings_usd=0.0,
            ),
            recent_queries=[],
        )

    # 2. Refusal counts & reasons
    refused_res = await db.execute(
        select(QueryLog.refused, QueryLog.refusal_reason, func.count(QueryLog.id))
        .group_by(QueryLog.refused, QueryLog.refusal_reason)
    )
    rows_ref = refused_res.all()

    total_refused = 0
    total_answered = 0
    by_reason: Dict[str, int] = {}

    for is_ref, reason, count in rows_ref:
        if is_ref:
            total_refused += count
            r_key = reason or "unspecified"
            by_reason[r_key] = by_reason.get(r_key, 0) + count
        else:
            total_answered += count

    refusal_rate = round(total_refused / total_queries, 4)

    # 3. Latencies across recent logs (sample of up to 500 queries)
    log_sample_stmt = (
        select(QueryLog.latency_ms, QueryLog.tokens_in, QueryLog.tokens_out)
        .order_by(desc(QueryLog.created_at))
        .limit(500)
    )
    log_sample_res = await db.execute(log_sample_stmt)
    sample_rows = log_sample_res.all()

    embed_times = []
    retrieve_times = []
    generate_times = []
    verify_times = []
    total_times = []
    tot_tok_in = 0
    tot_tok_out = 0

    for l_ms, t_in, t_out in sample_rows:
        if isinstance(l_ms, dict):
            embed_times.append(l_ms.get("embed", 0))
            retrieve_times.append(l_ms.get("retrieve", 0))
            generate_times.append(l_ms.get("generate", 0))
            verify_times.append(l_ms.get("verify", 0))
            total_times.append(l_ms.get("total", 0))
        if t_in:
            tot_tok_in += t_in
        if t_out:
            tot_tok_out += t_out

    def _avg(lst: List[int]) -> float:
        return round(sum(lst) / len(lst), 1) if lst else 0.0

    total_times.sort()
    p50 = total_times[int(len(total_times) * 0.5)] if total_times else 0.0
    p95 = total_times[int(len(total_times) * 0.95)] if total_times else 0.0

    latencies = LatencyAverages(
        embed_ms=_avg(embed_times),
        retrieve_ms=_avg(retrieve_times),
        generate_ms=_avg(generate_times),
        verify_ms=_avg(verify_times),
        total_ms=_avg(total_times),
        p50_total_ms=float(p50),
        p95_total_ms=float(p95),
    )

    # 4. Token & Cost estimation (Gemini 2.5 Flash: $0.075 / 1M in, $0.30 / 1M out)
    cost_usd = (tot_tok_in * 0.000000075) + (tot_tok_out * 0.00000030)
    early_refusals = by_reason.get("below_threshold", 0)
    tokens_saved = early_refusals * 1500
    savings_usd = tokens_saved * 0.000000075

    token_cost = TokenAndCostStats(
        total_tokens_in=tot_tok_in,
        total_tokens_out=tot_tok_out,
        estimated_cost_usd=round(cost_usd, 6),
        tokens_saved_by_early_refusal=tokens_saved,
        estimated_savings_usd=round(savings_usd, 6),
    )

    # 5. Recent queries (last 20)
    recent_stmt = (
        select(QueryLog.id, QueryLog.question, QueryLog.refused, QueryLog.refusal_reason, QueryLog.latency_ms, QueryLog.created_at)
        .order_by(desc(QueryLog.created_at))
        .limit(20)
    )
    recent_res = await db.execute(recent_stmt)
    recent_rows = recent_res.all()

    recent_queries = [
        RecentQueryItem(
            id=str(r[0]),
            question=r[1][:120] + ("..." if len(r[1]) > 120 else ""),
            refused=r[2],
            refusal_reason=r[3],
            latency_total_ms=r[4].get("total", 0) if isinstance(r[4], dict) else 0,
            created_at=r[5].isoformat() if isinstance(r[5], datetime) else str(r[5]),
        )
        for r in recent_rows
    ]

    return SystemStatsResponse(
        total_queries=total_queries,
        refusals=RefusalBreakdown(
            total_refused=total_refused,
            total_answered=total_answered,
            refusal_rate=refusal_rate,
            by_reason=by_reason,
        ),
        latencies=latencies,
        token_cost=token_cost,
        recent_queries=recent_queries,
    )
