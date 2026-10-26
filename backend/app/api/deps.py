from fastapi import Header
from app.core.config import settings


def get_current_owner_id(x_user_id: str | None = Header(default=None)) -> str:
    """
    Extracts the user identity for dataset isolation.
    Uses X-User-ID header if provided, otherwise defaults to 'default_user'.

    NOTE: This is strictly for local development and testing, NOT production authentication.
    """
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()
    return settings.default_owner_id

