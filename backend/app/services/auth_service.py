import uuid
import logging
from typing import Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.models.user import AppUser
from app.core.security import hash_password, verify_password, create_access_token
from app.core.config import settings

logger = logging.getLogger(__name__)

# Dummy hash for timing attack mitigation
_DUMMY_BCRYPT_HASH = "$2b$12$e88yZ56q6m3hU8FwY3i6I.gL0b2W2gWk7yJvU9BfQ4G7n.G6mQ1yC"


def register_user(
    db: Session,
    email: str,
    username: str,
    password: str
) -> Tuple[AppUser, str]:
    """
    Registers a new user after verifying unique email and username.
    Stores password hashed with bcrypt (never plaintext).
    """
    clean_email = email.strip().lower()
    clean_username = username.strip()

    # Check email collision
    existing_email = db.query(AppUser).filter(
        func.lower(AppUser.email) == clean_email
    ).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "EMAIL_ALREADY_REGISTERED",
                "message": "An account with this email address already exists."
            }
        )

    # Check username collision
    existing_user = db.query(AppUser).filter(
        func.lower(AppUser.username) == clean_username.lower()
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "USERNAME_ALREADY_TAKEN",
                "message": "This username is already taken. Please choose another."
            }
        )

    hashed_pw = hash_password(password)

    user = AppUser(
        id=uuid.uuid4(),
        email=clean_email,
        username=clean_username,
        hashed_password=hashed_pw,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        subject=str(user.id),
        extra_claims={"email": user.email, "username": user.username}
    )
    return user, token


def authenticate_user(
    db: Session,
    username_or_email: str,
    password: str
) -> Tuple[AppUser, str]:
    """
    Authenticates user credentials using bcrypt.
    Emits constant-time verification against timing attacks if user is not found.
    """
    clean_id = username_or_email.strip().lower()

    user = db.query(AppUser).filter(
        (func.lower(AppUser.email) == clean_id) | (func.lower(AppUser.username) == clean_id)
    ).first()

    if not user:
        # Dummy verification to prevent timing discrepancy
        verify_password(password, _DUMMY_BCRYPT_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_CREDENTIALS",
                "message": "Invalid email/username or password."
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_CREDENTIALS",
                "message": "Invalid email/username or password."
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "ACCOUNT_INACTIVE",
                "message": "This account is inactive. Please contact support."
            }
        )

    token = create_access_token(
        subject=str(user.id),
        extra_claims={"email": user.email, "username": user.username}
    )
    return user, token


def get_user_by_id(db: Session, user_id: str | uuid.UUID) -> AppUser | None:
    try:
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
    except ValueError:
        return None
    return db.query(AppUser).filter(AppUser.id == uid).first()
