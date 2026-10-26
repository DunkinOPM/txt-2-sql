from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.core.rate_limiter import rate_limit_auth
from app.api.deps import get_current_user
from app.models.user import AppUser
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    TokenResponse,
    LogoutResponse,
)
from app.services.auth_service import register_user, authenticate_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookie(response: Response, token: str) -> None:
    """
    Sets a secure, HttpOnly session cookie for same-origin or reverse-proxy deployments.
    """
    is_prod = settings.environment.lower() == "production"
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth)],
)
def register(
    payload: UserRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Registers a new user account. Returns a signed JWT access token and user metadata.
    Plaintext passwords are never logged or stored.
    """
    user, token = register_user(
        db=db,
        email=payload.email,
        username=payload.username,
        password=payload.password,
    )
    _set_auth_cookie(response, token)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_auth)],
)
def login(
    payload: UserLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Authenticates registered user credentials. Returns signed JWT access token.
    Mitigates user enumeration and timing attacks.
    """
    user, token = authenticate_user(
        db=db,
        username_or_email=payload.username_or_email,
        password=payload.password,
    )
    _set_auth_cookie(response, token)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def get_me(
    current_user: AppUser = Depends(get_current_user),
):
    """
    Returns verified profile data for the authenticated user session.
    """
    return UserResponse.model_validate(current_user)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
)
def logout(
    response: Response,
):
    """
    Invalidates client session by clearing HttpOnly authentication cookie.
    """
    response.delete_cookie(key="access_token", path="/")
    return LogoutResponse(message="Successfully logged out.")
