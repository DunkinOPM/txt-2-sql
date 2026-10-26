import uuid
from typing import Optional
from fastapi import Header, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import AppUser

bearer_scheme = HTTPBearer(auto_error=False)


def get_token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[str]:
    """
    Extracts access token from Authorization header or fallback HttpOnly cookie.
    """
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials:
        return credentials.credentials.strip()

    # Check cookie fallback (for same-origin or reverse proxy setups)
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token.strip()

    return None


def get_current_user_optional(
    token: Optional[str] = Depends(get_token_from_request),
    db: Session = Depends(get_db),
) -> Optional[AppUser]:
    """
    Decodes token and returns authenticated AppUser if valid token is supplied.
    Returns None if no token is present.
    Raises HTTPException(401) if token is malformed, invalid, or expired.
    """
    if not token:
        return None

    payload = decode_access_token(token)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_TOKEN", "message": "Token subject is missing."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_TOKEN", "message": "Invalid token subject UUID format."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(AppUser).filter(AppUser.id == user_uuid).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "USER_NOT_FOUND", "message": "Authenticated user account not found."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "ACCOUNT_INACTIVE", "message": "User account is deactivated."},
        )

    return user


def get_current_user(
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
) -> AppUser:
    """
    Strict dependency requiring a verified authenticated user.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "UNAUTHORIZED", "message": "Authentication required. Please log in."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def get_current_owner_id(
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
    x_user_id: Optional[str] = Header(default=None),
) -> str:
    """
    Extracts the user identity for dataset isolation.
    - If authenticated via valid session/token, returns str(current_user.id).
      NOTE: Caller-supplied X-User-ID is strictly ignored and cannot impersonate.
    - If unauthenticated and settings.enable_mock_auth is True (gated dev/test mode only),
      allows X-User-ID or default_owner_id.
    - If unauthenticated and settings.enable_mock_auth is False (production default),
      rejects the request with 401 UNAUTHORIZED.
    """
    if current_user is not None:
        return str(current_user.id)

    # Mock auth is strictly gated
    if settings.enable_mock_auth:
        if x_user_id and x_user_id.strip():
            return x_user_id.strip()
        return settings.default_owner_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error_code": "UNAUTHORIZED", "message": "Authentication required. Please provide a valid Bearer token."},
        headers={"WWW-Authenticate": "Bearer"},
    )
