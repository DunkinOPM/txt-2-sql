import os
import uuid
import math
import datetime
from decimal import Decimal
from typing import Any, List, Optional
import numpy as np
import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.metadata import AppDataset, AppDatasetTable, AppDatasetColumn
from app.schemas.dataset import (
    DatasetSchemaResponse,
    DatasetColumnResponse,
    DatasetPreviewResponse,
    DatasetDeleteResponse,
)
from app.services.type_inference import normalize_headers, infer_column_metadata


def generate_safe_table_name(dataset_id: uuid.UUID) -> str:
    """
    Generates a backend-controlled, collision-free PostgreSQL table identifier.
    Guaranteed to be alphanumeric + underscore, max 40 chars.
    """
    return f"dataset_{dataset_id.hex}"


def create_dataset_and_import(
    db: Session,
    owner_id: str,
    df: pd.DataFrame,
    raw_headers: List[str],
    original_filename: str,
    file_format: str,
) -> AppDataset:
    """
    Transactionally creates metadata, generates a dynamic physical table in uploaded_data,
    inserts records, and registers column metadata.
    Cleans up any created tables on failure.
    """
    dataset_id = uuid.uuid4()
    physical_table_name = generate_safe_table_name(dataset_id)

    # 1. Generate display name from filename
    base_name = os.path.splitext(original_filename)[0]
    display_name = base_name.replace("_", " ").strip().title() or "Untitled Dataset"

    # 2. Normalize headers and resolve collisions
    header_mappings = normalize_headers(raw_headers)

    # 3. Infer column types and extract safe sample values
    column_definitions: list[dict[str, Any]] = []
    ddl_column_clauses: list[str] = []

    for idx, (orig_name, int_name) in enumerate(header_mappings):
        series = df[idx]
        inferred_type, nullable, sample_values = infer_column_metadata(
            int_name, series
        )
        column_definitions.append({
            "ordinal_position": idx + 1,
            "original_name": orig_name,
            "internal_name": int_name,
            "inferred_type": inferred_type,
            "nullable": nullable,
            "sample_values": sample_values,
        })
        ddl_column_clauses.append(f'"{int_name}" {inferred_type}')

    # 4. Prepare physical table DDL
    ddl_sql = f"""
    CREATE TABLE uploaded_data."{physical_table_name}" (
        _row_id BIGSERIAL PRIMARY KEY,
        {", ".join(ddl_column_clauses)}
    );
    """

    table_created = False

    try:
        # Create physical table as appuser
        db.execute(text(ddl_sql))
        table_created = True

        # Prepare records for insertion efficiently using itertuples
        records: list[dict[str, Any]] = []
        col_configs = [
            (idx, cd["internal_name"], cd["inferred_type"])
            for idx, cd in enumerate(column_definitions)
        ]

        for row in df.itertuples(index=False, name=None):
            row_dict = {}
            for idx, col, itype in col_configs:
                val = row[idx]

                # Handle nulls & whitespace
                if val is None or pd.isna(val) or val == "" or (isinstance(val, float) and math.isnan(val)):
                    row_dict[col] = None
                    continue

                if isinstance(val, str) and not val.strip():
                    row_dict[col] = None
                    continue

                if itype == "BOOLEAN":
                    if isinstance(val, (bool, np.bool_)):
                        row_dict[col] = bool(val)
                    else:
                        s = str(val).strip().lower()
                        row_dict[col] = s in ("true", "t", "yes", "1")
                elif itype == "BIGINT":
                    try:
                        if isinstance(val, (int, np.integer)):
                            row_dict[col] = int(val)
                        elif isinstance(val, (float, np.floating)):
                            row_dict[col] = int(val)
                        else:
                            s = str(val).strip()
                            if "." in s:
                                row_dict[col] = int(s.split(".")[0])
                            else:
                                row_dict[col] = int(s)
                    except Exception:
                        row_dict[col] = None
                elif itype == "NUMERIC":
                    try:
                        if isinstance(val, (int, float, Decimal)):
                            row_dict[col] = Decimal(str(val))
                        else:
                            clean_val = str(val).replace(",", "").strip()
                            row_dict[col] = Decimal(clean_val)
                    except Exception:
                        row_dict[col] = None
                elif itype == "TIMESTAMPTZ":
                    try:
                        if isinstance(val, datetime.datetime):
                            if val.tzinfo is None:
                                row_dict[col] = val.replace(tzinfo=datetime.timezone.utc)
                            else:
                                row_dict[col] = val.astimezone(datetime.timezone.utc)
                        elif isinstance(val, datetime.date):
                            row_dict[col] = datetime.datetime.combine(
                                val, datetime.time.min
                            ).replace(tzinfo=datetime.timezone.utc)
                        else:
                            ts = pd.to_datetime(val)
                            if ts.tzinfo is None:
                                row_dict[col] = ts.tz_localize(datetime.timezone.utc).to_pydatetime()
                            else:
                                row_dict[col] = ts.astimezone(datetime.timezone.utc).to_pydatetime()
                    except Exception:
                        row_dict[col] = None
                else:  # TEXT
                    row_dict[col] = str(val)

            records.append(row_dict)

        # Batch insert into physical table
        if records:
            cols = [f'"{cd["internal_name"]}"' for cd in column_definitions]
            placeholders = [f':{cd["internal_name"]}' for cd in column_definitions]
            insert_sql = text(
                f'INSERT INTO uploaded_data."{physical_table_name}" ({", ".join(cols)}) '
                f'VALUES ({", ".join(placeholders)})'
            )
            batch_size = 1000
            for i in range(0, len(records), batch_size):
                batch = records[i : i + batch_size]
                db.execute(insert_sql, batch)

        # 5. Register metadata
        dataset_meta = AppDataset(
            id=dataset_id,
            owner_id=owner_id,
            display_name=display_name,
            original_filename=original_filename,
            file_format=file_format,
            status="ready",
            row_count=len(df),
            column_count=len(column_definitions),
        )
        db.add(dataset_meta)

        table_meta = AppDatasetTable(
            id=uuid.uuid4(),
            dataset_id=dataset_id,
            schema_name="uploaded_data",
            table_name=physical_table_name,
        )
        db.add(table_meta)

        for cd in column_definitions:
            col_meta = AppDatasetColumn(
                id=uuid.uuid4(),
                dataset_id=dataset_id,
                ordinal_position=cd["ordinal_position"],
                original_name=cd["original_name"],
                internal_name=cd["internal_name"],
                inferred_type=cd["inferred_type"],
                nullable=cd["nullable"],
                sample_values=cd["sample_values"],
            )
            db.add(col_meta)

        # Commit metadata and data insertions together
        db.commit()
        db.refresh(dataset_meta)
        return dataset_meta

    except Exception as e:
        db.rollback()
        # Drop physical table if it was created
        if table_created:
            try:
                cleanup_engine = db.get_bind()
                with cleanup_engine.begin() as cleanup_conn:
                    cleanup_conn.execute(
                        text(f'DROP TABLE IF EXISTS uploaded_data."{physical_table_name}" CASCADE')
                    )
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "IMPORT_FAILED",
                "message": f"Failed to import dataset: {str(e)}",
            },
        )


def list_authorized_datasets(db: Session, owner_id: str) -> List[AppDataset]:
    """Retrieves all datasets owned by the current user."""
    return (
        db.query(AppDataset)
        .filter(AppDataset.owner_id == owner_id, AppDataset.status != "deleting")
        .order_by(AppDataset.created_at.desc())
        .all()
    )


def get_authorized_dataset(db: Session, dataset_id: uuid.UUID, owner_id: str) -> AppDataset:
    """Retrieves a single dataset, strictly enforcing ownership isolation."""
    dataset = (
        db.query(AppDataset)
        .filter(AppDataset.id == dataset_id, AppDataset.owner_id == owner_id)
        .first()
    )
    if not dataset or dataset.status == "deleting":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DATASET_NOT_FOUND", "message": "Dataset not found or access denied."}
        )
    return dataset


def get_dataset_schema_details(
    db: Session, dataset_id: uuid.UUID, owner_id: str
) -> DatasetSchemaResponse:
    """Returns column metadata and data types for an authorized dataset."""
    dataset = get_authorized_dataset(db, dataset_id, owner_id)
    table_meta = (
        db.query(AppDatasetTable)
        .filter(AppDatasetTable.dataset_id == dataset_id)
        .first()
    )
    table_name = table_meta.table_name if table_meta else "unknown"

    columns = (
        db.query(AppDatasetColumn)
        .filter(AppDatasetColumn.dataset_id == dataset_id)
        .order_by(AppDatasetColumn.ordinal_position.asc())
        .all()
    )

    return DatasetSchemaResponse(
        dataset_id=dataset.id,
        display_name=dataset.display_name,
        table_name=table_name,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        columns=[DatasetColumnResponse.model_validate(c) for c in columns],
    )


def get_dataset_preview_rows(
    db: Session, dataset_id: uuid.UUID, owner_id: str, limit: int = 50
) -> DatasetPreviewResponse:
    """
    Retrieves bounded sample rows from the physical table for an authorized dataset.
    """
    dataset = get_authorized_dataset(db, dataset_id, owner_id)
    table_meta = (
        db.query(AppDatasetTable)
        .filter(AppDatasetTable.dataset_id == dataset_id)
        .first()
    )
    if not table_meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TABLE_NOT_FOUND", "message": "Physical table mapping not found."}
        )

    columns = (
        db.query(AppDatasetColumn)
        .filter(AppDatasetColumn.dataset_id == dataset_id)
        .order_by(AppDatasetColumn.ordinal_position.asc())
        .all()
    )

    # Bound the preview limit safely
    safe_limit = min(max(1, limit), 100)
    col_names = [f'"{c.internal_name}"' for c in columns]
    preview_sql = text(
        f'SELECT {", ".join(col_names)} FROM uploaded_data."{table_meta.table_name}" '
        f'ORDER BY _row_id ASC LIMIT :limit'
    )

    result = db.execute(preview_sql, {"limit": safe_limit})
    rows: list[dict[str, Any]] = []
    column_internal_names = [c.internal_name for c in columns]
    column_original_names = [c.original_name for c in columns]
    column_types = {c.internal_name: c.inferred_type for c in columns}

    for row in result.fetchall():
        row_dict = {}
        for idx, val in enumerate(row):
            int_col = column_internal_names[idx]
            if hasattr(val, "isoformat"):
                row_dict[int_col] = val.isoformat()
            elif isinstance(val, Decimal):
                if val.as_tuple().exponent == 0:
                    row_dict[int_col] = int(val)
                else:
                    row_dict[int_col] = float(val)
            else:
                row_dict[int_col] = val
        rows.append(row_dict)

    return DatasetPreviewResponse(
        dataset_id=dataset.id,
        display_name=dataset.display_name,
        columns=column_original_names,
        internal_columns=column_internal_names,
        column_types=column_types,
        rows=rows,
        total_preview_rows=len(rows),
        total_dataset_rows=dataset.row_count,
    )


def delete_authorized_dataset(
    db: Session, dataset_id: uuid.UUID, owner_id: str
) -> DatasetDeleteResponse:
    """
    Deletes an authorized dataset, dropping its dynamic table and cascading metadata.
    """
    dataset = get_authorized_dataset(db, dataset_id, owner_id)
    table_meta = (
        db.query(AppDatasetTable)
        .filter(AppDatasetTable.dataset_id == dataset_id)
        .first()
    )
    table_name = table_meta.table_name if table_meta else None
    display_name = dataset.display_name

    try:
        if table_name:
            db.execute(text(f'DROP TABLE IF EXISTS uploaded_data."{table_name}" CASCADE'))

        db.delete(dataset)
        db.commit()

        return DatasetDeleteResponse(
            dataset_id=dataset_id,
            display_name=display_name,
            message="Dataset and imported table deleted successfully.",
            deleted=True,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "DELETE_FAILED", "message": f"Failed to delete dataset: {str(e)}"}
        )

