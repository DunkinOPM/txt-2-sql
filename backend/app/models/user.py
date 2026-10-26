import uuid
from sqlalchemy import Column, String, Boolean, DateTime, text, Index
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class AppUser(Base):
    """
    Persistent application user model for authentication and ownership isolation.
    Stored strictly in schema 'app'. Revoked from 'readonly_user'.
    """
    __tablename__ = "app_users"
    __table_args__ = (
        Index("idx_app_users_email_lower", text("lower(email)"), unique=True),
        Index("idx_app_users_username_lower", text("lower(username)"), unique=True),
        {"schema": "app"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
