import uuid
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limiter import rate_limit_upload
from app.api.deps import get_current_owner_id
from app.schemas.query import SuggestedQuestionsResponse
from app.services.query_service import get_suggested_questions
from app.schemas.dataset import (
    DatasetSummaryResponse,
    DatasetSchemaResponse,
    DatasetPreviewResponse,
    DatasetDeleteResponse,
)
from app.services.upload_service import validate_and_parse_upload
from app.services.dataset_service import (
    create_dataset_and_import,
    list_authorized_datasets,
    get_authorized_dataset,
    get_dataset_schema_details,
    get_dataset_preview_rows,
    delete_authorized_dataset,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.post(
    "",
    response_model=DatasetSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_upload)],
)
async def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Upload and import a CSV or XLSX dataset.
    Validates file boundaries, normalizes column headers, infers data types,
    creates a physical table in schema 'uploaded_data', and registers metadata.
    Enforces upload rate limits per client.
    """
    df, raw_headers, clean_filename, file_format = await validate_and_parse_upload(file)

    dataset = create_dataset_and_import(
        db=db,
        owner_id=owner_id,
        df=df,
        raw_headers=raw_headers,
        original_filename=clean_filename,
        file_format=file_format,
    )

    return DatasetSummaryResponse.model_validate(dataset)


@router.get("", response_model=List[DatasetSummaryResponse])
def list_datasets(
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    List all datasets owned by the requesting user.
    """
    datasets = list_authorized_datasets(db, owner_id)
    return [DatasetSummaryResponse.model_validate(d) for d in datasets]


@router.get("/{dataset_id}", response_model=DatasetSummaryResponse)
def get_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Retrieve dataset summary metadata by ID for the authorized owner.
    """
    dataset = get_authorized_dataset(db, dataset_id, owner_id)
    return DatasetSummaryResponse.model_validate(dataset)


@router.get("/{dataset_id}/schema", response_model=DatasetSchemaResponse)
def get_dataset_schema(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Retrieve the column schema, inferred data types, and safe sample values.
    """
    return get_dataset_schema_details(db, dataset_id, owner_id)


@router.get("/{dataset_id}/preview", response_model=DatasetPreviewResponse)
def get_dataset_preview(
    dataset_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Retrieve bounded sample rows from the physical dataset table.
    """
    return get_dataset_preview_rows(db, dataset_id, owner_id, limit=limit)


@router.delete("/{dataset_id}", response_model=DatasetDeleteResponse)
def delete_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Delete an authorized dataset, dropping its dynamic table and cascading metadata.
    """
    return delete_authorized_dataset(db, dataset_id, owner_id)


@router.get("/{dataset_id}/suggested-questions", response_model=SuggestedQuestionsResponse)
def get_dataset_suggested_questions(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner_id),
):
    """
    Retrieve 3-4 schema-grounded suggested natural language questions for an authorized dataset.
    """
    return get_suggested_questions(db=db, owner_id=owner_id, dataset_id=dataset_id)
