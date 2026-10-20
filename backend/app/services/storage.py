import asyncio
import os
from pathlib import Path
from typing import Optional
import aiofiles
import structlog

from app.config import settings

logger = structlog.get_logger()


def ensure_storage_dir() -> Path:
    storage_path = Path(settings.STORAGE_DIR)
    if not storage_path.is_absolute() and not storage_path.exists():
        backend_root = Path(__file__).resolve().parent.parent.parent
        if (backend_root / "storage").exists():
            storage_path = backend_root / "storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


def is_r2_configured() -> bool:
    """Checks if Cloudflare R2 credentials and bucket are present."""
    return bool(
        settings.R2_ACCOUNT_ID
        and settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_BUCKET_NAME
    )


def get_r2_client():
    """Returns an S3 client configured for Cloudflare R2."""
    if not is_r2_configured():
        return None
    import boto3
    from botocore.config import Config

    endpoint_url = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


async def save_file_locally(document_id: str, content: bytes) -> str:
    """Saves PDF file content to local storage directory."""
    storage_path = ensure_storage_dir()
    file_path = storage_path / f"{document_id}.pdf"

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    return str(file_path)


async def save_file(document_id: str, content: bytes) -> str:
    """
    Saves document to storage:
    Always persists a local copy in STORAGE_DIR for instant worker extraction.
    If Cloudflare R2 is configured, uploads the object to the private R2 bucket.
    Returns the storage key identifier.
    """
    local_path = await save_file_locally(document_id, content)

    if is_r2_configured():
        r2_key = f"documents/{document_id}.pdf"
        s3 = get_r2_client()
        if s3:
            try:
                await asyncio.to_thread(
                    s3.put_object,
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=r2_key,
                    Body=content,
                    ContentType="application/pdf",
                )
                logger.info("uploaded_to_r2", key=r2_key, bucket=settings.R2_BUCKET_NAME)
                return r2_key
            except Exception as exc:
                logger.error("r2_upload_failed", key=r2_key, error=str(exc))

    return local_path


def generate_presigned_url(storage_key: str, expires_in: int = 600) -> Optional[str]:
    """
    Generates a Cloudflare R2 presigned GET URL valid for `expires_in` seconds (default 10 min).
    Returns None if R2 is not configured or generation fails.
    """
    if not is_r2_configured():
        return None

    s3 = get_r2_client()
    if not s3:
        return None

    # Normalize key to documents/{filename}
    key = storage_key
    if not key.startswith("documents/"):
        key = f"documents/{Path(storage_key).name}"

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception as exc:
        logger.error("failed_generating_r2_presigned_url", key=key, error=str(exc))
        return None


def get_local_file_path(storage_key: str) -> Path:
    """
    Returns Path object for a given storage_key.
    First checks literal path, then looks in STORAGE_DIR and backend storage.
    """
    path = Path(storage_key)
    if path.is_file():
        return path
    candidate = Path(settings.STORAGE_DIR) / path.name
    if candidate.is_file():
        return candidate
    backend_root = Path(__file__).resolve().parent.parent.parent
    candidate_app = backend_root / "storage" / path.name
    if candidate_app.is_file():
        return candidate_app
    return candidate


async def delete_local_file(storage_key: str) -> bool:
    """Deletes local file if it exists."""
    path = get_local_file_path(storage_key)
    if path.exists():
        path.unlink()
        return True
    return False


async def delete_storage_file(storage_key: str) -> bool:
    """
    Deletes file from Cloudflare R2 (if configured) and from local storage.
    """
    deleted_r2 = False
    if is_r2_configured():
        s3 = get_r2_client()
        if s3:
            key = storage_key
            if not key.startswith("documents/"):
                key = f"documents/{Path(storage_key).name}"
            try:
                await asyncio.to_thread(
                    s3.delete_object,
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=key,
                )
                deleted_r2 = True
            except Exception as exc:
                logger.error("failed_deleting_r2_object", key=key, error=str(exc))

    deleted_local = await delete_local_file(storage_key)
    return deleted_r2 or deleted_local
