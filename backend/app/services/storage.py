import os
import aiofiles
from pathlib import Path
from app.config import settings


def ensure_storage_dir() -> Path:
    storage_path = Path(settings.STORAGE_DIR)
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


async def save_file_locally(document_id: str, content: bytes) -> str:
    """Saves PDF file content to local storage directory."""
    storage_path = ensure_storage_dir()
    file_path = storage_path / f"{document_id}.pdf"
    
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
        
    return str(file_path)


def get_local_file_path(storage_key: str) -> Path:
    """Returns Path object for a given storage_key."""
    return Path(storage_key)


async def delete_local_file(storage_key: str) -> bool:
    """Deletes local file if it exists."""
    path = Path(storage_key)
    if path.exists():
        path.unlink()
        return True
    return False
