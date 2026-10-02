import uuid
from typing import Any, Dict, List
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def search_hybrid(
    db: AsyncSession,
    doc_ids: List[uuid.UUID],
    query_text: str,
    query_embedding: List[float],
    top_k: int = 8,
    limit_candidates: int = 50,
) -> List[Dict[str, Any]]:
    """
    Executes a hybrid search combining:
    1. Vector Cosine Distance (HNSW index)
    2. PostgreSQL Full-Text Search (tsvector GIN index with 'portuguese' regconfig)
    using Reciprocal Rank Fusion (RRF, k=60).

    Returns top_k chunks ordered by RRF score, with individual similarity scores.
    """
    if not doc_ids:
        return []

    # Clean query text for websearch_to_tsquery
    clean_qtext = query_text.strip()
    if not clean_qtext:
        clean_qtext = "documento"

    qvec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    doc_uuid_list = [uuid.UUID(str(d)) for d in doc_ids]

    sql_query = text(
        """
        WITH vec AS (
            SELECT 
                id, 
                row_number() OVER (ORDER BY embedding <=> CAST(:qvec AS vector)) AS r,
                1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
            FROM chunks 
            WHERE document_id = ANY(:doc_ids)
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:qvec AS vector) ASC
            LIMIT :candidate_limit
        ),
        fts AS (
            SELECT 
                id, 
                row_number() OVER (ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('portuguese', :qtext)) DESC) AS r
            FROM chunks
            WHERE document_id = ANY(:doc_ids)
              AND tsv @@ websearch_to_tsquery('portuguese', :qtext)
            ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('portuguese', :qtext)) DESC
            LIMIT :candidate_limit
        )
        SELECT 
            c.id,
            c.document_id,
            c.chunk_index,
            c.page_start,
            c.page_end,
            c.text,
            c.bboxes,
            COALESCE(vec.similarity, 0.0) AS vec_similarity,
            COALESCE(1.0 / (60.0 + vec.r), 0.0) + COALESCE(1.0 / (60.0 + fts.r), 0.0) AS rrf_score
        FROM chunks c
        LEFT JOIN vec ON vec.id = c.id
        LEFT JOIN fts ON fts.id = c.id
        WHERE vec.id IS NOT NULL OR fts.id IS NOT NULL
        ORDER BY rrf_score DESC
        LIMIT :top_k;
        """
    )

    try:
        res = await db.execute(
            sql_query,
            {
                "doc_ids": doc_uuid_list,
                "qvec": qvec_str,
                "qtext": clean_qtext,
                "candidate_limit": limit_candidates,
                "top_k": top_k,
            },
        )
        rows = res.fetchall()

        results = []
        for r in rows:
            results.append({
                "id": str(r[0]),
                "document_id": str(r[1]),
                "chunk_index": r[2],
                "page_start": r[3],
                "page_end": r[4],
                "text": r[5],
                "bboxes": r[6],
                "vec_similarity": float(r[7]),
                "rrf_score": float(r[8]),
            })

        return results

    except Exception as exc:
        logger.error("hybrid_search_failed", error=str(exc))
        # Fallback to pure vector search if FTS query syntax fails on special characters
        return await _search_vector_fallback(db, doc_ids, query_embedding, top_k)


async def _search_vector_fallback(
    db: AsyncSession,
    doc_ids: List[uuid.UUID],
    query_embedding: List[float],
    top_k: int = 8,
) -> List[Dict[str, Any]]:
    """Pure vector search fallback in case of FTS syntax issues."""
    qvec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    doc_uuid_list = [uuid.UUID(str(d)) for d in doc_ids]

    sql_query = text(
        """
        SELECT 
            id,
            document_id,
            chunk_index,
            page_start,
            page_end,
            text,
            bboxes,
            1 - (embedding <=> CAST(:qvec AS vector)) AS vec_similarity,
            1 - (embedding <=> CAST(:qvec AS vector)) AS rrf_score
        FROM chunks
        WHERE document_id = ANY(:doc_ids)
          AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:qvec AS vector) ASC
        LIMIT :top_k;
        """
    )

    res = await db.execute(
        sql_query,
        {
            "doc_ids": doc_uuid_list,
            "qvec": qvec_str,
            "top_k": top_k,
        },
    )
    rows = res.fetchall()

    return [
        {
            "id": str(r[0]),
            "document_id": str(r[1]),
            "chunk_index": r[2],
            "page_start": r[3],
            "page_end": r[4],
            "text": r[5],
            "bboxes": r[6],
            "vec_similarity": float(r[7]),
            "rrf_score": float(r[8]),
        }
        for r in rows
    ]
