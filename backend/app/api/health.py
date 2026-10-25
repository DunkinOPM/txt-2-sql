from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import get_db, get_readonly_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check(
    db: Session = Depends(get_db),
    readonly_db: Session = Depends(get_readonly_db)
):
    """
    Health check endpoint that verifies database connectivity for both
    admin and read-only roles.
    """
    admin_db_status = "healthy"
    readonly_db_status = "healthy"

    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        admin_db_status = f"unhealthy: {str(e)}"

    try:
        readonly_db.execute(text("SELECT 1"))
    except Exception as e:
        readonly_db_status = f"unhealthy: {str(e)}"

    is_healthy = admin_db_status == "healthy" and readonly_db_status == "healthy"

    response_payload = {
        "status": "healthy" if is_healthy else "degraded",
        "database": admin_db_status,
        "readonly_database": readonly_db_status,
        "version": "0.1.0",
        "environment": "development"
    }

    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response_payload
        )

    return response_payload

