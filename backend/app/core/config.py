import os
import logging
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Environment
    environment: str = "development"

    # PostgreSQL Configuration
    postgres_db: str = "text2sql"
    postgres_user: str = "appuser"
    postgres_password: str = "local_dev_password"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    # Database URLs
    database_url: str = "postgresql+psycopg://appuser:local_dev_password@127.0.0.1:5432/text2sql"
    readonly_database_url: str = "postgresql+psycopg://readonly_user:readonly_dev_password@127.0.0.1:5432/text2sql"

    # Authentication & JWT Configuration
    jwt_secret_key: str = "dev_insecure_jwt_secret_key_change_in_production_min_32_chars"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 24 hours

    # Gated Mock Authentication (Disabled by default; only allowed when explicitly enabled)
    enable_mock_auth: bool = False
    default_owner_id: str = "default_user"

    # Rate Limiting (Requests per minute)
    rate_limit_auth_per_minute: int = 15
    rate_limit_upload_per_minute: int = 20

    # External LLM API
    gemini_api_key: str = "placeholder_key"

    # Frontend Origin / CORS
    frontend_origin: str = "http://localhost:5173"
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"

    # Ingestion & Upload limits
    max_upload_mb: int = 20
    max_upload_rows: int = 100000
    max_upload_columns: int = 250

    # Query Execution limits
    query_timeout_seconds: int = 10
    max_result_rows: int = 1000

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment.lower() == "production":
            if (
                self.jwt_secret_key == "dev_insecure_jwt_secret_key_change_in_production_min_32_chars"
                or len(self.jwt_secret_key) < 32
            ):
                raise ValueError(
                    "FATAL: In production, JWT_SECRET_KEY must be set to a secure, randomly generated secret of at least 32 characters."
                )
            if self.enable_mock_auth:
                raise ValueError("FATAL: enable_mock_auth cannot be enabled in production environment.")
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        origins = set()
        if self.frontend_origin:
            origins.add(self.frontend_origin.rstrip("/"))
        for o in self.cors_allowed_origins.split(","):
            cleaned = o.strip().rstrip("/")
            if cleaned:
                origins.add(cleaned)
        return list(origins)

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
