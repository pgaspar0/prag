import uuid
from typing import Optional
from fastapi import Request, Response


SESSION_COOKIE_NAME = "session_id"


def get_or_create_session_id(request: Request, response: Response) -> str:
    """
    Retrieves the session_id from request cookies, or generates a new UUID.
    When a new session is created, sets the cookie on the response with:
    HttpOnly, SameSite=None, Secure (required when frontend is hosted separately on Vercel).
    In local development without HTTPS, SameSite='lax' is used if not secure.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        session_id = str(uuid.uuid4())
        # Set cookie on outgoing response
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",  # 'lax' for local testing, 'none' with secure=True in production cross-domain
            secure=False,
            max_age=60 * 60 * 24 * 7,  # 7 days
        )
    return session_id
