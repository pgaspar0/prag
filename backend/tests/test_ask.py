import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Chunk, Document, QueryLog
from app.db.session import async_session_maker
from app.generation.pipeline import REFUSAL_MESSAGE
from app.generation.verifier import normalize_text_for_verification, verify_citation_quote
from app.ingestion.embeddings import generate_synthetic_embedding


def test_verifier_string_matching():
    # 1. Exact match with whitespace and capitalization differences
    chunk = "O pagamento de todas as faturas deve ocorrer no prazo de trinta (30) dias."
    quote = "O PAGAMENTO de todas as faturas"
    is_valid, method = verify_citation_quote(quote, chunk)
    assert is_valid is True
    assert "exact_substring" in method

    # 2. Curly quotes and special dashes
    chunk = 'A cláusula prevê: "serviços de alta disponibilidade - 99.9%".'
    quote = "“serviços de alta disponibilidade — 99.9%”"
    is_valid, _ = verify_citation_quote(quote, chunk)
    assert is_valid is True

    # 3. Hyphenation at line break
    chunk = "A contratação da compa-\nnhia fornecedora é imediata."
    quote = "A contratação da companhia fornecedora"
    is_valid, _ = verify_citation_quote(quote, chunk)
    assert is_valid is True

    # 4. Fabricated quote
    fake_quote = "O prazo de garantia será de dez anos sem encargos."
    is_valid, reason = verify_citation_quote(fake_quote, chunk)
    assert is_valid is False

    # 5. Too short quote (< 8 characters)
    short_quote = "prazo"
    is_valid, reason = verify_citation_quote(short_quote, chunk)
    assert is_valid is False
    assert reason == "quote_too_short"


@pytest.mark.asyncio
async def test_ask_endpoint_successful_answer_and_logging(client: AsyncClient):
    # Setup document and chunk in database
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    rand_suffix = uuid.uuid4().hex[:8]
    session_id = f"session_ask_test_{rand_suffix}"
    question = "Qual é o prazo para liquidação das faturas no contrato?"
    doc_text = "As faturas deverão ser liquidadas no prazo de 30 dias a contar da emissão pela empresa contratada."
    emb = generate_synthetic_embedding(question, dim=768)

    async with async_session_maker() as db:
        doc = Document(
            id=doc_id,
            session_id=session_id,
            filename="contrato_financeiro.pdf",
            sha256=f"sha_ask_{rand_suffix}",
            storage_key="dummy_key",
            status="ready",
            is_demo=False,
        )
        db.add(doc)

        chunk = Chunk(
            id=chunk_id,
            document_id=doc_id,
            chunk_index=0,
            page_start=2,
            page_end=2,
            text=doc_text,
            bboxes=[{"page": 2, "x0": 50, "y0": 100, "x1": 200, "y1": 120}],
            embedding=emb,
            embedding_model="gemini-embedding-001",
            embedding_dim=768,
        )
        db.add(chunk)
        await db.commit()

    # Query with the same session cookie
    client.cookies.set("session_id", session_id)

    payload = {
        "document_ids": [str(doc_id)],
        "question": "Qual é o prazo para liquidação das faturas no contrato?",
    }

    response = await client.post("/ask", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["refused"] is False
    assert data["refusal_reason"] is None
    assert len(data["citations"]) > 0
    assert data["citations"][0]["page"] == 2
    assert "prazo de 30 dias" in data["citations"][0]["quote"]
    assert "latency_ms" in data
    assert data["latency_ms"]["total"] >= 0

    # Verify query_log record
    async with async_session_maker() as db:
        res = await db.execute(
            select(QueryLog).where(QueryLog.session_id == session_id)
        )
        logs = res.scalars().all()
        assert len(logs) >= 1
        last_log = logs[-1]
        assert last_log.refused is False
        assert last_log.question == payload["question"]


@pytest.mark.asyncio
async def test_ask_endpoint_session_isolation(client: AsyncClient):
    # Create document under another session
    other_doc_id = uuid.uuid4()
    rand_suffix = uuid.uuid4().hex[:8]
    other_session = f"private_other_session_{rand_suffix}"

    async with async_session_maker() as db:
        doc = Document(
            id=other_doc_id,
            session_id=other_session,
            filename="privado.pdf",
            sha256=f"sha_priv_{rand_suffix}",
            storage_key="dummy_key",
            status="ready",
            is_demo=False,
        )
        db.add(doc)
        await db.commit()

    # User with a different session tries to access it
    client.cookies.set("session_id", f"my_different_session_{rand_suffix}")
    payload = {
        "document_ids": [str(other_doc_id)],
        "question": "O que diz o contrato?",
    }

    response = await client.post("/ask", json=payload)
    assert response.status_code == 404
    assert "Nenhum dos documentos selecionados foi encontrado" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ask_gate1_threshold_refusal(client: AsyncClient):
    # Create document with unrelated text
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    rand_suffix = uuid.uuid4().hex[:8]
    session_id = f"session_gate1_test_{rand_suffix}"
    doc_text = "Esta é uma receita de culinária para fazer bolo de chocolate com morangos."
    emb = generate_synthetic_embedding(doc_text, dim=768)

    async with async_session_maker() as db:
        doc = Document(
            id=doc_id,
            session_id=session_id,
            filename="receita.pdf",
            sha256=f"sha_gate1_{rand_suffix}",
            storage_key="dummy_key",
            status="ready",
            is_demo=False,
        )
        db.add(doc)

        chunk = Chunk(
            id=chunk_id,
            document_id=doc_id,
            chunk_index=0,
            page_start=1,
            page_end=1,
            text=doc_text,
            bboxes=[{"page": 1, "x0": 50, "y0": 50, "x1": 150, "y1": 70}],
            embedding=emb,
            embedding_model="gemini-embedding-001",
            embedding_dim=768,
        )
        db.add(chunk)
        await db.commit()

    client.cookies.set("session_id", session_id)
    # Ask something completely off-topic where similarity will fall below 0.55
    payload = {
        "document_ids": [str(doc_id)],
        "question": "Qual é a velocidade máxima da nave espacial Voyager?",
    }

    response = await client.post("/ask", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is True
    assert data["refusal_reason"] in ("below_threshold", "not_answerable")
    assert data["answer"] == REFUSAL_MESSAGE
    assert len(data["citations"]) == 0
