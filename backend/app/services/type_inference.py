import re
import math
import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
import pandas as pd
import numpy as np

POSTGRES_RESERVED_KEYWORDS = {
    "all", "analyse", "analyze", "and", "any", "array", "as", "asc", "asymmetric",
    "authorization", "binary", "both", "case", "cast", "check", "collate", "collation",
    "column", "concurrently", "constraint", "create", "cross", "current_catalog",
    "current_date", "current_role", "current_schema", "current_time", "current_timestamp",
    "current_user", "default", "deferrable", "desc", "distinct", "do", "else", "end",
    "except", "false", "fetch", "for", "foreign", "freeze", "from", "full", "grant",
    "group", "having", "ilike", "in", "initially", "inner", "intersect", "into", "is",
    "isnull", "join", "lateral", "leading", "left", "like", "limit", "localtime",
    "localtimestamp", "natural", "not", "notnull", "null", "offset", "on", "only",
    "or", "order", "outer", "overlaps", "placing", "primary", "references", "returning",
    "right", "select", "session_user", "similar", "some", "symmetric", "table", "tablesample",
    "then", "to", "trailing", "true", "union", "unique", "user", "using", "variadic",
    "verbose", "when", "where", "window", "with"
}

POSTGRES_BIGINT_MIN = -9223372036854775808
POSTGRES_BIGINT_MAX = 9223372036854775807

SENSITIVE_TOKENS = {
    "email", "phone", "mobile", "cell", "address", "salary", "wage", "wages",
    "tax", "taxes", "password", "passwd", "secret", "token", "ssn", "pin",
    "auth", "credential", "credentials", "card", "cvv", "apikey", "cvc",
}

SENSITIVE_PATTERNS = [
    re.compile(r"\bapi[_-]?key\b", re.IGNORECASE),
    re.compile(r"\bprivate[_-]?key\b", re.IGNORECASE),
    re.compile(r"\bcredit[_-]?card\b", re.IGNORECASE),
    re.compile(r"\bdebit[_-]?card\b", re.IGNORECASE),
    re.compile(r"\bphone[_-]?(?:number|num|no)?\b", re.IGNORECASE),
    re.compile(r"\bcard[_-]?(?:number|num|no)?\b", re.IGNORECASE),
]


def normalize_headers(raw_headers: list[Any]) -> list[tuple[str, str]]:
    """
    Normalizes a list of raw column headers deterministically into safe PostgreSQL
    identifiers while preserving original display names and resolving collisions.

    Returns:
        List of tuples: (original_name, internal_name)
    """
    normalized_list: list[tuple[str, str]] = []
    existing_internal_names: set[str] = set()
    base_counts: dict[str, int] = {}

    for idx, raw_h in enumerate(raw_headers):
        # 1. Preserve original name
        orig_name = str(raw_h).strip() if raw_h is not None and not pd.isna(raw_h) else f"Column {idx + 1}"
        if not orig_name:
            orig_name = f"Column {idx + 1}"

        # 2. Lowercase and replace non-alphanumeric chars with underscore
        clean_name = orig_name.lower()
        clean_name = re.sub(r"[^a-z0-9_]+", "_", clean_name)
        clean_name = clean_name.strip("_")

        # 3. Handle empty or starting with non-letter
        if not clean_name:
            clean_name = f"col_{idx + 1}"
        elif clean_name[0].isdigit():
            clean_name = f"col_{clean_name}"

        # 4. Handle reserved keywords
        if clean_name in POSTGRES_RESERVED_KEYWORDS:
            clean_name = f"col_{clean_name}"

        # 5. Truncate to 50 chars to avoid exceeding PostgreSQL 63-byte identifier limit
        clean_name = clean_name[:50].rstrip("_")
        if not clean_name:
            clean_name = f"col_{idx + 1}"

        # 6. Guaranteed collision-free resolution
        candidate = clean_name
        counter = base_counts.get(clean_name, 1)

        if candidate in existing_internal_names:
            while candidate in existing_internal_names:
                counter += 1
                candidate = f"{clean_name}_{counter}"
            base_counts[clean_name] = counter
        else:
            base_counts[clean_name] = 1

        existing_internal_names.add(candidate)
        normalized_list.append((orig_name, candidate))

    return normalized_list


def is_boolean_series(series: pd.Series) -> bool:
    """Checks if a series contains purely boolean representations."""
    bool_literals = {True, False, "true", "false", "t", "f", "yes", "no"}
    valid_count = 0

    for v in series:
        if v is None or pd.isna(v):
            continue
        if isinstance(v, (bool, np.bool_)):
            valid_count += 1
        elif isinstance(v, str):
            low = v.strip().lower()
            if not low:
                continue
            if low not in bool_literals:
                return False
            valid_count += 1
        else:
            return False

    return valid_count > 0


def is_integer_series(series: pd.Series) -> bool:
    """Checks if all non-null values can be represented as 64-bit signed integers (PostgreSQL BIGINT)."""
    valid_count = 0

    for v in series:
        if v is None or pd.isna(v):
            continue
        # Note: In Python, bool is a subclass of int, so exclude it explicitly
        if isinstance(v, (bool, np.bool_)):
            return False
        if isinstance(v, (int, np.integer)):
            if not (POSTGRES_BIGINT_MIN <= v <= POSTGRES_BIGINT_MAX):
                return False
            valid_count += 1
            continue
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                continue
            if not v.is_integer():
                return False
            if not (POSTGRES_BIGINT_MIN <= v <= POSTGRES_BIGINT_MAX):
                return False
            valid_count += 1
            continue
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            if not re.match(r"^[+-]?\d+$", s):
                return False
            try:
                int_val = int(s)
                if not (POSTGRES_BIGINT_MIN <= int_val <= POSTGRES_BIGINT_MAX):
                    return False
                valid_count += 1
            except (ValueError, OverflowError):
                return False
        else:
            return False

    return valid_count > 0


def is_numeric_series(series: pd.Series) -> bool:
    """Checks if all non-null values can be represented as Decimal/NUMERIC."""
    valid_count = 0

    for v in series:
        if v is None or pd.isna(v):
            continue
        if isinstance(v, (bool, np.bool_)):
            return False
        if isinstance(v, (int, np.integer)):
            valid_count += 1
            continue
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                continue
            valid_count += 1
            continue
        if isinstance(v, Decimal):
            valid_count += 1
            continue
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if not s:
                continue
            try:
                Decimal(s)
                valid_count += 1
            except (InvalidOperation, ValueError):
                return False
        else:
            return False

    return valid_count > 0


def is_datetime_series(series: pd.Series) -> bool:
    """Conservatively checks if values match standard ISO date/datetime formats or datetime objects."""
    iso_pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
    )
    valid_count = 0

    for v in series:
        if v is None or pd.isna(v):
            continue
        if isinstance(v, (pd.Timestamp, pd.DatetimeIndex, datetime.datetime, datetime.date)):
            valid_count += 1
            continue
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            if not iso_pattern.match(s):
                return False
            try:
                pd.to_datetime(s)
                valid_count += 1
            except Exception:
                return False
        else:
            return False

    return valid_count > 0


def is_sensitive_column(column_name: str) -> bool:
    """
    Returns True if column name suggests sensitive or secret information.
    Uses token-based and targeted regex matching to prevent accidental substring
    collisions (e.g. 'syntax' or 'taxonomy' will NOT match 'tax').
    """
    low = column_name.lower().strip()
    clean_words = set(re.split(r"[^a-z0-9]+", low))
    if clean_words & SENSITIVE_TOKENS:
        return True

    return any(p.search(low) for p in SENSITIVE_PATTERNS)


def infer_column_metadata(
    internal_name: str,
    series: pd.Series
) -> tuple[str, bool, Optional[list[Any]]]:
    """
    Infers PostgreSQL data type conservatively, checks nullability, and extracts
    minimal, safe categorical sample values according to privacy restrictions.

    Returns:
        (inferred_type, nullable, sample_values)
    """
    total_len = len(series)
    valid_count = 0
    non_null_vals: list[Any] = []

    for v in series:
        if v is None or pd.isna(v):
            continue
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            valid_count += 1
            non_null_vals.append(s)
        elif isinstance(v, float) and math.isnan(v):
            continue
        else:
            valid_count += 1
            non_null_vals.append(v)

    nullable = (valid_count < total_len)

    # Empty or whitespace-only column safely falls back to nullable TEXT
    if valid_count == 0:
        return "TEXT", True, None

    # Conservative type inference
    if is_boolean_series(series):
        inferred_type = "BOOLEAN"
    elif is_integer_series(series):
        inferred_type = "BIGINT"
    elif is_numeric_series(series):
        inferred_type = "NUMERIC"
    elif is_datetime_series(series):
        inferred_type = "TIMESTAMPTZ"
    else:
        inferred_type = "TEXT"

    # Minimal & Conservative Sample Values (Section 1.5)
    sample_values: Optional[list[Any]] = None

    if inferred_type == "TEXT":
        if not is_sensitive_column(internal_name):
            cleaned_vals = [str(v).strip() for v in non_null_vals if str(v).strip()]
            unique_vals = list(dict.fromkeys(cleaned_vals))
            if 0 < len(unique_vals) <= 20 and all(len(s) <= 60 for s in unique_vals[:5]):
                sample_values = unique_vals[:5]
    elif inferred_type == "BOOLEAN":
        sample_values = [True, False]

    return inferred_type, nullable, sample_values


