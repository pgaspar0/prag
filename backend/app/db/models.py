import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    chunks: Mapped[List["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )
    ingestion_job: Mapped[Optional["IngestionJob"]] = relationship(
        "IngestionJob", back_populates="document", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("session_id", "sha256", name="uq_documents_session_sha256"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    bboxes: Mapped[Any] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[Optional[Any]] = mapped_column(Vector(768), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)

    tsv: Mapped[Optional[Any]] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('portuguese', text)", persisted=True),
        nullable=True,
    )

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_doc_chunk_index"),
        Index("chunks_embedding_hnsw", "embedding", postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("chunks_tsv_gin", "tsv", postgresql_using="gin"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    document: Mapped["Document"] = relationship("Document", back_populates="ingestion_job")


class QueryLog(Base):
    __tablename__ = "query_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved: Mapped[Any] = mapped_column(JSONB, nullable=False)
    answer: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    refusal_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[Any] = mapped_column(JSONB, nullable=False)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )


class EvalQuestion(Base):
    __tablename__ = "eval_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    split: Mapped[str] = mapped_column(String(20), nullable=False)  # dev | test
    qtype: Mapped[str] = mapped_column(String(50), nullable=False)  # answerable | unanswerable | injection
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_pages: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    must_contain: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    split: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[Any] = mapped_column(JSONB, nullable=False)
    summary: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_questions.id"),
        primary_key=True,
    )
    retrieved_pages: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    cited_pages: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    refused: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    citation_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    retrieval_hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
