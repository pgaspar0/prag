import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import QueryLog
from app.generation.prompt import SYSTEM_PROMPT, format_user_prompt
from app.generation.schema import (
    AskResponse,
    CitationVerified,
    LatencyBreakdown,
    LLMGenerationResponse,
)
from app.generation.verifier import verify_citation_quote
from app.ingestion.embeddings import generate_embedding
from app.retrieval.hybrid import search_hybrid

logger = structlog.get_logger()

REFUSAL_MESSAGE = "Não encontrei esta informação nos documentos fornecidos."


def _call_gemini_generate(user_prompt: str) -> LLMGenerationResponse:
    """Invokes Gemini Flash with structured JSON output."""
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your_gemini_api_key_here":
        # Deterministic mock fallback for local tests without API key
        return _mock_llm_response(user_prompt)

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=settings.GEN_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=LLMGenerationResponse,
            temperature=0.0,
        ),
    )

    data = json.loads(response.text)
    return LLMGenerationResponse.model_validate(data)


def _mock_llm_response(user_prompt: str) -> LLMGenerationResponse:
    """Mock generator for test environments."""
    # Look for known test terms in the prompt
    p_lower = user_prompt.lower()
    if "cláusula" in p_lower or "fatura" in p_lower or "pagamento" in p_lower:
        # Extract chunk_id from prompt if present
        import re
        match = re.search(r'chunk_id: "([a-f0-9\-]+)"', user_prompt)
        chunk_id = match.group(1) if match else str(uuid.uuid4())
        return LLMGenerationResponse(
            answerable=True,
            claims=[
                {
                    "text": "As faturas deverão ser liquidadas no prazo de 30 dias a contar da emissão.",
                    "citations": [
                        {
                            "chunk_id": chunk_id,
                            "quote": "prazo de 30 dias a contar da emissão",
                        }
                    ],
                }
            ],
        )
    return LLMGenerationResponse(answerable=False, claims=[])


async def answer_question_pipeline(
    db: AsyncSession,
    session_id: Optional[str],
    doc_ids: List[uuid.UUID],
    question: str,
) -> AskResponse:
    """
    Executes the complete 3-Gate RAG question answering pipeline:
    1. Retrieval via Hybrid Search (Vector + Full-Text RRF).
    2. Gate 1: Cosine similarity cutoff check.
    3. LLM generation with structured JSON schema.
    4. Gate 2: LLM answerability check.
    5. Gate 3: Deterministic string match verification of citations against chunk text.
    6. Logging to query_log table.
    """
    t_start = time.perf_counter()

    # 1. Embed question (RETRIEVAL_QUERY task type)
    t0 = time.perf_counter()
    q_emb = await generate_embedding(question, task_type="RETRIEVAL_QUERY")
    t_embed_ms = int((time.perf_counter() - t0) * 1000)

    # 2. Hybrid search
    t0 = time.perf_counter()
    chunks = await search_hybrid(
        db=db,
        doc_ids=doc_ids,
        query_text=question,
        query_embedding=q_emb,
        top_k=8,
    )
    t_retrieve_ms = int((time.perf_counter() - t0) * 1000)

    # Prepare retrieved info for query_log
    retrieved_log = [
        {
            "chunk_id": c["id"],
            "page": c["page_start"],
            "vec_similarity": round(c["vec_similarity"], 4),
            "rrf_score": round(c["rrf_score"], 4),
        }
        for c in chunks
    ]

    # GATE 1: Max Cosine Similarity Check
    max_sim = max((c["vec_similarity"] for c in chunks), default=0.0)
    if not chunks or max_sim < settings.SIM_THRESHOLD:
        t_total_ms = int((time.perf_counter() - t_start) * 1000)
        latencies = LatencyBreakdown(
            embed=t_embed_ms,
            retrieve=t_retrieve_ms,
            generate=0,
            verify=0,
            total=t_total_ms,
        )
        await _record_query_log(
            db=db,
            session_id=session_id,
            question=question,
            retrieved=retrieved_log,
            answer=None,
            refused=True,
            refusal_reason="below_threshold",
            latency_ms=latencies.model_dump(),
        )
        return AskResponse(
            refused=True,
            refusal_reason="below_threshold",
            answer=REFUSAL_MESSAGE,
            citations=[],
            latency_ms=latencies,
        )

    # 3. LLM Generation
    t0 = time.perf_counter()
    user_prompt = format_user_prompt(question, chunks)
    try:
        llm_output = await asyncio.to_thread(_call_gemini_generate, user_prompt)
    except Exception as exc:
        logger.error("llm_generation_error", error=str(exc))
        # Controlled fallback on LLM error
        llm_output = LLMGenerationResponse(answerable=False, claims=[])
    t_generate_ms = int((time.perf_counter() - t0) * 1000)

    # GATE 2: LLM answerability check
    if not llm_output.answerable or not llm_output.claims:
        t_total_ms = int((time.perf_counter() - t_start) * 1000)
        latencies = LatencyBreakdown(
            embed=t_embed_ms,
            retrieve=t_retrieve_ms,
            generate=t_generate_ms,
            verify=0,
            total=t_total_ms,
        )
        await _record_query_log(
            db=db,
            session_id=session_id,
            question=question,
            retrieved=retrieved_log,
            answer=llm_output.model_dump(),
            refused=True,
            refusal_reason="not_answerable",
            latency_ms=latencies.model_dump(),
        )
        return AskResponse(
            refused=True,
            refusal_reason="not_answerable",
            answer=REFUSAL_MESSAGE,
            citations=[],
            latency_ms=latencies,
        )

    # GATE 3: Deterministic Verification of Citations
    t0 = time.perf_counter()
    chunk_map: Dict[str, Dict[str, Any]] = {c["id"]: c for c in chunks}
    verified_claims: List[str] = []
    verified_citations: List[CitationVerified] = []

    for claim_idx, claim in enumerate(llm_output.claims):
        claim_has_valid_citation = False

        for citation in claim.citations:
            target_chunk = chunk_map.get(citation.chunk_id)
            if not target_chunk:
                continue

            # Verify substring match
            is_valid, _ = verify_citation_quote(citation.quote, target_chunk["text"])
            if is_valid:
                claim_has_valid_citation = True
                verified_citations.append(
                    CitationVerified(
                        claim_index=claim_idx,
                        document_id=target_chunk["document_id"],
                        page=target_chunk["page_start"],
                        quote=citation.quote,
                        bboxes=target_chunk.get("bboxes", []),
                    )
                )

        if claim_has_valid_citation:
            verified_claims.append(claim.text)

    t_verify_ms = int((time.perf_counter() - t0) * 1000)

    # If all claims failed citation verification, trigger refusal
    if not verified_claims or not verified_citations:
        t_total_ms = int((time.perf_counter() - t_start) * 1000)
        latencies = LatencyBreakdown(
            embed=t_embed_ms,
            retrieve=t_retrieve_ms,
            generate=t_generate_ms,
            verify=t_verify_ms,
            total=t_total_ms,
        )
        await _record_query_log(
            db=db,
            session_id=session_id,
            question=question,
            retrieved=retrieved_log,
            answer=llm_output.model_dump(),
            refused=True,
            refusal_reason="citation_verification_failed",
            latency_ms=latencies.model_dump(),
        )
        return AskResponse(
            refused=True,
            refusal_reason="citation_verification_failed",
            answer=REFUSAL_MESSAGE,
            citations=[],
            latency_ms=latencies,
        )

    final_answer = " ".join(verified_claims)
    t_total_ms = int((time.perf_counter() - t_start) * 1000)
    latencies = LatencyBreakdown(
        embed=t_embed_ms,
        retrieve=t_retrieve_ms,
        generate=t_generate_ms,
        verify=t_verify_ms,
        total=t_total_ms,
    )

    response_data = AskResponse(
        refused=False,
        refusal_reason=None,
        answer=final_answer,
        citations=verified_citations,
        latency_ms=latencies,
    )

    await _record_query_log(
        db=db,
        session_id=session_id,
        question=question,
        retrieved=retrieved_log,
        answer=response_data.model_dump(),
        refused=False,
        refusal_reason=None,
        latency_ms=latencies.model_dump(),
    )

    return response_data


async def _record_query_log(
    db: AsyncSession,
    session_id: Optional[str],
    question: str,
    retrieved: Any,
    answer: Any,
    refused: bool,
    refusal_reason: Optional[str],
    latency_ms: Any,
):
    """Persists query execution metrics in query_log table."""
    try:
        log_entry = QueryLog(
            session_id=session_id,
            question=question,
            retrieved=retrieved,
            answer=answer,
            refused=refused,
            refusal_reason=refusal_reason,
            latency_ms=latency_ms,
        )
        db.add(log_entry)
        await db.commit()
    except Exception as exc:
        logger.error("failed_saving_query_log", error=str(exc))
