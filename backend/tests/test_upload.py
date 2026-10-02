import io
import fitz
import pytest
from httpx import AsyncClient


def create_valid_pdf_bytes(page_count: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page()
        text = f"Página {i + 1}. Este é um documento de teste corporativo contendo termos contratuais, cláusulas de pagamento e regras de conformidade com texto suficiente para exceder os limites mínimos de densidade textual exigidos pelo assistente RAG."
        page.insert_text((50, 50), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_scanned_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page()  # Page without text, simulating scanned image
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_upload_valid_pdf(client: AsyncClient):
    pdf_bytes = create_valid_pdf_bytes(2)
    files = {"file": ("contrato.pdf", pdf_bytes, "application/pdf")}

    response = await client.post("/documents", files=files)
    assert response.status_code == 202
    data = response.json()
    assert data["filename"] == "contrato.pdf"
    assert data["status"] == "queued"
    assert data["page_count"] == 2
    assert data["is_existing"] is False
    assert "document_id" in data
    assert "job_id" in data

    doc_id = data["document_id"]

    # Verify listing includes the document
    list_res = await client.get("/documents")
    assert list_res.status_code == 200
    docs = list_res.json()
    assert any(d["id"] == doc_id for d in docs)

    # Verify document detail
    detail_res = await client.get(f"/documents/{doc_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == doc_id

    # Verify file retrieval
    file_res = await client.get(f"/documents/{doc_id}/file")
    assert file_res.status_code == 200
    assert file_res.headers["content-type"] == "application/pdf"
    assert len(file_res.content) == len(pdf_bytes)

    # Test duplicate upload in same session
    dup_res = await client.post("/documents", files=files)
    assert dup_res.status_code == 200
    dup_data = dup_res.json()
    assert dup_data["document_id"] == doc_id
    assert dup_data["is_existing"] is True

    # Test deletion
    del_res = await client.delete(f"/documents/{doc_id}")
    assert del_res.status_code == 200

    # Ensure document is gone
    not_found_res = await client.get(f"/documents/{doc_id}")
    assert not_found_res.status_code == 404


@pytest.mark.asyncio
async def test_upload_invalid_magic_bytes(client: AsyncClient):
    fake_content = b"NOT_A_PDF_FILE_HEADER"
    files = {"file": ("malicious.pdf", fake_content, "application/pdf")}

    response = await client.post("/documents", files=files)
    assert response.status_code == 422
    assert "cabeçalho %PDF- ausente" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_scanned_pdf_rejection(client: AsyncClient):
    scanned_bytes = create_scanned_pdf_bytes()
    files = {"file": ("digitalizado.pdf", scanned_bytes, "application/pdf")}

    response = await client.post("/documents", files=files)
    assert response.status_code == 422
    assert "PDF digitalizado detetado" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_empty_file(client: AsyncClient):
    files = {"file": ("vazio.pdf", b"", "application/pdf")}
    response = await client.post("/documents", files=files)
    assert response.status_code == 400
    assert "Ficheiro vazio" in response.json()["detail"]
