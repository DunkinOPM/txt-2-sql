"""
Semantic Intent Extraction, Semantic SQL Generation, and Semantic Intent Validation.

Ensures Text-to-SQL generation and repair:
1. Accurately reflect the requested analytical operations (AVG, SUM, COUNT, MIN, MAX).
2. Reference the user's intended columns rather than defaulting to unrelated columns.
3. Group and filter by the requested attributes.
4. Honor top/bottom sorting and limits.
5. Gracefully fail with clear explanation if requested columns are missing or incompatible.
6. Never silently return an unrelated 'SELECT first_col FROM table LIMIT 10' query.
"""

import re
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import sqlglot
from sqlglot import exp

from app.services.sql_validator import validate_sql_query, SqlValidationError
from app.services.ambiguity_detector import (
    is_identifier_column,
    is_non_evaluative_column,
    detect_out_of_scope_query,
    get_candidate_metric_columns,
    match_column_in_text,
    is_unresolved_evaluative_query,
)

logger = logging.getLogger(__name__)

NUMERIC_TYPES: Set[str] = {
    "INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT",
    "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE PRECISION",
    "DOUBLE_PRECISION", "REAL"
}

DATE_TYPES: Set[str] = {
    "DATE", "TIMESTAMP", "TIMESTAMPTZ", "TIME"
}

STOP_WORDS: Set[str] = {
    "what", "is", "the", "of", "in", "for", "a", "an", "and", "or",
    "are", "there", "show", "give", "me", "all", "get", "find", "list",
    "tell", "please", "can", "you", "which", "who", "with", "from",
    "table", "data", "dataset", "record", "records", "row", "rows",
    "to", "at", "by", "per", "on", "that", "this", "each", "every"
}

# Generic entity domain nouns that must not match columns via substring token in Pass 2
GENERIC_ENTITY_TERMS: Set[str] = {
    "student", "students", "employee", "employees", "user", "users",
    "customer", "customers", "item", "items", "entry", "entries",
    "record", "records", "person", "people", "worker", "workers",
    "member", "members", "player", "players", "product", "products",
    "order", "orders", "row", "rows", "table", "dataset", "data"
}

# Known non-column analytical terms to ignore during missing-column detection
NON_COLUMN_TERMS: Set[str] = {
    "average", "avg", "mean", "total", "sum", "count", "number", "quantity",
    "maximum", "max", "highest", "peak", "most", "greatest", "oldest",
    "minimum", "min", "lowest", "least", "smallest", "youngest", "fewest",
    "top", "bottom", "first", "last", "order", "sort", "ascending", "descending",
    "greater", "more", "less", "fewer", "equal", "above", "below", "between",
    "student", "students", "employee", "employees", "user", "users", "item", "items",
    "entry", "entries", "record", "records", "details", "detail", "row", "rows",
    "information", "breakdown", "department", "departments", "result", "results"
}

METRIC_SYNONYMS: Dict[str, List[str]] = {
    "score": ["marks", "grade", "points", "gpa", "cgpa", "exam", "test", "result", "rating"],
    "scoring": ["marks", "score", "grade", "points", "gpa", "cgpa", "exam", "test"],
    "scored": ["marks", "score", "grade", "points", "gpa", "cgpa"],
    "performing": ["performance", "rating", "score", "marks", "gpa", "cgpa", "sales", "revenue", "output"],
    "performance": ["rating", "score", "marks", "gpa", "cgpa", "sales", "revenue", "output"],
    "performer": ["performance", "rating", "score", "marks", "gpa", "cgpa", "sales", "revenue", "output"],
    "performers": ["performance", "rating", "score", "marks", "gpa", "cgpa", "sales", "revenue", "output"],
    "productive": ["production", "output", "units", "yield", "volume"],
    "paid": ["salary", "wage", "pay", "compensation", "revenue", "income", "rate"],
    "paying": ["salary", "wage", "pay", "compensation", "revenue", "income", "rate"],
    "earning": ["salary", "wage", "pay", "compensation", "income", "revenue"],
    "earner": ["salary", "wage", "pay", "compensation", "income"],
    "earners": ["salary", "wage", "pay", "compensation", "income"],
    "costing": ["price", "cost", "amount", "fee", "rate"],
    "priced": ["price", "cost", "amount", "fee", "rate"],
    "rated": ["rating", "stars", "score", "rank"],
    "selling": ["sales", "revenue", "units", "quantity", "volume"],
    "sold": ["units_sold", "units", "sales", "quantity", "volume"],
    "buyer": ["purchases", "orders", "spent", "spending"],
}


def find_metric_column(token: str, columns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Finds a numeric column matching a metric token or its synonyms/stems.
    Excludes identifiers and non-evaluative columns.
    """
    if not token or not columns:
        return None
    t = token.lower().strip("?,.'\"();: ")
    if not t:
        return None

    # Direct column match
    col = find_column_by_name(t, columns)
    if col and col.get("inferred_type", "").upper() in NUMERIC_TYPES and not is_identifier_column(col) and not is_non_evaluative_column(col):
        return col

    # Synonyms and stemming
    syns = METRIC_SYNONYMS.get(t, [])
    stem = re.sub(r"(ing|ed|s)$", "", t)
    if stem in METRIC_SYNONYMS:
        syns = list(set(syns + METRIC_SYNONYMS[stem]))

    for s in syns:
        c = find_column_by_name(s, columns)
        if c and c.get("inferred_type", "").upper() in NUMERIC_TYPES and not is_identifier_column(c) and not is_non_evaluative_column(c):
            return c

    return None


def find_column_by_name(token: str, columns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Finds a column in columns_metadata by matching original or internal names.
    Supports exact match, normalized alphanumeric, singular/plural, and word token matching.
    """
    if not token or not columns:
        return None

    t = token.lower().strip("?,.'\"();: ")
    if not t:
        return None

    t_clean = re.sub(r"[^a-z0-9]", "", t)

    # Pass 1: Exact and singular/plural matches
    for col in columns:
        orig = col.get("original_name", "").lower()
        internal = col.get("internal_name", "").lower()
        orig_clean = re.sub(r"[^a-z0-9]", "", orig)

        if t == orig or t == internal or (t_clean and (t_clean == orig_clean or t_clean == internal)):
            return col

        t_s = t[:-1] if t.endswith("s") else t
        orig_s = orig[:-1] if orig.endswith("s") else orig
        internal_s = internal[:-1] if internal.endswith("s") else internal

        if t_s and (t_s == orig_s or t_s == internal_s):
            return col

    # Pass 2: Word token inside column name (e.g. "name" in "student_name")
    # Generic entity nouns (e.g. "student", "employee") must NOT match a multi-word column like "Student Name"
    if len(t) >= 4 and t not in STOP_WORDS and t not in GENERIC_ENTITY_TERMS and t_clean not in GENERIC_ENTITY_TERMS:
        t_s = t[:-1] if t.endswith("s") else t
        if t_s not in GENERIC_ENTITY_TERMS:
            for col in columns:
                internal = col.get("internal_name", "").lower()
                orig = col.get("original_name", "").lower()
                int_parts = internal.split("_")
                orig_parts = orig.split()
                if t in int_parts or t in orig_parts or (t_s and (t_s in int_parts or t_s in orig_parts)):
                    return col

    return None


def extract_query_intent(question: str, columns_metadata: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extracts the analytical intent, referenced columns, aggregations, grouping,
    filters, sorting, and limits from the natural language question.
    """
    q_lower = question.lower()
    intent: Dict[str, Any] = {
        "aggregation": None,
        "agg_column": None,
        "group_by_column": None,
        "filters": [],
        "order_column": None,
        "order_direction": None,
        "limit": None,
        "target_columns": [],
        "primary_target_col": None,
        "missing_column": None,
        "incompatible_type_error": None,
    }

    # 1. Identify all directly mentioned authorized columns (using n-grams and tokens)
    mentioned_cols: List[Dict[str, Any]] = []

    words = [w.strip("?,.'\"();: ") for w in q_lower.split()]
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i+n])
            if phrase and phrase not in STOP_WORDS and phrase not in NON_COLUMN_TERMS:
                c = find_column_by_name(phrase, columns_metadata)
                if c and c not in mentioned_cols:
                    mentioned_cols.append(c)

    for col in columns_metadata:
        orig = col.get("original_name", "").lower()
        internal = col.get("internal_name", "").lower()

        pattern_orig = r"\b" + re.escape(orig) + r"\b"
        pattern_internal = r"\b" + re.escape(internal) + r"\b"

        if re.search(pattern_orig, q_lower) or re.search(pattern_internal, q_lower):
            if col not in mentioned_cols:
                mentioned_cols.append(col)
        elif len(orig) > 3:
            orig_s = orig[:-1] if orig.endswith("s") else orig + "s"
            if re.search(r"\b" + re.escape(orig_s) + r"\b", q_lower):
                if col not in mentioned_cols:
                    mentioned_cols.append(col)

    intent["target_columns"] = mentioned_cols

    # Primary requested target column e.g. "what is the age of...", "give me the student id of..."
    target_match = re.search(
        r"\b(?:what is|what's|which is|give me|show|find|list|get|display|select|tell me)\s+(?:the\s+)?([a-zA-Z0-9_ ]+?)\s+(?:of|for|with|from|where|having|in|who|which)\b",
        q_lower
    )
    if target_match:
        cand_phrase = target_match.group(1).strip()
        primary_c = find_column_by_name(cand_phrase, columns_metadata)
        if primary_c:
            intent["primary_target_col"] = primary_c

    # Ensure all distinct requested target columns are maintained with primary target first
    targets: List[Dict[str, Any]] = []
    if intent.get("primary_target_col"):
        targets.append(intent["primary_target_col"])
    for c in mentioned_cols:
        if not any(t["internal_name"] == c["internal_name"] for t in targets):
            targets.append(c)
    intent["target_columns"] = targets

    # 2. Detect Limit & Ordering Intent ("Top 5 students by GPA", "Bottom 10", "Sorted by Marks")
    top_m = re.search(r"\btop\s+(\d+)\b", q_lower)
    bot_m = re.search(r"\bbottom\s+(\d+)\b", q_lower)
    first_m = re.search(r"\bfirst\s+(\d+)\b", q_lower)

    if top_m:
        intent["limit"] = int(top_m.group(1))
        intent["order_direction"] = "DESC"
    elif bot_m:
        intent["limit"] = int(bot_m.group(1))
        intent["order_direction"] = "ASC"
    elif first_m:
        intent["limit"] = int(first_m.group(1))
        intent["order_direction"] = "ASC"

    # Find ordering column
    order_m = re.search(r"\b(?:sorted by|ordered by|(?:top|bottom|first|highest|lowest|best|worst)\s+\d+\s+.*?\s+by)\s+([a-zA-Z0-9_ ]+)", q_lower)
    if order_m:
        phrase = order_m.group(1).strip()
        c = find_column_by_name(phrase, columns_metadata)
        if c:
            intent["order_column"] = c
        else:
            for word in phrase.split():
                c = find_column_by_name(word, columns_metadata)
                if c:
                    intent["order_column"] = c
                    break

    if not intent["order_column"] and (top_m or bot_m):
        for col in mentioned_cols:
            if col.get("inferred_type", "").upper() in NUMERIC_TYPES and not is_identifier_column(col):
                intent["order_column"] = col
                break

    # Check ranking superlatives for entity requests (e.g. "student with the highest GPA", "highest scoring student")
    highest_m = re.search(r"\b(?:highest|maximum|max|top|peak|best|oldest)\s+([a-zA-Z0-9_ ]+)", q_lower)
    lowest_m = re.search(r"\b(?:lowest|minimum|min|least|worst|youngest)\s+([a-zA-Z0-9_ ]+)", q_lower)

    metric_rank_col = None
    rank_dir = "DESC"
    if highest_m:
        phrase = highest_m.group(1).strip()
        c = find_metric_column(phrase, columns_metadata)
        if c:
            metric_rank_col = c
            rank_dir = "DESC"
        else:
            for w in phrase.split():
                c = find_metric_column(w, columns_metadata)
                if c:
                    metric_rank_col = c
                    rank_dir = "DESC"
                    break
    elif lowest_m:
        phrase = lowest_m.group(1).strip()
        c = find_metric_column(phrase, columns_metadata)
        if c:
            metric_rank_col = c
            rank_dir = "ASC"
        else:
            for w in phrase.split():
                c = find_metric_column(w, columns_metadata)
                if c:
                    metric_rank_col = c
                    rank_dir = "ASC"
                    break

    # If not found immediately after superlative, but the phrase/question contains candidate metrics or evaluative concept
    if not metric_rank_col and (highest_m or lowest_m):
        cand_metrics = get_candidate_metric_columns(columns_metadata)
        matched_cand_metrics = [
            c for c in cand_metrics
            if any(m["internal_name"] == c["internal_name"] for m in mentioned_cols)
            or match_column_in_text(question, [c])
        ]
        if matched_cand_metrics:
            rank_dir = "DESC" if highest_m else "ASC"
            # If primary target is a candidate metric (e.g. "What is the GPA of..."), use it
            if intent.get("primary_target_col") and any(
                c["internal_name"] == intent["primary_target_col"]["internal_name"]
                for c in matched_cand_metrics
            ):
                metric_rank_col = intent["primary_target_col"]
            else:
                metric_rank_col = matched_cand_metrics[0]

    # Check clarification in parentheses: "give me student id of top performing student (GPA)"
    paren_m = re.search(r"\(([^)]+)\)$", question)
    if paren_m and not metric_rank_col:
        c = find_column_by_name(paren_m.group(1).strip(), columns_metadata)
        if c:
            metric_rank_col = c
            rank_dir = "DESC"

    is_entity_query = (
        intent.get("primary_target_col") is not None or
        any(c != metric_rank_col for c in mentioned_cols) or
        any(k in q_lower for k in ("student", "employee", "product", "who", "which", "give me", "find", "performer"))
    )
    is_pure_scalar = (
        bool(re.search(r"\bwhat\s+is\s+(?:the\s+)?(highest|maximum|max|lowest|minimum|min|average|avg|sum|total)\b", q_lower))
        and not (intent.get("primary_target_col") is not None or any(c != metric_rank_col for c in mentioned_cols))
    )

    is_top_or_sort = bool(top_m or bot_m or re.search(r"\b(sorted by|ordered by)\b", q_lower))

    if metric_rank_col and (is_entity_query or not is_pure_scalar) and not is_top_or_sort:
        intent["order_column"] = metric_rank_col
        intent["order_direction"] = rank_dir
        intent["limit"] = 1

    # Filter out pure ordering modifiers from target_columns if user didn't ask for them as outputs
    # (e.g. "What is the age of the student with the highest marks?" -> marks is order modifier, age is output)
    if intent.get("primary_target_col") and intent.get("order_column"):
        ord_int = intent["order_column"]["internal_name"]
        prim_int = intent["primary_target_col"]["internal_name"]
        if ord_int != prim_int:
            ord_orig = intent["order_column"].get("original_name", "").lower()
            ord_pat = rf"\b(?:and|give|show|what is|find|list|along with|too|also)\b.*?\b(?:{re.escape(ord_orig)}|{re.escape(ord_int)})\b"
            if not re.search(ord_pat, q_lower):
                intent["target_columns"] = [
                    c for c in intent["target_columns"]
                    if c["internal_name"] != ord_int
                ]

    # 3. Detect Grouping ("by department", "per department", "for each department", "grouped by department")
    # Note: 'by <col>' in 'top N by <col>' or 'sorted by <col>' is sorting, NOT grouping.
    if is_top_or_sort:
        group_match = re.search(r"\b(?:grouped by|per|for each)\s+([a-zA-Z0-9_ ]+)", q_lower)
    else:
        group_match = re.search(r"\b(?:grouped by|by|per|for each)\s+([a-zA-Z0-9_ ]+)", q_lower)

    if group_match:
        phrase = group_match.group(1).strip()
        for word in phrase.split():
            matched_group = find_column_by_name(word, columns_metadata)
            if matched_group and matched_group != intent.get("order_column"):
                intent["group_by_column"] = matched_group
                break

    # 4. Detect Aggregation Intent (AVG, COUNT, SUM, MAX, MIN)
    # A. Average
    if re.search(r"\b(average|avg|mean)\b", q_lower):
        intent["aggregation"] = "AVG"
        # Find which column to average
        match = re.search(r"\b(?:average|avg|mean)\s+(?:of\s+)?([a-zA-Z0-9_ ]+)", q_lower)
        if match:
            for word in match.group(1).split():
                candidate_col = find_column_by_name(word, columns_metadata)
                if candidate_col:
                    intent["agg_column"] = candidate_col
                    break
        # If not adjacent, search mentioned columns (excluding group-by col)
        if not intent["agg_column"]:
            for col in mentioned_cols:
                if col != intent.get("group_by_column"):
                    intent["agg_column"] = col
                    break

    # B. Count
    elif re.search(r"\b(count|how many|number of|total number|total count)\b", q_lower):
        intent["aggregation"] = "COUNT"

    # C. Sum / Total
    elif not (top_m or bot_m or first_m) and re.search(r"\b(sum\b|sum\s+of|total\s+(?:marks|score|scores|amount|sales|revenue|cost|points|value))\b", q_lower):
        intent["aggregation"] = "SUM"
        match = re.search(r"\b(?:sum|total)\s+(?:of\s+)?([a-zA-Z0-9_ ]+)", q_lower)
        if match:
            for word in match.group(1).split():
                candidate_col = find_column_by_name(word, columns_metadata)
                if candidate_col:
                    intent["agg_column"] = candidate_col
                    break
        if not intent["agg_column"]:
            for col in mentioned_cols:
                if col != intent.get("group_by_column"):
                    intent["agg_column"] = col
                    break

    # D. Maximum
    elif (
        re.search(r"\b(maximum|max\b|highest|peak|most|greatest|oldest)\b", q_lower)
        and not intent.get("order_column")
        and not (intent.get("target_columns") and len(intent["target_columns"]) > 1)
        and not any(k in q_lower for k in ("performing", "performer", "scoring", "scorer", "student", "employee", "who", "which", "give me", "give the"))
    ):
        intent["aggregation"] = "MAX"
        match = re.search(r"\b(?:maximum|max|highest|peak|most|greatest|oldest)\s+(?:of\s+(?:the\s+)?)?([a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)?)", q_lower)
        if match:
            candidate_col = find_column_by_name(match.group(1).strip(), columns_metadata)
            if not candidate_col:
                for word in match.group(1).split():
                    candidate_col = find_column_by_name(word, columns_metadata)
                    if candidate_col:
                        break
            if candidate_col:
                intent["agg_column"] = candidate_col
        if not intent["agg_column"]:
            for col in mentioned_cols:
                if col != intent.get("group_by_column"):
                    intent["agg_column"] = col
                    break

    # E. Minimum
    elif (
        re.search(r"\b(minimum|min\b|lowest|least|smallest|youngest|fewest)\b", q_lower)
        and not intent.get("order_column")
        and not (intent.get("target_columns") and len(intent["target_columns"]) > 1)
        and not any(k in q_lower for k in ("performing", "performer", "scoring", "scorer", "student", "employee", "who", "which", "give me", "give the"))
    ):
        intent["aggregation"] = "MIN"
        match = re.search(r"\b(?:minimum|min|lowest|least|smallest|youngest|fewest)\s+(?:of\s+(?:the\s+)?)?([a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)?)", q_lower)
        if match:
            candidate_col = find_column_by_name(match.group(1).strip(), columns_metadata)
            if not candidate_col:
                for word in match.group(1).split():
                    candidate_col = find_column_by_name(word, columns_metadata)
                    if candidate_col:
                        break
            if candidate_col:
                intent["agg_column"] = candidate_col
        if not intent["agg_column"]:
            for col in mentioned_cols:
                if col != intent.get("group_by_column"):
                    intent["agg_column"] = col
                    break

    # 4. Check for Incompatible Aggregation Type (e.g. AVG on TEXT column)
    if intent["aggregation"] in ("AVG", "SUM") and intent["agg_column"]:
        c_type = intent["agg_column"].get("inferred_type", "TEXT").upper()
        if c_type not in NUMERIC_TYPES:
            intent["incompatible_type_error"] = (
                f"Cannot compute {intent['aggregation']} on column '{intent['agg_column']['original_name']}' "
                f"because its data type is {c_type} (numeric type required)."
            )


    # 6. Detect Filters
    # A. Age-specific phrases
    age_col = find_column_by_name("age", columns_metadata)
    if age_col:
        m_old = re.search(r"\b(?:older than|age >|age greater than|age above|age more than)\s*(\d+(?:\.\d+)?)\b", question, re.I)
        if m_old:
            intent["filters"].append({"column": age_col, "op": ">", "value": m_old.group(1), "is_string": False})
        m_young = re.search(r"\b(?:younger than|age <|age less than|age below)\s*(\d+(?:\.\d+)?)\b", question, re.I)
        if m_young:
            intent["filters"].append({"column": age_col, "op": "<", "value": m_young.group(1), "is_string": False})

    # B. General numeric comparisons: <col> (>=|<=|>|<|=|above|below|greater than|less than) <num>
    num_comp = re.finditer(
        r"\b([a-zA-Z_]+)\s*(?:(>=|<=|>|<|=|greater than|more than|above|less than|below|equal to|at least|at most))\s*(\d+(?:\.\d+)?)\b",
        question,
        re.I
    )
    for m in num_comp:
        col_word = m.group(1)
        col = find_column_by_name(col_word, columns_metadata)
        if col:
            op_raw = m.group(2).lower()
            val = m.group(3)
            if op_raw in (">=", "at least"):
                op = ">="
            elif op_raw in ("<=", "at most"):
                op = "<="
            elif op_raw in (">", "greater than", "more than", "above"):
                op = ">"
            elif op_raw in ("<", "less than", "below"):
                op = "<"
            else:
                op = "="

            if not any(f["column"]["internal_name"] == col["internal_name"] and f["op"] == op for f in intent["filters"]):
                intent["filters"].append({"column": col, "op": op, "value": val, "is_string": False})

    # C. Categorical / string filters across all schema columns
    for col in columns_metadata:
        c_type = col.get("inferred_type", "TEXT").upper()
        if c_type in ("TEXT", "VARCHAR"):
            orig = col.get("original_name", "").lower()
            internal = col.get("internal_name", "").lower()

            # Pattern 1: in <val> <col> or from <val> <col>
            pat_in = rf"\b(?:in|from)\s+['\"]?([a-zA-Z0-9_ ]+?)['\"]?\s+(?:{re.escape(orig)}|{re.escape(internal)})\b"
            m_in = re.search(pat_in, q_lower)
            if m_in:
                val = m_in.group(1).strip()
                if val and val not in STOP_WORDS and val not in ("table", "data", "dataset"):
                    if not any(f["column"]["internal_name"] == col["internal_name"] for f in intent["filters"]):
                        intent["filters"].append({"column": col, "op": "=", "value": f"'{val}'", "is_string": True})
            else:
                # Pattern 2: <col> (is|=) '<val>'
                pat_eq = rf"\b(?:{re.escape(orig)}|{re.escape(internal)})\s*(?:is|=|==)\s*['\"]?([a-zA-Z0-9_ ]+?)['\"]?(?:\s+and|\s+with|$)"
                m_eq = re.search(pat_eq, q_lower)
                if m_eq:
                    val = m_eq.group(1).strip()
                    if val and val not in STOP_WORDS and val not in ("table", "data", "dataset"):
                        if not any(f["column"]["internal_name"] == col["internal_name"] for f in intent["filters"]):
                            intent["filters"].append({"column": col, "op": "=", "value": f"'{val}'", "is_string": True})

    # 7. Detect Missing Column Requests for Aggregations:
    # E.g. "average salary", "mean salary", "sum of salary", "total salary"
    match_missing_agg = re.search(r"\b(?:average|avg|mean|sum of|sum)\s+([a-zA-Z_]+)\b", q_lower)
    if match_missing_agg:
        word = match_missing_agg.group(1).strip()
        if word not in STOP_WORDS and word not in NON_COLUMN_TERMS:
            if not find_column_by_name(word, columns_metadata):
                intent["missing_column"] = word

    return intent


def generate_semantic_sql(
    question: str,
    table_name: str,
    columns: List[Dict[str, Any]],
    dataset_name: str = "Dataset",
    structured_intent: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generates a PostgreSQL query grounded in the natural language question, authorized schema,
    and optional structured intent. Used for local / offline / fallback execution without Gemini,
    preserving 100% semantic correctness.
    """
    # 0. Reject out of scope queries immediately
    oos = detect_out_of_scope_query(dataset_name, columns, question)
    if oos:
        raise SqlValidationError(
            "OUT_OF_SCOPE",
            oos.reason or f"The question is completely unrelated to dataset '{dataset_name}'."
        )

    intent = extract_query_intent(question, columns)

    # Merge structured_intent if provided
    if structured_intent and isinstance(structured_intent, dict):
        req_outs = structured_intent.get("requested_outputs", [])
        if req_outs:
            matched_targets = []
            for ro in req_outs:
                c = find_column_by_name(ro, columns)
                if c and not any(m["internal_name"] == c["internal_name"] for m in matched_targets):
                    matched_targets.append(c)
            if matched_targets:
                intent["target_columns"] = matched_targets
                if not intent.get("primary_target_col"):
                    intent["primary_target_col"] = matched_targets[0]

        sort_rank = structured_intent.get("sorting_and_ranking")
        if sort_rank:
            parts = sort_rank.strip().split()
            sort_c = find_column_by_name(parts[0], columns)
            if sort_c:
                intent["order_column"] = sort_c
                intent["order_direction"] = parts[1].upper() if len(parts) > 1 and parts[1].upper() in ("ASC", "DESC") else "DESC"

        limit_val = structured_intent.get("result_limit")
        if limit_val is not None:
            try:
                intent["limit"] = int(limit_val)
            except (ValueError, TypeError):
                pass

    # 1. Reject if requested column is missing
    if intent["missing_column"]:
        avail = ", ".join(f"'{c.get('original_name')}'" for c in columns)
        raise SqlValidationError(
            "MISSING_REQUESTED_COLUMN",
            f"The dataset '{dataset_name}' does not contain column '{intent['missing_column']}'. "
            f"Available columns are: {avail}."
        )

    # 2. Reject if requested aggregation is incompatible with column type
    if intent["incompatible_type_error"]:
        raise SqlValidationError("INCOMPATIBLE_COLUMN_TYPE", intent["incompatible_type_error"])

    clean_table = table_name.replace("uploaded_data.", "")
    target_table = f"uploaded_data.{clean_table}"
    where_clauses: List[str] = []

    # Build WHERE conditions
    for f in intent["filters"]:
        c_internal = f["column"]["internal_name"]
        op = f["op"]
        val = f["value"]
        if f.get("is_string"):
            clean_val = val.strip("'\"")
            where_clauses.append(f"LOWER({c_internal}) = LOWER('{clean_val}')")
        else:
            where_clauses.append(f"{c_internal} {op} {val}")

    where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # 3. Aggregations (AVG, SUM, MIN, MAX)
    if intent["aggregation"] in ("AVG", "SUM", "MIN", "MAX"):
        agg_func = intent["aggregation"]
        agg_col = intent["agg_column"]
        if not agg_col:
            num_cols = [c for c in columns if c.get("inferred_type", "").upper() in NUMERIC_TYPES]
            if not num_cols:
                raise SqlValidationError(
                    "INCOMPATIBLE_COLUMN_TYPE",
                    f"No numeric columns available in dataset '{dataset_name}' to compute {agg_func}."
                )
            agg_col = num_cols[0]

        col_name = agg_col["internal_name"]
        alias = f"{agg_func.lower()}_{col_name}"

        # If grouping requested
        if intent["group_by_column"]:
            grp_col = intent["group_by_column"]["internal_name"]
            return f"SELECT {grp_col}, {agg_func}({col_name}) AS {alias} FROM {target_table}{where_str} GROUP BY {grp_col}"

        return f"SELECT {agg_func}({col_name}) AS {alias} FROM {target_table}{where_str}"

    # 4. Aggregation (COUNT)
    if intent["aggregation"] == "COUNT":
        if intent["group_by_column"]:
            grp_col = intent["group_by_column"]["internal_name"]
            return f"SELECT {grp_col}, COUNT(*) AS total_count FROM {target_table}{where_str} GROUP BY {grp_col}"

        return f"SELECT COUNT(*) AS total_count FROM {target_table}{where_str}"

    # 5. Top N / Bottom N Sorting and Limits
    if intent["limit"] and intent["order_column"]:
        ord_col = intent["order_column"]["internal_name"]
        direction = intent["order_direction"] or "DESC"
        limit_val = intent["limit"]

        proj_cols = []
        if intent.get("target_columns"):
            # Ensure primary_target_col is placed first if present
            ordered_targets = list(intent["target_columns"])
            if intent.get("primary_target_col"):
                prim = intent["primary_target_col"]
                ordered_targets = [prim] + [c for c in ordered_targets if c["internal_name"] != prim["internal_name"]]
            for c in ordered_targets:
                c_name = c["internal_name"]
                if c_name not in proj_cols:
                    proj_cols.append(c_name)
        elif intent.get("primary_target_col"):
            proj_cols.append(intent["primary_target_col"]["internal_name"])
        else:
            # Project identifying entity column (like name/id) and the ordered metric
            name_or_id = next(
                (c["internal_name"] for c in columns if any(k in c["internal_name"] for k in ("name", "id"))),
                None
            )
            if name_or_id and name_or_id != ord_col:
                proj_cols.append(name_or_id)
            proj_cols.append(ord_col)

        cols_str = ", ".join(proj_cols)
        return f"SELECT {cols_str} FROM {target_table}{where_str} ORDER BY {ord_col} {direction} LIMIT {limit_val}"

    # 6. Specific Column Selection vs All Records
    filter_cols = {f["column"]["internal_name"] for f in intent["filters"]}
    target_non_filter = [c for c in intent["target_columns"] if c["internal_name"] not in filter_cols]

    if target_non_filter:
        cols_str = ", ".join(c["internal_name"] for c in intent["target_columns"])
        return f"SELECT {cols_str} FROM {target_table}{where_str}"
    elif intent["target_columns"] and not intent["filters"]:
        cols_str = ", ".join(c["internal_name"] for c in intent["target_columns"])
        return f"SELECT {cols_str} FROM {target_table}{where_str}"

    # Unresolved ranking/superlative check - NEVER fallback to SELECT * for unranked superlatives!
    q_lower = question.lower()
    if any(k in q_lower for k in ("top", "best", "worst", "performing", "highest", "lowest", "performer")):
        raise SqlValidationError(
            "UNRESOLVED_AMBIGUOUS_METRIC",
            "Cannot generate SQL for query with unresolved ranking or performance metric."
        )

    # 7. Filtered or general listing
    if where_str:
        return f"SELECT * FROM {target_table}{where_str}"

    full_table_keywords = {"all records", "all rows", "all data", "show all", "list all", "display all", "everything"}
    if any(k in q_lower for k in full_table_keywords):
        return f"SELECT * FROM {target_table}"

    # Never silently fall back to SELECT * for unmapped queries!
    raise SqlValidationError(
        "UNRESOLVED_QUERY_INTENT",
        f"Could not map question to authorized columns or operations in dataset '{dataset_name}'. No arbitrary table scan will be generated."
    )


def repair_semantic_sql(
    question: str,
    table_name: str,
    columns: List[Dict[str, Any]],
    failed_sql: str,
    error_message: str,
    dataset_name: str = "Dataset",
    structured_intent: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Deterministically repairs failed SQL:
    1. First attempts AST-based repair on failed_sql for missing operations
       (e.g., missing or incorrect LIMIT, missing ORDER BY, missing GROUP BY) while preserving user intent.
    2. Validates that the query does not attempt to guess an unresolved ambiguous metric
       (e.g., 'top 5 performing' without a defined metric column raises UNRESOLVED_AMBIGUOUS_METRIC).
    3. If AST repair fails or isn't applicable, falls back to full semantic SQL generation.
    4. Validates the repaired SQL against both security policies and semantic rules.
    """
    logger.info(f"Repairing SQL using semantic engine for error: {error_message}")
    # 0. Reject out of scope queries immediately
    oos = detect_out_of_scope_query(dataset_name, columns, question)
    if oos:
        raise SqlValidationError(
            "OUT_OF_SCOPE",
            oos.reason or f"The question is completely unrelated to dataset '{dataset_name}'."
        )

    intent = extract_query_intent(question, columns)
    if structured_intent and isinstance(structured_intent, dict):
        sort_rank = structured_intent.get("sorting_and_ranking")
        if sort_rank:
            parts = sort_rank.strip().split()
            sort_c = find_column_by_name(parts[0], columns)
            if sort_c:
                intent["order_column"] = sort_c
                intent["order_direction"] = parts[1].upper() if len(parts) > 1 and parts[1].upper() in ("ASC", "DESC") else "DESC"
        limit_val = structured_intent.get("result_limit")
        if limit_val is not None:
            try:
                intent["limit"] = int(limit_val)
            except (ValueError, TypeError):
                pass

    # 1. Reject unresolved ranking/superlative query - NEVER guess a column!
    is_eval, _ = is_unresolved_evaluative_query(question)
    cand_metrics = get_candidate_metric_columns(columns)
    if is_eval and len(cand_metrics) > 1 and not (structured_intent and structured_intent.get("sorting_and_ranking")):
        raise SqlValidationError(
            "UNRESOLVED_AMBIGUOUS_METRIC",
            "Cannot repair SQL for query with unresolved ranking or performance metric."
        )

    q_lower = question.lower()
    if any(k in q_lower for k in ("top", "best", "worst", "performing", "highest", "lowest", "performer")):
        if not intent.get("order_column") and not intent.get("agg_column"):
            raise SqlValidationError(
                "UNRESOLVED_AMBIGUOUS_METRIC",
                "Cannot repair SQL for query with unresolved ranking or performance metric."
            )

    # 2. Check for missing columns
    if intent.get("missing_column"):
        avail = ", ".join(f"'{c.get('original_name')}'" for c in columns)
        raise SqlValidationError(
            "MISSING_REQUESTED_COLUMN",
            f"The dataset does not contain column '{intent['missing_column']}'. Available columns: {avail}."
        )

    # 3. Attempt bounded AST-based repair on failed_sql
    if failed_sql and failed_sql.strip():
        try:
            parsed = sqlglot.parse_one(failed_sql, read="postgres")
            if isinstance(parsed, exp.Select):
                # Repair LIMIT
                if intent.get("limit"):
                    parsed.set("limit", exp.Limit(expression=exp.Literal.number(intent["limit"])))

                # Repair ORDER BY
                if intent.get("order_column"):
                    ord_col = intent["order_column"]["internal_name"]
                    direction = intent.get("order_direction", "DESC")
                    order_expr = parsed.find(exp.Order)
                    if not order_expr or ord_col.lower() not in {c.name.lower() for c in order_expr.find_all(exp.Column)}:
                        parsed = parsed.order_by(f"{ord_col} {direction}")

                # Repair GROUP BY
                if intent.get("group_by_column"):
                    grp_col = intent["group_by_column"]["internal_name"]
                    group_expr = parsed.find(exp.Group)
                    if not group_expr or grp_col.lower() not in {c.name.lower() for c in group_expr.find_all(exp.Column)}:
                        parsed = parsed.group_by(grp_col)

                repaired_candidate = parsed.sql(dialect="postgres")
                allowed_cols = {c["internal_name"].lower() for c in columns}
                validate_sql_query(repaired_candidate, table_name, allowed_cols)
                validate_sql_semantics(repaired_candidate, question, table_name, columns, structured_intent=structured_intent)
                logger.info(f"Successfully repaired SQL via AST transformation: {repaired_candidate}")
                return repaired_candidate
        except SqlValidationError as ve:
            if ve.error_code in ("UNRESOLVED_AMBIGUOUS_METRIC", "MISSING_REQUESTED_COLUMN"):
                raise
            logger.debug(f"AST candidate failed semantic validation ({ve}); falling back to semantic generation.")
        except Exception as e:
            logger.debug(f"AST manipulation could not repair SQL ({e}); falling back to semantic generation.")

    # 4. Fallback to full semantic generation
    return generate_semantic_sql(
        question=question,
        table_name=table_name,
        columns=columns,
        dataset_name=dataset_name,
        structured_intent=structured_intent,
    )


def validate_sql_semantics(
    candidate_sql: str,
    question: str,
    table_name: str,
    columns_metadata: List[Dict[str, Any]],
    structured_intent: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Validates that the candidate SQL accurately reflects the natural language question's intent:
    - Verifies presence of requested aggregate functions (AVG, SUM, COUNT, MIN, MAX).
    - Verifies that target columns mentioned in the question are referenced in the query.
    - Verifies GROUP BY clauses when grouping is requested.
    - Verifies LIMIT values when top/bottom N is requested.
    - Verifies ORDER BY clauses when ranking is requested.
    - Verifies WHERE filters when filtering conditions are requested.
    - Rejects SQL that queries unrelated columns or omits user-specified operations.
    """
    if not candidate_sql or not candidate_sql.strip():
        raise SqlValidationError("EMPTY_SQL", "Candidate SQL is empty.")

    try:
        parsed = sqlglot.parse_one(candidate_sql, read="postgres")
    except Exception as e:
        raise SqlValidationError("SQL_SYNTAX_ERROR", f"Could not parse SQL for semantic validation: {e}")

    intent = extract_query_intent(question, columns_metadata)
    q_lower = question.lower()

    # 1. Check Missing Column
    if intent["missing_column"]:
        avail = ", ".join(f"'{c.get('original_name')}'" for c in columns_metadata)
        raise SqlValidationError(
            "MISSING_REQUESTED_COLUMN",
            f"The dataset does not contain column '{intent['missing_column']}'. Available columns: {avail}."
        )

    # 2. Check Aggregation Intent
    if intent["aggregation"] == "AVG":
        avgs = list(parsed.find_all(exp.Avg))
        if not avgs:
            target = intent['agg_column']['original_name'] if intent['agg_column'] else 'column'
            raise SqlValidationError(
                "INTENT_MISMATCH_AGGREGATION",
                f"The user question requests an average/mean ('{target}'), but the generated SQL query does not use the AVG() aggregate function."
            )
        # Check target column is in AVG
        if intent["agg_column"]:
            agg_internal = intent["agg_column"]["internal_name"].lower()
            avg_col_names = {
                c.name.lower()
                for avg in avgs
                for c in avg.find_all(exp.Column)
            }
            if agg_internal not in avg_col_names:
                raise SqlValidationError(
                    "INTENT_MISMATCH_COLUMN",
                    f"User requested average of '{intent['agg_column']['original_name']}', but generated SQL does not apply AVG() to column '{agg_internal}'."
                )

    elif intent["aggregation"] == "COUNT":
        counts = list(parsed.find_all(exp.Count))
        if not counts:
            raise SqlValidationError(
                "INTENT_MISMATCH_AGGREGATION",
                "The user question requests counting records/items, but the generated SQL query does not use the COUNT() function."
            )

    elif intent["aggregation"] == "SUM":
        sums = list(parsed.find_all(exp.Sum))
        if not sums:
            target = intent['agg_column']['original_name'] if intent['agg_column'] else 'metric'
            raise SqlValidationError(
                "INTENT_MISMATCH_AGGREGATION",
                f"The user question requests a sum/total of '{target}', but the generated SQL query does not use the SUM() function."
            )

    elif intent["aggregation"] == "MAX":
        maxs = list(parsed.find_all(exp.Max))
        has_desc_order = any(
            isinstance(o, exp.Ordered) and o.args.get("desc")
            for o in parsed.find_all(exp.Ordered)
        )
        if not maxs and not (has_desc_order and parsed.find(exp.Limit)):
            raise SqlValidationError(
                "INTENT_MISMATCH_AGGREGATION",
                "The user question requests the maximum/highest value, but the SQL does not use MAX() or ORDER BY DESC with LIMIT."
            )

    elif intent["aggregation"] == "MIN":
        mins = list(parsed.find_all(exp.Min))
        has_asc_order = any(
            isinstance(o, exp.Ordered) and not o.args.get("desc")
            for o in parsed.find_all(exp.Ordered)
        )
        if not mins and not (has_asc_order and parsed.find(exp.Limit)):
            raise SqlValidationError(
                "INTENT_MISMATCH_AGGREGATION",
                "The user question requests the minimum/lowest value, but the SQL does not use MIN() or ORDER BY ASC with LIMIT."
            )

    # 3. Check Target Column Reference
    # If the user specifically asks about columns (e.g. "What is the average Age?", "What is the GPA and Age..."),
    # the SQL MUST reference those columns.
    referenced_columns = {col.name.lower() for col in parsed.find_all(exp.Column) if col.name != "*"}
    if structured_intent and isinstance(structured_intent, dict):
        req_outs = structured_intent.get("requested_outputs", [])
        for ro in req_outs:
            c = find_column_by_name(ro, columns_metadata)
            if c:
                c_internal = c["internal_name"].lower()
                if c_internal not in referenced_columns:
                    raise SqlValidationError(
                        "INTENT_MISMATCH_COLUMN",
                        f"The question requests output column '{c['original_name']}', but the generated SQL does not project '{c_internal}'."
                    )
    if intent["agg_column"]:
        agg_c = intent["agg_column"]["internal_name"].lower()
        if agg_c not in referenced_columns:
            raise SqlValidationError(
                "INTENT_MISMATCH_COLUMN",
                f"The question inquires about column '{intent['agg_column']['original_name']}', but the generated SQL does not reference '{agg_c}'."
            )
    elif intent.get("target_columns") and not intent.get("aggregation"):
        for t_col in intent["target_columns"]:
            t_c = t_col["internal_name"].lower()
            if t_c not in referenced_columns:
                raise SqlValidationError(
                    "INTENT_MISMATCH_COLUMN",
                    f"The question requests output column '{t_col['original_name']}', but the generated SQL does not project '{t_c}'."
                )

    # 4. Check Grouping
    if intent["group_by_column"]:
        group_expr = parsed.find(exp.Group)
        if not group_expr:
            raise SqlValidationError(
                "INTENT_MISMATCH_GROUPING",
                f"The question asks for results grouped by '{intent['group_by_column']['original_name']}', but the SQL lacks a GROUP BY clause."
            )
        group_cols = {c.name.lower() for c in group_expr.find_all(exp.Column)}
        grp_internal = intent["group_by_column"]["internal_name"].lower()
        if grp_internal not in group_cols:
            raise SqlValidationError(
                "INTENT_MISMATCH_GROUPING",
                f"The GROUP BY clause does not group by requested column '{grp_internal}'."
            )

    # 5. Check Limit
    if intent["limit"]:
        limit_expr = parsed.find(exp.Limit)
        if not limit_expr:
            raise SqlValidationError(
                "INTENT_MISMATCH_LIMIT",
                f"The question requests top {intent['limit']}, but the SQL query does not contain a LIMIT clause."
            )
        try:
            val = int(limit_expr.expression.this)
            if val != intent["limit"]:
                raise SqlValidationError(
                    "INTENT_MISMATCH_LIMIT",
                    f"The question requests top {intent['limit']}, but the SQL query specifies LIMIT {val}."
                )
        except (AttributeError, ValueError):
            pass

    # 5b. Check Order
    if intent.get("order_column"):
        order_expr = parsed.find(exp.Order)
        if not order_expr:
            raise SqlValidationError(
                "INTENT_MISMATCH_ORDER",
                f"The question requests ranking/ordering by '{intent['order_column']['original_name']}', but the SQL lacks an ORDER BY clause."
            )
        ordered_cols = {c.name.lower() for c in order_expr.find_all(exp.Column)}
        ord_internal = intent["order_column"]["internal_name"].lower()
        if ord_internal not in ordered_cols:
            raise SqlValidationError(
                "INTENT_MISMATCH_ORDER",
                f"The ORDER BY clause does not order by requested column '{ord_internal}'."
            )
    elif intent.get("limit") and any(k in q_lower for k in ("top", "best", "worst", "highest", "lowest", "performer")):
        if not parsed.find(exp.Order):
            raise SqlValidationError(
                "INTENT_MISMATCH_ORDER",
                "The question requests a top/ranking result, but the SQL lacks an ORDER BY clause."
            )

    # 6. Check Filters
    if intent["filters"]:
        where_expr = parsed.find(exp.Where)
        if not where_expr:
            f_col = intent["filters"][0]["column"]["original_name"]
            raise SqlValidationError(
                "INTENT_MISMATCH_FILTER",
                f"The question specifies a filter condition on '{f_col}', but the generated SQL lacks a WHERE clause."
            )
        where_cols = {c.name.lower() for c in where_expr.find_all(exp.Column)}
        for f in intent["filters"]:
            f_internal = f["column"]["internal_name"].lower()
            if f_internal not in where_cols:
                raise SqlValidationError(
                    "INTENT_MISMATCH_FILTER",
                    f"The SQL WHERE clause does not filter on requested column '{f_internal}'."
                )

    # 7. Unconstrained SELECT * scan rejection for specific, filtered, or ranking questions
    if any(k in q_lower for k in ("top", "best", "worst", "performing", "highest", "lowest", "older than", "younger than")) or intent.get("primary_target_col"):
        is_select_all = not parsed.find(exp.Where) and not parsed.find(exp.Order) and not parsed.find(exp.Group) and not parsed.find(exp.Anonymous) and not list(parsed.find_all(exp.AggFunc))
        if is_select_all:
            raise SqlValidationError(
                "INTENT_MISMATCH_QUERY",
                "The question requests a specific filtered or ranked result, but the SQL performs an unconstrained table scan without WHERE or ORDER BY."
            )

    # 8. Check for spurious MAX/MIN when query is an Argmax/Argmin record lookup
    is_argmax_lookup = (
        (intent.get("primary_target_col") or intent.get("target_columns")) and intent.get("order_column") and not intent.get("group_by_column")
    ) or (
        bool(structured_intent and isinstance(structured_intent, dict) and structured_intent.get("sorting_and_ranking") and (structured_intent.get("requested_outputs") or structured_intent.get("result_limit")))
    )
    if is_argmax_lookup:
        max_or_min = list(parsed.find_all(exp.Max)) + list(parsed.find_all(exp.Min))
        if max_or_min:
            ord_name = intent["order_column"]["original_name"] if intent.get("order_column") else (structured_intent.get("sorting_and_ranking") if structured_intent else "ranking")
            raise SqlValidationError(
                "INTENT_MISMATCH_AGGREGATION",
                f"The query requests records ordered by '{ord_name}' (Argmax/Argmin lookup), "
                f"not a scalar aggregation MAX()/MIN()."
            )
