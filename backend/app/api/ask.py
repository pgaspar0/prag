from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_or_create_session_id
from app.db.models import Document
from app.db.session import get_db
from app.generation.pipeline import answer_question_pipeline
from app.generation.schema import AskRequest, AskResponse

router = APIRouter(prefix="/ask", tags=["RAG Query"])


@router.post("", response_model=AskResponse, status_code=status.HTTP_200_OK)
async def ask_question(
    body: AskRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Asks a question about one or more documents.
    Enforces session isolation: users can only query their own session documents
    or public demo documents.
    Executes the 3-Gate anti-hallucination verification pipeline.
    """
    session_id = get_or_create_session_id(request, response)

    # Verify that all requested document_ids exist and are accessible to this session
    query = select(Document.id).where(
        Document.id.in_(body.document_ids),
        or_(
            Document.session_id == session_id,
            Document.is_demo == True,  # noqa: E712
        ),
    )
    res = await db.execute(query)
    authorized_ids = res.scalars().all()

    if not authorized_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum dos documentos selecionados foi encontrado ou está acessível.",
        )

    # Run RAG pipeline
    result = await answer_question_pipeline(
        db=db,
        session_id=session_id,
        doc_ids=authorized_ids,
        question=body.question,
    )

    return result
