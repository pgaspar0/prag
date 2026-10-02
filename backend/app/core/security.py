import re
import uuid
from typing import Optional
import structlog
from fastapi import Request, Response

from app.config import settings

logger = structlog.get_logger()

SESSION_COOKIE_NAME = "session_id"
MAX_QUESTION_LENGTH = 1000


def is_valid_session_id(val: str) -> bool:
    """
    Verifies that a string is a safe session identifier:
    alphanumeric, hyphens, underscores, length between 8 and 64 characters.
    Prevents header injection, SQL poisoning, or directory traversal.
    """
    if not val or not (8 <= len(val) <= 64):
        return False
    return bool(re.match(r"^[a-zA-Z0-9_\-]+$", val))


def get_or_create_session_id(request: Request, response: Response) -> str:
    """
    Retrieves the session_id from request cookies, or generates a new valid UUID.
    Validates format: if malformed or tampered, a fresh UUID is issued.
    When a new session is created, sets the cookie on the response:
    - In production (ENV == 'production'): SameSite='none', Secure=True (cross-domain Vercel <-> Render).
    - In development: SameSite='lax', Secure=False.
    """
    raw_session_id = request.cookies.get(SESSION_COOKIE_NAME)

    if raw_session_id and is_valid_session_id(raw_session_id):
        session_id = raw_session_id
    else:
        session_id = str(uuid.uuid4())
        is_prod = settings.ENV == "production"

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="none" if is_prod else "lax",
            secure=is_prod,
            max_age=60 * 60 * 24 * 7,  # 7 days
        )

    return session_id


def sanitize_user_question(question: str) -> str:
    """
    Sanitizes user input question:
    1. Trims whitespace
    2. Strips ASCII control characters (keeping standard newlines)
    3. Truncates to MAX_QUESTION_LENGTH (1000 chars)
    """
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", question).strip()
    if len(cleaned) > MAX_QUESTION_LENGTH:
        cleaned = cleaned[:MAX_QUESTION_LENGTH]
    return cleaned
