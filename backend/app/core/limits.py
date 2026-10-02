import io
import fitz  # PyMuPDF
from fastapi import HTTPException, UploadFile, status

from app.config import settings


class PDFValidationError(HTTPException):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(status_code=status_code, detail=detail)


async def validate_pdf_upload(file: UploadFile) -> tuple[bytes, int]:
    """
    Validates a PDF upload file stream:
    1. File size limit (<= MAX_UPLOAD_SIZE_MB)
    2. Magic bytes (%PDF-)
    3. Not encrypted / password protected
    4. Page count limit (<= MAX_PAGES)
    5. Text density: checks if document is not purely scanned (< 50 chars/page on average)

    Returns:
        tuple[bytes, int]: (file_bytes, page_count)
    """
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # Read content
    content = await file.read()
    if len(content) == 0:
        raise PDFValidationError("Ficheiro vazio.", status_code=status.HTTP_400_BAD_REQUEST)

    if len(content) > max_bytes:
        raise PDFValidationError(
            f"Ficheiro excede o tamanho máximo de {settings.MAX_UPLOAD_SIZE_MB} MB.",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    # 1. Check Magic Bytes (%PDF-)
    if not content.startswith(b"%PDF-"):
        raise PDFValidationError(
            "Formato inválido: o ficheiro não é um PDF válido (cabeçalho %PDF- ausente)."
        )

    # 2. Inspect with PyMuPDF
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise PDFValidationError(f"Não foi possível abrir o PDF: {str(exc)}")

    try:
        # Check encryption
        if doc.is_encrypted:
            raise PDFValidationError("PDFs encriptados ou protegidos por palavra-passe não são suportados.")

        page_count = len(doc)
        if page_count == 0:
            raise PDFValidationError("O PDF não contém páginas.")

        if page_count > settings.MAX_PAGES:
            raise PDFValidationError(
                f"O PDF tem {page_count} páginas, excedendo o limite máximo de {settings.MAX_PAGES} páginas."
            )

        # Check for scanned documents (average characters per page)
        total_chars = 0
        for page in doc:
            text = page.get_text("text").strip()
            total_chars += len(text)

        avg_chars = total_chars / page_count
        if avg_chars < 50:
            raise PDFValidationError(
                "PDF digitalizado detetado (média < 50 caracteres/página). OCR está fora do âmbito do projeto."
            )

        return content, page_count
    finally:
        doc.close()
