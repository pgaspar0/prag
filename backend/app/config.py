from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Environment
    ENV: str = Field(default="development", description="Environment mode: development or production")

    # Database
    # Note: Local docker runs on host port 5433 to prevent collision with other postgres instances
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgrespassword@localhost:5433/prag_db",
        description="Async PostgreSQL connection string with asyncpg"
    )
    DATABASE_URL_SYNC: str = Field(
        default="postgresql://postgres:postgrespassword@localhost:5433/prag_db",
        description="Sync PostgreSQL connection string for Alembic migrations"
    )

    # LLM & Embedding Models (Strictly configurable, NEVER hardcoded in business logic)
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API key")
    GEN_MODEL: str = Field(default="gemini-2.5-flash", description="Generation model name")
    EMBED_MODEL: str = Field(default="gemini-embedding-001", description="Embedding model name")
    EMBED_DIM: int = Field(default=768, description="Embedding vector dimension (768 for HNSW compatibility)")

    # RAG Retrieval Thresholds
    SIM_THRESHOLD: float = Field(default=0.55, description="Initial cosine similarity cutoff threshold")

    # Storage
    STORAGE_DIR: str = Field(default="backend/storage", description="Local storage directory for PDFs in development")
    R2_ACCOUNT_ID: str = Field(default="", description="Cloudflare R2 Account ID")
    R2_ACCESS_KEY_ID: str = Field(default="", description="Cloudflare R2 Access Key ID")
    R2_SECRET_ACCESS_KEY: str = Field(default="", description="Cloudflare R2 Secret Access Key")
    R2_BUCKET_NAME: str = Field(default="", description="Cloudflare R2 Bucket Name")

    # Security & Limits
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="CORS allowed origins"
    )
    MAX_UPLOAD_SIZE_MB: int = Field(default=10, description="Max PDF upload file size in megabytes")
    MAX_PAGES: int = Field(default=30, description="Max PDF page count allowed for extraction")
    DAILY_LLM_CAP: int = Field(default=400, description="Max allowed LLM requests per day across demo")
    SENTRY_DSN: str = Field(default="", description="Optional Sentry DSN for error monitoring")


settings = Settings()
