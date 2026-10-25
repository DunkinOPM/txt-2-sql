import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL Configuration
    postgres_db: str = "text2sql"
    postgres_user: str = "appuser"
    postgres_password: str = "local_dev_password"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    # Database URLs
    database_url: str = "postgresql+psycopg://appuser:local_dev_password@127.0.0.1:5432/text2sql"
    readonly_database_url: str = "postgresql+psycopg://readonly_user:readonly_dev_password@127.0.0.1:5432/text2sql"

    # External LLM API
    gemini_api_key: str = "placeholder_key"

    # Frontend Origin for CORS
    frontend_origin: str = "http://localhost:5173"

    # Ingestion & Upload limits
    max_upload_mb: int = 20
    max_upload_rows: int = 100000
    max_upload_columns: int = 250

    # Query Execution limits
    query_timeout_seconds: int = 10
    max_result_rows: int = 1000

    # Development Session Identity (NOT production authentication)
    default_owner_id: str = "default_user"

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

