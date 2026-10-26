import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserRegisterRequest(BaseModel):
    email: str = Field(..., description="Valid email address")
    username: str = Field(..., min_length=3, max_length=50, description="Alphanumeric username")
    password: str = Field(..., min_length=8, max_length=128, description="Password with minimum 8 characters")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address format.")
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, underscores, and hyphens.")
        return v


class UserLoginRequest(BaseModel):
    username_or_email: str = Field(..., min_length=1, description="Registered email or username")
    password: str = Field(..., min_length=1, description="Account password")

    @field_validator("username_or_email")
    @classmethod
    def clean_identifier(cls, v: str) -> str:
        return v.strip()


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class LogoutResponse(BaseModel):
    message: str
