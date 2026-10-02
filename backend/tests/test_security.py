import asyncio
from datetime import date, datetime, timedelta, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.config import settings
from app.core.limits import (
    DAILY_LLM_CAP_EXCEEDED_MSG,
    check_daily_llm_cap,
    increment_daily_llm_usage,
    limiter,
)
from app.core.security import (
    SESSION_COOKIE_NAME,
    get_or_create_session_id,
    is_valid_session_id,
    sanitize_user_question,
)
from app.db.models import Chunk, DailyUsage, Document
from app.db.session import async_session_maker
from app.ingestion.worker import cleanup_expired_documents
from app.services.storage import (
    delete_storage_file,
    generate_presigned_url,
    get_local_file_path,
    is_r2_configured,
    save_file,
)


@pytest.mark.asyncio
async def test_session_isolation_crud_and_query(client: AsyncClient):
    """
    Ensures that documents uploaded by Session A are completely invisible,
    un-downloadable, un-deletable, and un-queryable by Session B.
    """
    session_a = f"session_sec_a_{uuid.uuid4().hex[:8]}"
    session_b = f"session_sec_b_{uuid.uuid4().hex[:8]}"

    doc_a_id = uuid.uuid4()
    doc_demo_id = uuid.uuid4()

    async with async_session_maker() as db:
        # Create private document for Session A
        doc_a = Document(
            id=doc_a_id,
            session_id=session_a,
            filename="contrato_privado_a.pdf",
            sha256=f"sha_a_{uuid.uuid4().hex[:8]}",
            storage_key="backend/storage/contrato_privado_a.pdf",
            status="ready",
            is_demo=False,
        )
        # Create public demo document
        doc_demo = Document(
            id=doc_demo_id,
            session_id=None,
            filename="manual_demo.pdf",
            sha256=f"sha_demo_{uuid.uuid4().hex[:8]}",
            storage_key="backend/storage/manual_demo.pdf",
            status="ready",
            is_demo=True,
        )
        db.add_all([doc_a, doc_demo])
        await db.commit()

    # Client authenticates as Session B
    client.cookies.set(SESSION_COOKIE_NAME, session_b)

    # 1. Listing documents for Session B
    res_list = await client.get("/documents")
    assert res_list.status_code == 200
    listed_ids = [d["id"] for d in res_list.json()]
    assert str(doc_a_id) not in listed_ids, "Session B should NOT see Session A documents"
    assert str(doc_demo_id) in listed_ids, "Session B should see public demo documents"

    # 2. Detail retrieval for Session A document by Session B
    res_detail = await client.get(f"/documents/{doc_a_id}")
    assert res_detail.status_code == 404

    # 3. File download for Session A document by Session B
    res_file = await client.get(f"/documents/{doc_a_id}/file")
    assert res_file.status_code == 404

    # 4. Deleting Session A document by Session B
    res_del = await client.delete(f"/documents/{doc_a_id}")
    assert res_del.status_code == 404

    # 5. Asking questions against Session A document by Session B
    res_ask = await client.post(
        "/ask",
        json={"document_ids": [str(doc_a_id)], "question": "Qual é o valor do contrato?"},
    )
    assert res_ask.status_code == 404
    assert "Nenhum dos documentos selecionados foi encontrado" in res_ask.json()["detail"]


@pytest.mark.asyncio
async def test_session_id_validation_and_sanitization():
    """
    Tests session_id validation: malicious characters, SQL injection patterns,
    or path traversal must be rejected.
    """
    assert is_valid_session_id("valid-uuid-session-1234_abc") is True
    assert is_valid_session_id(str(uuid.uuid4())) is True

    # Malicious or invalid session IDs
    assert is_valid_session_id("../../../etc/passwd") is False
    assert is_valid_session_id("session; DROP TABLE documents;--") is False
    assert is_valid_session_id("session with spaces") is False
    assert is_valid_session_id("<script>alert(1)</script>") is False
    assert is_valid_session_id("short") is False  # < 8 chars
    assert is_valid_session_id("a" * 70) is False  # > 64 chars


def test_sanitize_user_question():
    """Verifies that questions are trimmed, stripped of control chars, and bounded in length."""
    raw = "  \x00\x07Qual é a validade do contrato?\t\r\n  "
    sanitized = sanitize_user_question(raw)
    assert sanitized == "Qual é a validade do contrato?"

    huge_question = "A" * 1500
    bounded = sanitize_user_question(huge_question)
    assert len(bounded) == 1000


@pytest.mark.asyncio
async def test_ask_empty_question_returns_400(client: AsyncClient):
    """Empty or whitespace-only questions must return 400 Bad Request."""
    doc_id = uuid.uuid4()
    session_id = f"session_empty_{uuid.uuid4().hex[:8]}"

    async with async_session_maker() as db:
        doc = Document(
            id=doc_id,
            session_id=session_id,
            filename="doc.pdf",
            sha256=f"sha_{uuid.uuid4().hex[:8]}",
            storage_key="key",
            status="ready",
            is_demo=False,
        )
        db.add(doc)
        await db.commit()

    client.cookies.set(SESSION_COOKIE_NAME, session_id)
    res = await client.post(
        "/ask",
        json={"document_ids": [str(doc_id)], "question": "    \x00  "},
    )
    assert res.status_code == 400
    assert "A pergunta não pode estar vazia" in res.json()["detail"]


@pytest.mark.asyncio
async def test_daily_llm_cap_enforcement_and_increment():
    """
    Tests atomic increment of daily LLM usage and HTTP 429 trigger when cap is reached.
    """
    async with async_session_maker() as db:
        # 1. Increment usage
        new_count = await increment_daily_llm_usage(db=db, tokens_in=150, tokens_out=75)
        assert new_count >= 1

        # Check in DB
        res = await db.execute(
            select(DailyUsage).where(DailyUsage.usage_date == func.current_date())
        )
        usage_row = res.scalar_one()
        assert usage_row.llm_calls >= 1
        assert usage_row.tokens_in >= 150
        assert usage_row.tokens_out >= 75

        # 2. Simulate reaching cap by setting cap to 1
        orig_cap = settings.DAILY_LLM_CAP
        try:
            settings.DAILY_LLM_CAP = 1
            # Force usage row to cap
            usage_row.llm_calls = 1
            await db.commit()

            with pytest.raises(Exception) as exc_info:
                await check_daily_llm_cap(db)
            assert exc_info.value.status_code == 429
            assert DAILY_LLM_CAP_EXCEEDED_MSG in str(exc_info.value.detail)
        finally:
            settings.DAILY_LLM_CAP = orig_cap
            # Reset usage row
            usage_row.llm_calls = 0
            await db.commit()


@pytest.mark.asyncio
async def test_storage_presigned_url_generation():
    """
    Tests R2 presigned URL generation when configured, and graceful None fallback in local mode.
    """
    # In local test environment, R2 is not configured
    assert is_r2_configured() is False
    assert generate_presigned_url("documents/test.pdf") is None

    # Test with simulated R2 credentials
    orig_acc = settings.R2_ACCOUNT_ID
    orig_key = settings.R2_ACCESS_KEY_ID
    orig_sec = settings.R2_SECRET_ACCESS_KEY
    orig_bkt = settings.R2_BUCKET_NAME

    try:
        settings.R2_ACCOUNT_ID = "mockaccount123"
        settings.R2_ACCESS_KEY_ID = "mockkey456"
        settings.R2_SECRET_ACCESS_KEY = "mocksecret789"
        settings.R2_BUCKET_NAME = "prag-bucket"

        assert is_r2_configured() is True
        presigned = generate_presigned_url("documents/test.pdf", expires_in=600)
        assert presigned is not None
        assert "prag-bucket" in presigned or "mockaccount123" in presigned
        assert "X-Amz-Signature" in presigned or "AWSAccessKeyId" in presigned
    finally:
        settings.R2_ACCOUNT_ID = orig_acc
        settings.R2_ACCESS_KEY_ID = orig_key
        settings.R2_SECRET_ACCESS_KEY = orig_sec
        settings.R2_BUCKET_NAME = orig_bkt


@pytest.mark.asyncio
async def test_24_hour_document_auto_cleanup():
    """
    Tests that cleanup_expired_documents:
    - Deletes non-demo documents created > 24 hours ago.
    - Preserves non-demo documents created < 24 hours ago.
    - Preserves demo documents regardless of age.
    """
    now = datetime.now(timezone.utc)
    expired_user_doc_id = uuid.uuid4()
    recent_user_doc_id = uuid.uuid4()
    old_demo_doc_id = uuid.uuid4()

    async with async_session_maker() as db:
        expired_doc = Document(
            id=expired_user_doc_id,
            session_id="session_expired_test_123",
            filename="expired_doc.pdf",
            sha256=f"sha_{uuid.uuid4().hex[:8]}",
            storage_key="backend/storage/expired_doc.pdf",
            status="ready",
            is_demo=False,
            created_at=now - timedelta(hours=25),
        )
        recent_doc = Document(
            id=recent_user_doc_id,
            session_id="session_recent_test_123",
            filename="recent_doc.pdf",
            sha256=f"sha_{uuid.uuid4().hex[:8]}",
            storage_key="backend/storage/recent_doc.pdf",
            status="ready",
            is_demo=False,
            created_at=now - timedelta(hours=2),
        )
        old_demo_doc = Document(
            id=old_demo_doc_id,
            session_id=None,
            filename="demo_preserved.pdf",
            sha256=f"sha_{uuid.uuid4().hex[:8]}",
            storage_key="backend/storage/demo_preserved.pdf",
            status="ready",
            is_demo=True,
            created_at=now - timedelta(hours=72),
        )
        db.add_all([expired_doc, recent_doc, old_demo_doc])
        await db.commit()

    # Execute 24-hour cleanup
    deleted_count = await cleanup_expired_documents(max_age_hours=24)
    assert deleted_count >= 1

    # Verify database state
    async with async_session_maker() as db:
        res1 = await db.execute(select(Document).where(Document.id == expired_user_doc_id))
        assert res1.scalar_one_or_none() is None, "Expired user document should be deleted"

        res2 = await db.execute(select(Document).where(Document.id == recent_user_doc_id))
        assert res2.scalar_one_or_none() is not None, "Recent user document should be kept"

        res3 = await db.execute(select(Document).where(Document.id == old_demo_doc_id))
        assert res3.scalar_one_or_none() is not None, "Demo document must be kept regardless of age"


@pytest.mark.asyncio
async def test_ask_rate_limit_exceeded(client: AsyncClient):
    """Verifies that exceeding 10 queries/minute per IP triggers HTTP 429 Too Many Requests."""
    session_id = f"session_rate_{uuid.uuid4().hex[:8]}"
    client.cookies.set(SESSION_COOKIE_NAME, session_id)
    doc_id = uuid.uuid4()

    async with async_session_maker() as db:
        doc = Document(
            id=doc_id,
            session_id=session_id,
            filename="doc_rate.pdf",
            sha256=f"sha_{uuid.uuid4().hex[:8]}",
            storage_key="key",
            status="ready",
            is_demo=False,
        )
        db.add(doc)
        await db.commit()

    # The rate limit on /ask is 10/minute
    statuses = []
    for _ in range(12):
        res = await client.post(
            "/ask",
            json={"document_ids": [str(doc_id)], "question": "Pergunta para teste de limite?"},
        )
        statuses.append(res.status_code)

    assert 429 in statuses, f"Expected 429 in response statuses, got {statuses}"

