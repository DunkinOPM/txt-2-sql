import re
from typing import Set, Tuple, Optional, Any
import sqlglot
from sqlglot import exp

# Explicitly approved analytical and scalar SQL functions
APPROVED_FUNCTIONS: Set[str] = {
    # Aggregates
    "count", "sum", "avg", "min", "max",
    # Math
    "round", "abs", "ceil", "ceiling", "floor", "trunc", "truncate", "mod", "power", "sqrt",
    # Strings
    "lower", "upper", "trim", "ltrim", "rtrim", "substring", "substr",
    "concat", "length", "replace", "left", "right", "position", "strpos",
    # Null & conditionals
    "coalesce", "nullif", "greatest", "least", "case",
    # Date & time
    "date_trunc", "extract", "now", "current_date", "current_time", "current_timestamp",
    "age", "date_part",
    # Formatting and casting
    "cast", "to_char", "to_date", "to_number", "to_timestamp",
}

# Forbidden system columns in PostgreSQL
FORBIDDEN_SYSTEM_COLUMNS: Set[str] = {
    "ctid", "xmin", "xmax", "cmin", "cmax", "tableoid"
}

# Deterministic patterns to reject outright before parsing
FORBIDDEN_RAW_PATTERNS = [
    re.compile(r"/\*.*?\*/", re.DOTALL),  # Block comments
    re.compile(r"--[^\r\n]*"),            # Line comments
    re.compile(
        r"\b(insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+\w+|"
        r"alter\s+\w+|create\s+\w+|truncate\s+\w+|grant\s+\w+|revoke\s+\w+|"
        r"copy\s+.*?\s+from|execute\s+\w+|vacuum\b|reindex\b|cluster\b|"
        r"lock\s+table|call\s+\w+|do\s+\$\$)\b",
        re.IGNORECASE
    ),
]


class SqlValidationError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_sql_query(
    candidate_sql: str,
    target_table_name: str,
    allowed_columns: Set[str],
) -> str:
    """
    Validates candidate SQL against SQLGlot AST parsing rules and independent security policies.
    Guarantees:
    - Single statement only.
    - Read-only query form: SELECT (with safe SELECT-only CTEs).
    - Table allowlist: strictly target_table_name in schema uploaded_data (or unqualified).
    - Schema allowlist: schema uploaded_data only; schema app, pg_catalog, etc. strictly rejected.
    - Column allowlist: only approved internal_names belonging to the target table.
    - Function allowlist: approved analytical/scalar functions only; system/admin functions rejected.
    - Rejects comments, stacked queries, mutations, and DDL.
    Returns:
    - Cleaned, normalized PostgreSQL SQL string.
    """
    clean_sql = candidate_sql.strip()
    if not clean_sql:
        raise SqlValidationError("EMPTY_SQL", "Generated SQL is empty.")

    # 1. Independent deterministic pre-checks
    for pattern in FORBIDDEN_RAW_PATTERNS:
        if pattern.search(clean_sql):
            raise SqlValidationError(
                "FORBIDDEN_SQL_CONSTRUCT",
                "SQL contains comments or mutating keywords prohibited by policy."
            )

    # Reject raw semicolons that separate multiple commands
    # (allow single trailing semicolon if present)
    trimmed_semicolon = clean_sql.rstrip(";\t \r\n")
    if ";" in trimmed_semicolon:
        raise SqlValidationError(
            "MULTIPLE_STATEMENTS_REJECTED",
            "Multiple SQL statements separated by semicolons are strictly prohibited."
        )

    # 2. Parse using SQLGlot for PostgreSQL
    try:
        parsed_statements = sqlglot.parse(trimmed_semicolon, read="postgres")
    except Exception as e:
        raise SqlValidationError(
            "SQL_SYNTAX_ERROR",
            f"Failed to parse SQL query with PostgreSQL dialect: {str(e)}"
        )

    if not parsed_statements:
        raise SqlValidationError("EMPTY_SQL", "No valid SQL statement found.")

    if len(parsed_statements) > 1:
        raise SqlValidationError(
            "MULTIPLE_STATEMENTS_REJECTED",
            "Exactly one SQL statement is permitted per query."
        )

    root_stmt = parsed_statements[0]
    if root_stmt is None:
        raise SqlValidationError("EMPTY_SQL", "Parsed SQL statement is null.")

    # 3. Verify root statement is a SELECT or UNION of SELECTs
    if not isinstance(root_stmt, (exp.Select, exp.Union)):
        raise SqlValidationError(
            "NON_READ_ONLY_STATEMENT",
            f"Only read-only SELECT statements are allowed. Found: {root_stmt.__class__.__name__}"
        )

    # 4. Check for any forbidden expression types anywhere in AST
    forbidden_classes = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
        exp.Create, exp.Command, exp.Transaction, exp.Commit, exp.Rollback,
        exp.Merge
    )
    for forbidden in root_stmt.find_all(forbidden_classes):
        raise SqlValidationError(
            "MUTATION_REJECTED",
            f"Disallowed mutating or administrative SQL statement type: {forbidden.__class__.__name__}"
        )

    # 5. Extract defined CTE aliases so they are recognized as valid local table sources
    cte_aliases: Set[str] = set()
    cte_columns: Set[str] = set()
    if hasattr(root_stmt, "ctes") and root_stmt.ctes:
        for cte in root_stmt.ctes:
            cte_alias = cte.alias.lower() if cte.alias else ""
            if cte_alias:
                cte_aliases.add(cte_alias)
            # Verify CTE inner query is strictly SELECT
            cte_query = cte.this
            if not isinstance(cte_query, (exp.Select, exp.Union)):
                raise SqlValidationError(
                    "NON_READ_ONLY_CTE",
                    f"CTE '{cte_alias}' contains a non-SELECT statement."
                )
            # Collect CTE column aliases
            for select_item in cte_query.selects:
                if isinstance(select_item, exp.Alias):
                    cte_columns.add(select_item.alias.lower())
                elif isinstance(select_item, exp.Column):
                    cte_columns.add(select_item.name.lower())

    # 6. Table Allowlist Check
    # Every table referenced must be either the designated dataset table or a valid local CTE
    normalized_target_table = target_table_name.lower().strip('"')
    all_tables = root_stmt.find_all(exp.Table)

    has_target_table = False
    for table_expr in all_tables:
        t_name = table_expr.name.lower().strip('"')
        t_schema = table_expr.db.lower().strip('"') if table_expr.db else None

        # Check if table reference is a local CTE
        if t_name in cte_aliases:
            if t_schema is not None:
                raise SqlValidationError(
                    "UNAUTHORIZED_SCHEMA_ACCESS",
                    f"CTE '{t_name}' cannot be qualified with schema '{t_schema}'."
                )
            continue

        # Reject any unauthorized schema (especially 'app', 'pg_catalog', 'information_schema')
        if t_schema not in (None, "uploaded_data"):
            raise SqlValidationError(
                "UNAUTHORIZED_SCHEMA_ACCESS",
                f"Access to schema '{t_schema}' is strictly denied. Only 'uploaded_data' is accessible."
            )

        # Check table name match
        if t_name != normalized_target_table:
            raise SqlValidationError(
                "UNAUTHORIZED_TABLE_ACCESS",
                f"Query references unauthorized table '{t_name}'. Only '{normalized_target_table}' is permitted."
            )

        has_target_table = True

    # Ensure at least one table was referenced (or CTE based on target)
    if not has_target_table and not cte_aliases:
        raise SqlValidationError(
            "NO_TABLE_REFERENCED",
            "Query must query the authorized dataset table."
        )

    # 7. Function Allowlist Check
    for func in root_stmt.find_all(exp.Func):
        if isinstance(func, exp.Anonymous):
            f_name = func.this.lower().strip('"')
        elif hasattr(func, "key") and func.key:
            f_name = func.key.lower()
        else:
            f_name = func.__class__.__name__.lower()

        # Reject functions starting with pg_ or administrative prefixes
        if f_name.startswith("pg_") or f_name.startswith("lo_") or f_name not in APPROVED_FUNCTIONS:
            raise SqlValidationError(
                "UNAPPROVED_FUNCTION_REJECTED",
                f"Function '{f_name}' is not in the approved safe analytical function list."
            )

    # 8. Column Allowlist Check
    # Normalize allowed columns to lowercase
    normalized_allowed_cols = {c.lower().strip('"') for c in allowed_columns}

    # Collect projection aliases defined in the root query
    root_aliases: Set[str] = set()
    if hasattr(root_stmt, "selects"):
        for sel in root_stmt.selects:
            if isinstance(sel, exp.Alias):
                root_aliases.add(sel.alias.lower().strip('"'))

    for col in root_stmt.find_all(exp.Column):
        c_name = col.name.lower().strip('"')

        # Check for system column injection
        if c_name in FORBIDDEN_SYSTEM_COLUMNS:
            raise SqlValidationError(
                "SYSTEM_COLUMN_REJECTED",
                f"Access to PostgreSQL system column '{c_name}' is prohibited."
            )

        # Wildcard * is valid for selecting columns
        if c_name == "*":
            continue

        # Column could be from a CTE or an alias
        if c_name in cte_columns or c_name in root_aliases:
            continue

        # Column must be in dataset's allowed columns
        if c_name not in normalized_allowed_cols:
            raise SqlValidationError(
                "UNAUTHORIZED_COLUMN_ACCESS",
                f"Column '{c_name}' does not exist in the authorized dataset schema."
            )

    # Return normalized SQL with target schema explicitly qualified
    # Transpile to clean standard postgres SQL
    normalized_sql = root_stmt.sql(dialect="postgres")
    return normalized_sql
