import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CitationItem(BaseModel):
    chunk_id: str
    quote: str


class ClaimItem(BaseModel):
    text: str
    citations: List[CitationItem] = Field(default_factory=list)


class LLMGenerationResponse(BaseModel):
    answerable: bool
    claims: List[ClaimItem] = Field(default_factory=list)


class CitationVerified(BaseModel):
    claim_index: int
    document_id: str
    page: int
    quote: str
    bboxes: List[Dict[str, Any]] = Field(default_factory=list)


class LatencyBreakdown(BaseModel):
    embed: int
    retrieve: int
    generate: int
    verify: int
    total: int


class AskRequest(BaseModel):
    document_ids: List[uuid.UUID] = Field(..., min_length=1)
    question: str = Field(..., min_length=2, max_length=1000)


class AskResponse(BaseModel):
    refused: bool
    refusal_reason: Optional[str] = None
    answer: str
    citations: List[CitationVerified] = Field(default_factory=list)
    latency_ms: LatencyBreakdown
