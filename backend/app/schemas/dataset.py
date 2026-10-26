import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class DatasetColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    ordinal_position: int
    original_name: str
    internal_name: str
    inferred_type: str
    nullable: bool
    sample_values: Optional[list[Any]] = None
    created_at: datetime


class DatasetSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: str
    display_name: str
    original_filename: str
    file_format: str
    status: str
    row_count: int
    column_count: int
    created_at: datetime
    updated_at: datetime
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class DatasetSchemaResponse(BaseModel):
    dataset_id: uuid.UUID
    display_name: str
    table_name: str
    row_count: int
    column_count: int
    columns: list[DatasetColumnResponse]


class DatasetPreviewResponse(BaseModel):
    dataset_id: uuid.UUID
    display_name: str
    columns: list[str]
    internal_columns: list[str]
    column_types: dict[str, str]
    rows: list[dict[str, Any]]
    total_preview_rows: int
    total_dataset_rows: int


class DatasetDeleteResponse(BaseModel):
    dataset_id: uuid.UUID
    display_name: str
    message: str
    deleted: bool = True

