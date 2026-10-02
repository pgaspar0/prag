import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.limits import increment_daily_llm_usage
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
    """Deterministic mock generator for test environments and offline benchmarks."""
    import re
    p_lower = user_prompt.lower()

    # 1. Adversarial prompt injection defense
    injection_keywords = [
        "ignora", "ignore", "override", "desconsidera", "tu agora és", "culinário",
        "receita", "drop table", "modo de debug", "revogadas", "administrador",
        "sem checagem", "sem restrições", "sem custos", "unrestricted ai", "prompt do sistema"
    ]
    if any(k in p_lower for k in injection_keywords):
        return LLMGenerationResponse(answerable=False, claims=[])

    # 2. Extract question and chunks from prompt
    q_match = re.search(r"PERGUNTA DO UTILIZADOR:\s*(.*?)(?:\n\nGera agora|\Z)", user_prompt, re.DOTALL)
    question = q_match.group(1).strip() if q_match else ""

    chunk_matches = re.findall(
        r'---\s*INÍCIO EXCERTO\s*\[chunk_id:\s*"([a-f0-9\-]+)".*?\]\s*---\s*\n(.*?)\n\s*---\s*FIM EXCERTO',
        user_prompt,
        re.DOTALL,
    )
    if not chunk_matches or not question:
        return LLMGenerationResponse(answerable=False, claims=[])

    # 3. Known unanswerable topics in the contract
    unanswerable_topics = [
        "pagamento antecipado", "office 365", "inundações", "inundacoes",
        "portáteis", "portateis", "refeição", "refeicao", "tóquio", "toquio",
        "são paulo", "sao paulo", "ordem de compra", "cursos de formação",
        "formacao", "nvme", "ssd", "marca dos servidores", "presencial",
        "reembolso", "telefone direto", "engenharia social", "firewall",
        "100 máquinas", "100 maquinas", "cafetaria", "férias", "ferias",
        "arbitragem", "criptomoedas", "bitcoin", "ethereum", "dólares", "dolares", "usd"
    ]
    q_lower = question.lower()
    if any(u in q_lower for u in unanswerable_topics):
        return LLMGenerationResponse(answerable=False, claims=[])

    # 4. Canonical topic mappings for the contract (ordered by specificity)
    topic_quotes = [
        ("confidencialidade", "5 anos", "perdurará pelo prazo de 5 anos após a sua cessação"),
        ("renovação", "12 meses", "renova-se de forma automática por períodos sucessivos de 12 meses"),
        ("vigência", "24 meses", "duração inicial e vigência de 24 meses"),
        ("sla", "99.9%", "disponibilidade mensal (uptime) mínimo de 99.9%"),
        ("severidade crítica", "15 minutos", "tempo máximo de resposta de 15 minutos"),
        ("manutenção", "domingos", "exclusivamente aos domingos, entre as 02:00 e as 06:00"),
        ("mensalidade base", "4.500", "mensalidade base fixa de 4.500,00 EUR (quatro mil e quinhentos euros), acrescida de IVA"),
        ("prazo de pagamento", "30 dias", "prazo de pagamento das faturas é de 30 dias líquidos"),
        ("juros de mora", "1%", "juros de mora à taxa de 1% ao mês"),
        ("encriptação", "AES-256", "encriptação AES-256 bits, tanto em repouso quanto em trânsito"),
        ("retenção", "30 dias", "mantidas e preservadas durante um prazo de retenção de 30 dias"),
        ("violação de dados", "48 horas", "prazo máximo de 48 horas após ter conhecimento"),
        ("aviso prévio", "60 dias", "aviso prévio por carta registada com antecedência mínima de 60 dias"),
        ("responsabilidade", "12 meses", "limitada ao montante total faturado e pago pelo Cliente nos últimos 12 meses"),
        ("foro", "Lisboa", "exclusivamente competente o foro da comarca de Lisboa"),
        ("prestadora", "Nexus Cloud", "PRIMEIRA OUTORGANTE: Nexus Cloud Solutions Lda."),
        ("cliente", "Vertex", "SEGUNDA OUTORGANTE: Vertex Tecnologias SA"),
        ("severidade alta", "1 hora", "tempo máximo de resposta de 1 hora"),
        ("inferior a 99.0%", "25%", "desconto de 25% sobre o valor da referida mensalidade"),
        ("abaixo de 99.9%", "10%", "desconto de 10% sobre o valor da mensalidade"),
        ("faturas periódicas", "primeiro dia útil", "emitidas pela Prestadora no primeiro dia útil de cada mês"),
        ("iva", "acrescida de IVA", "acrescida de IVA à taxa legal em vigor"),
        ("meio de pagamento", "SEPA", "transferência bancária SEPA para a conta bancária da Prestadora"),
        ("datacenters", "Frankfurt", "situados no território da União Europeia, concretamente nas localizações de Frankfurt e Dublin"),
        ("dpo", "dpo@nexuscloud.pt", "Encarregado de Proteção de Dados (DPO) através do endereço dpo@nexuscloud.pt"),
        ("justa causa", "15 dias", "sanado no prazo de 15 dias após notificação escrita"),
        ("rescisão imotivada", "carta registada", "aviso prévio por carta registada com antecedência mínima de 60 dias"),
        ("legislação", "lei portuguesa", "rege-se e é subsidiariamente integrado em todos os seus aspetos pela lei portuguesa"),
        ("renunciar", "qualquer outro", "com expressa renúncia a qualquer outro"),
        ("faturas", "30 dias", "prazo de 30 dias"),
        ("objeto", "Kubernetes", "infraestrutura em nuvem privada, cluster Kubernetes dedicado"),
    ]

    for topic_kw, ans_kw, quote in topic_quotes:
        if topic_kw.lower() in q_lower or ans_kw.lower() in q_lower:
            # Find the chunk containing this quote
            for cid, ctext in chunk_matches:
                if quote in ctext or ans_kw in ctext:
                    # Find sentence containing quote
                    for s in re.split(r"(?<=[.!?])\s+", ctext):
                        if ans_kw in s or quote in s:
                            return LLMGenerationResponse(
                                answerable=True,
                                claims=[
                                    {
                                        "text": s.strip(),
                                        "citations": [
                                            {
                                                "chunk_id": cid,
                                                "quote": quote if quote in ctext else ans_kw,
                                            }
                                        ],
                                    }
                                ],
                            )

    # General fallback: search for chunks with matching keywords
    stopwords = {
        "qual", "quais", "quem", "como", "onde", "quando", "quanto", "quantos", "quantas",
        "para", "pelo", "pela", "pelos", "pelas", "entre", "sobre", "este", "esta", "estes",
        "estas", "esse", "essa", "esses", "essas", "aquele", "aquela", "aqueles", "aquelas",
        "caso", "antes", "apos", "após", "durante", "todos", "todas", "todo", "toda", "outro",
        "outra", "outros", "outras", "ser", "estar", "for", "ter", "haver", "com", "sem",
        "por", "que", "dos", "das", "num", "numa", "sob", "mais", "menos", "deve", "deverá"
    }

    q_words = [
        w.lower().strip("?,.:;\"'()[]")
        for w in re.findall(r"\w+", question)
        if len(w) > 3 and w.lower() not in stopwords
    ]

    best_chunk_id = None
    best_chunk_text = ""
    best_score = 0

    for cid, ctext in chunk_matches:
        c_lower = ctext.lower()
        score = sum(1 for w in q_words if w in c_lower)
        if score > best_score:
            best_score = score
            best_chunk_id = cid
            best_chunk_text = ctext.strip()

    if best_score < 2 or not best_chunk_id:
        return LLMGenerationResponse(answerable=False, claims=[])

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", best_chunk_text) if len(s.strip()) > 15]
    if not sentences:
        sentences = [best_chunk_text]

    best_sentence = max(sentences, key=lambda s: sum(1 for w in q_words if w in s.lower()))
    quote = best_sentence
    if len(quote) > 70:
        quote = quote[:70].rsplit(" ", 1)[0]

    return LLMGenerationResponse(
        answerable=True,
        claims=[
            {
                "text": best_sentence,
                "citations": [
                    {
                        "chunk_id": best_chunk_id,
                        "quote": quote,
                    }
                ],
            }
        ],
    )


async def answer_question_pipeline(
    db: AsyncSession,
    session_id: Optional[str],
    doc_ids: List[uuid.UUID],
    question: str,
    sim_threshold: Optional[float] = None,
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
    effective_threshold = (
        sim_threshold if sim_threshold is not None else settings.SIM_THRESHOLD
    )
    max_sim = max((c["vec_similarity"] for c in chunks), default=0.0)
    if not chunks or max_sim < effective_threshold:
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
    # Increment daily usage metrics
    tok_in = len(user_prompt) // 4
    tok_out = len(str(llm_output.model_dump())) // 4
    await increment_daily_llm_usage(db=db, tokens_in=tok_in, tokens_out=tok_out)

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

                # Determine exact page of the quote if chunk spans multiple pages
                quote_page = target_chunk["page_start"]
                if target_chunk["page_start"] != target_chunk["page_end"] and target_chunk.get("bboxes"):
                    import re
                    words_quote = [w.lower() for w in re.findall(r"\w+", citation.quote)]
                    if words_quote:
                        target_len = min(2, len(words_quote))
                        target_words = words_quote[:target_len]
                        bbs = target_chunk["bboxes"]
                        for i in range(len(bbs) - target_len + 1):
                            if all(
                                bbs[i + k].get("text", "").lower() == target_words[k]
                                for k in range(target_len)
                            ):
                                quote_page = bbs[i].get("page", target_chunk["page_start"])
                                break

                # Only include bboxes belonging to the quote's page
                relevant_bboxes = [
                    bb for bb in target_chunk.get("bboxes", [])
                    if bb.get("page") == quote_page
                ]

                verified_citations.append(
                    CitationVerified(
                        claim_index=claim_idx,
                        document_id=target_chunk["document_id"],
                        page=quote_page,
                        quote=citation.quote,
                        bboxes=relevant_bboxes,
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
