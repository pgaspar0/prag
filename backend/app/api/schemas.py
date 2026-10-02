import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    job_id: Optional[uuid.UUID] = None
    filename: str
    status: str
    page_count: int
    is_existing: bool = False


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: str
    page_count: Optional[int] = None
    is_demo: bool
    created_at: datetime
    progress: Optional[int] = 0


class DocumentDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: str
    page_count: Optional[int] = None
    is_demo: bool
    error: Optional[str] = None
    created_at: datetime
    progress: Optional[int] = 0
