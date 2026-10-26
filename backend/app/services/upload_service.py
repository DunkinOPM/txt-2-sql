import io
import os
import re
import csv
from typing import Tuple, List, Any
from fastapi import UploadFile, HTTPException, status
import pandas as pd
import openpyxl
from app.core.config import settings


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes user-supplied filename to prevent path traversal or unsafe characters.
    """
    base = os.path.basename(filename)
    clean = re.sub(r"[^\w\s\.-]", "_", base)
    clean = clean.strip()
    return clean or "uploaded_dataset"


def detect_csv_delimiter(sample_text: str) -> str:
    """
    Detects delimiter for CSV files, supporting ',', ';', and '\t'.
    Falls back to ',' safely if detection fails or is ambiguous.
    """
    sample = sample_text[:8192]
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=[",", ";", "\t"])
        if dialect.delimiter in [",", ";", "\t"]:
            return dialect.delimiter
    except Exception:
        pass

    # Heuristic fallback based on first non-empty lines
    lines = [line for line in sample.splitlines() if line.strip()][:5]
    if lines:
        candidates = [",", ";", "\t"]
        counts = {c: lines[0].count(c) for c in candidates}
        best = max(candidates, key=lambda c: counts[c])
        if counts[best] > 0:
            return best

    return ","


async def validate_and_parse_upload(
    file: UploadFile
) -> Tuple[pd.DataFrame, List[str], str, str]:
    """
    Reads, validates, and parses an uploaded CSV or XLSX file with streaming size
    enforcement, format checking, and tabular boundary validation.

    Returns:
        (dataframe, raw_headers, sanitized_filename, file_format)
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "EMPTY_FILENAME", "message": "No file uploaded or filename is empty."}
        )

    clean_filename = sanitize_filename(file.filename)
    ext = os.path.splitext(clean_filename)[1].lower()

    if ext not in [".csv", ".xlsx"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "UNSUPPORTED_FORMAT",
                "message": f"Unsupported file format '{ext}'. Only CSV and XLSX files are accepted."
            }
        )

    file_format = "csv" if ext == ".csv" else "xlsx"
    max_bytes = settings.max_upload_mb * 1024 * 1024

    # Stream file to check size limit without loading unbounded memory
    chunks = []
    total_bytes = 0

    while True:
        chunk = await file.read(1024 * 64)  # 64 KB chunks
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "FILE_TOO_LARGE",
                    "message": f"File size exceeds limit of {settings.max_upload_mb} MB."
                }
            )
        chunks.append(chunk)

    if total_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "EMPTY_FILE", "message": "Uploaded file is empty (0 bytes)."}
        )

    file_bytes = b"".join(chunks)
    raw_headers: List[str] = []
    df: pd.DataFrame

    # Parse into pandas DataFrame & extract pristine raw headers
    try:
        if file_format == "csv":
            decoded = False
            for encoding in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
                try:
                    text_content = file_bytes.decode(encoding)
                    delimiter = detect_csv_delimiter(text_content)
                    # Extract raw headers via csv.reader to avoid pandas auto-renaming duplicate headers
                    reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
                    first_row = next(reader, None)
                    if first_row is None:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error_code": "EMPTY_FILE", "message": "CSV file contains no rows."}
                        )
                    raw_headers = [str(col).strip() for col in first_row]

                    # Read dataframe with header=None and skiprows=1 to keep duplicate headers intact
                    df = pd.read_csv(
                        io.BytesIO(file_bytes),
                        encoding=encoding,
                        sep=delimiter,
                        skiprows=1,
                        header=None,
                        keep_default_na=False,
                        na_values=[""]
                    )
                    decoded = True
                    break
                except pd.errors.EmptyDataError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error_code": "NO_DATA_ROWS", "message": "Dataset contains 0 data rows."}
                    )
                except UnicodeDecodeError:
                    continue
                except HTTPException:
                    raise
                except StopIteration:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error_code": "EMPTY_FILE", "message": "CSV file contains no rows."}
                    )
                except Exception:
                    continue

            if not decoded or df is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": "MALFORMED_CSV",
                        "message": "Could not parse CSV file. Ensure it is a valid delimiter-separated text file."
                    }
                )
        else:
            # Excel XLSX
            try:
                wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
                sheet = wb.active
                if sheet is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error_code": "EMPTY_FILE", "message": "Excel workbook contains no sheets."}
                    )

                rows_iter = sheet.iter_rows(values_only=True)
                first_row = next(rows_iter, None)
                if first_row is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error_code": "EMPTY_FILE", "message": "Excel sheet contains no rows."}
                    )
                raw_headers = [str(col).strip() if col is not None else "" for col in first_row]

                df = pd.read_excel(
                    io.BytesIO(file_bytes),
                    skiprows=1,
                    header=None,
                    engine="openpyxl",
                    keep_default_na=False,
                    na_values=[""]
                )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": "MALFORMED_XLSX",
                        "message": f"Could not parse Excel spreadsheet: {str(e)}"
                    }
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "PARSE_ERROR",
                "message": f"Failed to parse file: {str(e)}"
            }
        )

    # 1. Check columns
    col_count = len(raw_headers)
    if col_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "NO_COLUMNS", "message": "Dataset contains 0 columns."}
        )

    if col_count > settings.max_upload_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "COLUMN_LIMIT_EXCEEDED",
                "message": f"Dataset contains {col_count} columns, exceeding limit of {settings.max_upload_columns}."
            }
        )

    # 2. Check if headers are completely blank
    if all(h == "" for h in raw_headers):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_HEADERS",
                "message": "The file header row contains no decipherable column names."
            }
        )

    # 3. Check data rows
    if df.shape[0] == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "NO_DATA_ROWS", "message": "Dataset contains 0 data rows."}
        )

    if df.shape[0] > settings.max_upload_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "ROW_LIMIT_EXCEEDED",
                "message": f"Dataset contains {df.shape[0]} rows, exceeding limit of {settings.max_upload_rows}."
            }
        )

    # Ensure df has exactly as many columns as raw_headers (pad or truncate)
    if df.shape[1] < col_count:
        for idx in range(df.shape[1], col_count):
            df[idx] = None
    elif df.shape[1] > col_count:
        df = df.iloc[:, :col_count]

    df.columns = list(range(col_count))
    return df, raw_headers, clean_filename, file_format
