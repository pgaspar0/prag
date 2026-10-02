import hashlib
import uuid
from typing import List
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import DocumentDetailResponse, DocumentResponse, DocumentUploadResponse
from app.core.limits import validate_pdf_upload
from app.core.security import get_or_create_session_id
from app.db.models import Document, IngestionJob
from app.db.session import get_db
from app.services.storage import delete_local_file, get_local_file_path, save_file_locally

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload and queue a PDF document for ingestion.
    Validates magic bytes, page count, and scanned PDF detection.
    Computes SHA-256 for deduplication per session.
    Returns 202 Accepted.
    """
    session_id = get_or_create_session_id(request, response)

    # 1. Validation
    content, page_count = await validate_pdf_upload(file)

    # 2. SHA-256 Deduplication check for this session
    sha256_hash = hashlib.sha256(content).hexdigest()

    existing_query = select(Document).options(selectinload(Document.ingestion_job)).where(
        Document.session_id == session_id,
        Document.sha256 == sha256_hash,
    )
    res = await db.execute(existing_query)
    existing_doc = res.scalar_one_or_none()

    if existing_doc:
        job_id = existing_doc.ingestion_job.id if existing_doc.ingestion_job else None
        response.status_code = status.HTTP_200_OK
        return DocumentUploadResponse(
            document_id=existing_doc.id,
            job_id=job_id,
            filename=existing_doc.filename,
            status=existing_doc.status,
            page_count=existing_doc.page_count or page_count,
            is_existing=True,
        )

    # 3. Save to storage
    doc_id = uuid.uuid4()
    storage_key = await save_file_locally(str(doc_id), content)

    # 4. Create document & ingestion job
    document = Document(
        id=doc_id,
        session_id=session_id,
        filename=file.filename or "document.pdf",
        sha256=sha256_hash,
        storage_key=storage_key,
        page_count=page_count,
        status="queued",
        is_demo=False,
    )
    db.add(document)

    job = IngestionJob(
        document_id=doc_id,
        status="queued",
        progress=0,
    )
    db.add(job)

    await db.commit()
    await db.refresh(document)
    await db.refresh(job)

    return DocumentUploadResponse(
        document_id=document.id,
        job_id=job.id,
        filename=document.filename,
        status=document.status,
        page_count=page_count,
        is_existing=False,
    )


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    List all documents available to the current session:
    user's own uploaded documents + public demo documents.
    """
    session_id = get_or_create_session_id(request, response)

    query = (
        select(Document)
        .options(selectinload(Document.ingestion_job))
        .where(
            or_(
                Document.session_id == session_id,
                Document.is_demo == True,  # noqa: E712
            )
        )
        .order_by(Document.created_at.desc())
    )
    res = await db.execute(query)
    docs = res.scalars().all()

    result = []
    for d in docs:
        prog = d.ingestion_job.progress if d.ingestion_job else 0
        result.append(
            DocumentResponse(
                id=d.id,
                filename=d.filename,
                status=d.status,
                page_count=d.page_count,
                is_demo=d.is_demo,
                created_at=d.created_at,
                progress=prog,
            )
        )
    return result


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific document if it belongs to session or is demo."""
    session_id = get_or_create_session_id(request, response)

    query = (
        select(Document)
        .options(selectinload(Document.ingestion_job))
        .where(
            Document.id == document_id,
            or_(
                Document.session_id == session_id,
                Document.is_demo == True,  # noqa: E712
            ),
        )
    )
    res = await db.execute(query)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento não encontrado ou sem permissão de acesso.",
        )

    prog = doc.ingestion_job.progress if doc.ingestion_job else 0
    return DocumentDetailResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        page_count=doc.page_count,
        is_demo=doc.is_demo,
        error=doc.error,
        created_at=doc.created_at,
        progress=prog,
    )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Serve the PDF file with HTTP Range support for page jumping in frontend viewer.
    """
    session_id = get_or_create_session_id(request, response)

    query = select(Document).where(
        Document.id == document_id,
        or_(
            Document.session_id == session_id,
            Document.is_demo == True,  # noqa: E712
        ),
    )
    res = await db.execute(query)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento não encontrado ou sem permissão de acesso.",
        )

    file_path = get_local_file_path(doc.storage_key)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ficheiro físico não encontrado no armazenamento.",
        )

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=doc.filename,
    )


@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    document_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Delete a user-owned document and its associated file."""
    session_id = get_or_create_session_id(request, response)

    query = select(Document).where(
        Document.id == document_id,
        Document.session_id == session_id,
    )
    res = await db.execute(query)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento não encontrado ou sem permissão para apagar.",
        )

    # Delete physical file
    await delete_local_file(doc.storage_key)

    # Delete database record (cascades to chunks and jobs)
    await db.delete(doc)
    await db.commit()

    return {"status": "deleted", "document_id": document_id}
