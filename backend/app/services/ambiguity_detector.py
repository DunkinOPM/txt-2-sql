"""
Ambiguity Detection, Out-of-Scope Detection, and Schema-Grounded Classification Service.

Detects unresolved evaluative, ranking, and subjective concepts in natural language queries
(e.g., "top performing", "best student", "good performance", "most successful") and checks
whether the dataset schema establishes a clear, singular metric or requires targeted clarification.
Also identifies out-of-scope requests inquiring about foreign entities absent from the schema.
"""

import re
import logging
from typing import Any, Dict, List, Optional, Tuple, Set

from app.schemas.classification import ClassificationResult, ClassificationCategory

logger = logging.getLogger(__name__)

NUMERIC_TYPES: Set[str] = {
    "INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT",
    "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE PRECISION",
    "DOUBLE_PRECISION", "REAL"
}

EVALUATIVE_PATTERNS: List[str] = [
    r"\b(top|best|highest|worst|lowest)[\s-]+(?:(\d+)[\s-]+)?performing\b",
    r"\b(top|best|leading|worst|underperforming)[\s-]+(?:(\d+)[\s-]+)?([a-zA-Z_]+)\b",
    r"\b(good|poor|high|low|great|strong|weak)[\s-]+performance\b",
    r"\b(most|least)[\s-]+(successful|productive|active|valuable|profitable|efficient|effective|popular)\b",
    r"\b(highest|top|leading|best)[\s-]+(?:(\d+)[\s-]+)?achiev(?:ing|er|ers)\b",
    r"\bfind\s+(?:the\s+)?(best|top|worst)\s+([a-zA-Z_]+)\b",
    r"\bwho\s+is\s+(?:the\s+)?(best|top|worst)\s+([a-zA-Z_]+)\b",
    r"\bwhich\s+([a-zA-Z_]+)\s+is\s+(?:the\s+)?(best|top|worst)\b",
]

IDENTIFIER_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?:_id|^id|id$|_key$|^key$|_code$|^code$|_no$|^no$|_num$|^num$|_pk$|_fk$)", re.I),
    re.compile(r"^(ssn|sku|uuid|phone|mobile|zip|postal|row_id|_row_id|year|enrollment_year|admission_year|hire_year|birth_year|dob|date_of_birth)$", re.I),
]

NON_PERFORMANCE_METRIC_PATTERNS: List[re.Pattern] = [
    re.compile(r"^(age|birth_year|birth_date|dob|date_of_birth)$", re.I),
    re.compile(r"^(gender|sex|ethnicity|race|nationality|marital_status|status|active|is_active|flag)$", re.I),
    re.compile(r"^(zip|postal|postal_code|zip_code|lat|latitude|lon|longitude|altitude|elevation)$", re.I),
    re.compile(r"^(phone|mobile|cell|fax|ip|ip_address|port)$", re.I),
    re.compile(r"^(year|month|day|date|quarter|hour|minute|second)$", re.I),
]

METRIC_KEYWORDS: Set[str] = {
    "score", "marks", "grade", "attendance", "rank", "percentage",
    "percent", "rating", "performance", "points", "sales", "revenue", "profit",
    "salary", "wage", "credits", "hours", "amount", "cost", "price", "margin",
    "gpa", "cgpa", "units", "quantity", "volume", "headcount", "discount", "balance"
}

STOP_WORDS: Set[str] = {
    "what", "is", "the", "of", "in", "for", "a", "an", "and", "or",
    "are", "there", "show", "give", "me", "all", "get", "find", "list",
    "tell", "please", "can", "you", "which", "who", "with", "from",
    "table", "data", "dataset", "record", "records", "row", "rows",
    "to", "at", "by", "per", "on", "that", "this", "each", "every"
}


def is_unresolved_evaluative_query(question: str) -> Tuple[bool, Optional[str]]:
    """Checks whether the query contains an unresolved evaluative or ranking concept."""
    q_lower = question.lower()
    for pat in EVALUATIVE_PATTERNS:
        m = re.search(pat, q_lower)
        if m:
            return True, m.group(0).strip()
    return False, None


def is_identifier_column(col: Dict[str, Any]) -> bool:
    """Identifies if a column serves as an entity identifier rather than a performance metric."""
    orig = col.get("original_name", "").lower()
    internal = col.get("internal_name", "").lower()
    clean_orig = re.sub(r"[^a-z0-9]", "", orig)
    clean_int = re.sub(r"[^a-z0-9]", "", internal)

    # If the column name contains explicit metric keywords, it is a metric, not an ID
    if any(k in clean_orig or k in clean_int for k in METRIC_KEYWORDS):
        return False

    for pat in IDENTIFIER_PATTERNS:
        if pat.search(internal) or pat.search(orig) or pat.search(clean_orig):
            return True
    return False


def is_non_evaluative_column(col: Dict[str, Any]) -> bool:
    """Identifies demographic, spatial, or dimensional columns that are not performance measures."""
    orig = col.get("original_name", "").lower().strip()
    internal = col.get("internal_name", "").lower().strip()
    clean_orig = re.sub(r"[^a-z0-9]", "", orig)
    clean_int = re.sub(r"[^a-z0-9]", "", internal)

    # If it contains explicit metric keywords, it is a metric, not demographic
    if any(k in clean_orig or k in clean_int for k in METRIC_KEYWORDS):
        return False

    for pat in NON_PERFORMANCE_METRIC_PATTERNS:
        if pat.search(orig) or pat.search(internal) or pat.search(clean_orig) or pat.search(clean_int):
            return True
    return False


def get_candidate_metric_columns(columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Identifies candidate performance/evaluative metric columns across any arbitrary schema.
    Uses data types and schema evidence to select quantifiable measures and exclude pure IDs
    and demographic attributes.
    """
    candidates = []
    for col in columns:
        if is_identifier_column(col) or is_non_evaluative_column(col):
            continue

        orig = col.get("original_name", "").lower()
        internal = col.get("internal_name", "").lower()
        ctype = col.get("inferred_type", "TEXT").upper()

        is_num = ctype in NUMERIC_TYPES
        has_metric_kw = any(k in internal or k in orig for k in METRIC_KEYWORDS)

        if is_num or has_metric_kw:
            candidates.append(col)
    return candidates


def match_column_in_text(text: str, columns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Checks if a column is explicitly referenced in the given text."""
    t_lower = text.lower()
    t_clean = re.sub(r"[^a-z0-9]", "", t_lower)

    for col in columns:
        orig = col.get("original_name", "").lower().strip()
        internal = col.get("internal_name", "").lower().strip()
        orig_clean = re.sub(r"[^a-z0-9]", "", orig)
        internal_clean = re.sub(r"[^a-z0-9]", "", internal)

        # Exact token match (only if non-empty)
        if orig and re.search(r"\b" + re.escape(orig) + r"\b", t_lower):
            return col

        if internal and re.search(r"\b" + re.escape(internal) + r"\b", t_lower):
            return col

        if len(orig_clean) >= 3 and orig_clean in t_clean:
            return col
        if len(internal_clean) >= 3 and internal_clean in t_clean:
            return col

    return None


def extract_head_noun(phrase: str) -> str:
    """Extracts the principal head noun from a phrase or token."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\s]", "", phrase).strip()
    words = [w for w in cleaned.split() if w.lower() not in STOP_WORDS]
    if not words:
        return ""
    # In English noun phrases, the head noun is usually the final token (e.g., 'five apples' -> 'apples')
    return words[-1].lower()


def detect_out_of_scope_query(
    dataset_name: str,
    schema_summary: List[Dict[str, Any]],
    question: str,
) -> Optional[ClassificationResult]:
    """
    Determines whether a query is asking for entities, domains, or subjects completely
    unrelated to the authorized dataset schema (e.g. asking for 'apples' on a student dataset).
    """
    q_lower = question.lower()

    # 1. Known trivia/world knowledge/general AI requests
    out_of_scope_patterns = [
        r"\b(?:capital of|weather in|recipe for|translate to|tell me a joke|who is the president|who won the world cup)\b",
        r"\b(?:write a poem|sing a song|how to cook|france|germany|paris|tokyo|olympics)\b",
    ]
    for pat in out_of_scope_patterns:
        if re.search(pat, q_lower):
            return ClassificationResult(
                category=ClassificationCategory.OUT_OF_SCOPE,
                confidence=0.98,
                reason=f"The question is completely unrelated to the dataset '{dataset_name}'.",
                missing_fields=[],
                ambiguities=[],
            )

    # 2. Build dataset schema vocabulary
    schema_vocab: Set[str] = set()
    # From dataset name
    for part in re.split(r"[\s_]+", dataset_name.lower()):
        clean_part = re.sub(r"[^a-z0-9]", "", part)
        if len(clean_part) >= 3 and clean_part not in STOP_WORDS:
            schema_vocab.add(clean_part)
            if clean_part.endswith("s"):
                schema_vocab.add(clean_part[:-1])
            else:
                schema_vocab.add(clean_part + "s")

    # From column names
    for col in schema_summary:
        for name_field in ("original_name", "internal_name"):
            val = col.get(name_field, "").lower()
            for part in re.split(r"[\s_]+", val):
                clean_part = re.sub(r"[^a-z0-9]", "", part)
                if len(clean_part) >= 3 and clean_part not in STOP_WORDS:
                    schema_vocab.add(clean_part)
                    if clean_part.endswith("s"):
                        schema_vocab.add(clean_part[:-1])
                    else:
                        schema_vocab.add(clean_part + "s")

    # Generic schema/database terms that are always considered in-domain
    generic_data_nouns = {
        "record", "records", "row", "rows", "entry", "entries", "item", "items",
        "data", "dataset", "table", "value", "values", "result", "results",
        "detail", "details", "all", "everything", "total", "count", "average"
    }

    # 3. Detect entity complement patterns e.g. "name of five apples", "names of apples", "color of orange"
    # Pattern A: "[attribute] of [number?] [foreign_entity]"
    prep_m = re.search(
        r"\b(?:name|names|list|type|types|kind|kinds|count|number|color|colors|photo|photos|price|cost)\s+of\s+(?:the\s+|a\s+|an\s+|some\s+|\d+\s+)?([a-zA-Z_]+)\b",
        q_lower
    )
    if prep_m:
        entity = prep_m.group(1).lower().strip()
        entity_s = entity[:-1] if entity.endswith("s") else entity + "s"
        if (
            len(entity) >= 3
            and entity not in STOP_WORDS
            and entity not in generic_data_nouns
            and entity not in schema_vocab
            and entity_s not in schema_vocab
        ):
            # Check if any other word in the question matches the schema (excluding the attribute word like 'name')
            other_words = [
                w.strip("?,.'\"();: ")
                for w in q_lower.split()
                if w.strip("?,.'\"();: ") not in STOP_WORDS
                and w.strip("?,.'\"();: ") not in ("name", "names", "list", "count", "number")
            ]
            has_other_schema_match = any(
                w in schema_vocab or (w[:-1] if w.endswith("s") else w + "s") in schema_vocab
                for w in other_words
                if len(w) >= 3
            )
            if not has_other_schema_match:
                return ClassificationResult(
                    category=ClassificationCategory.OUT_OF_SCOPE,
                    confidence=0.95,
                    reason=(
                        f"The question inquires about '{entity}', which is completely unrelated to the "
                        f"dataset '{dataset_name}' and absent from its schema."
                    ),
                    missing_fields=[],
                    ambiguities=[],
                )

    # Pattern B: Direct entity queries: e.g. "give me five apples", "show 10 apples", "list apples"
    direct_m = re.search(
        r"\b(?:give me|show|find|list|get|display)\s+(?:the\s+)?(?:(\d+|five|ten|all)\s+)?([a-zA-Z_]+)\b",
        q_lower
    )
    if direct_m:
        entity = direct_m.group(2).lower().strip()
        entity_s = entity[:-1] if entity.endswith("s") else entity + "s"
        if (
            len(entity) >= 3
            and entity not in STOP_WORDS
            and entity not in generic_data_nouns
            and entity not in schema_vocab
            and entity_s not in schema_vocab
        ):
            # Verify no other words match schema
            other_words = [
                w.strip("?,.'\"();: ")
                for w in q_lower.split()
                if w.strip("?,.'\"();: ") not in STOP_WORDS
            ]
            has_other_schema_match = any(
                w in schema_vocab or (w[:-1] if w.endswith("s") else w + "s") in schema_vocab
                for w in other_words
                if len(w) >= 3
            )
            if not has_other_schema_match:
                return ClassificationResult(
                    category=ClassificationCategory.OUT_OF_SCOPE,
                    confidence=0.95,
                    reason=(
                        f"The question inquires about '{entity}', which does not exist in dataset '{dataset_name}'."
                    ),
                    missing_fields=[],
                    ambiguities=[],
                )

    return None


def detect_query_ambiguity_and_classification(
    dataset_name: str,
    schema_summary: List[Dict[str, Any]],
    question: str,
    previous_clarifications: Optional[List[Dict[str, str]]] = None,
) -> Optional[ClassificationResult]:
    """
    Analyzes whether the query is ambiguous, unanswerable, or clear based strictly
    on the available schema columns and previous conversational clarification turns.
    """
    candidate_metrics = get_candidate_metric_columns(schema_summary)

    # 1. Check if ambiguity was already resolved in a prior clarification turn
    if previous_clarifications:
        for turn in previous_clarifications:
            ans = turn.get("answer", "")
            # If user provided a metric answer, mark resolved
            if match_column_in_text(ans, candidate_metrics) or match_column_in_text(question, candidate_metrics):
                logger.info(f"Ambiguity resolved via clarification turn: {ans}")
                return None

    # Also check if the question was rewritten to include a clarification in parentheses e.g. "question (CGPA)"
    paren_match = re.search(r"\(([^)]+)\)$", question)
    if paren_match:
        chosen_option = paren_match.group(1).strip()
        if match_column_in_text(chosen_option, candidate_metrics) or match_column_in_text(chosen_option, schema_summary):
            logger.info(f"Ambiguity resolved via refined query text: {chosen_option}")
            return None

    # 2. Check for unresolved evaluative / ranking queries
    is_eval, concept = is_unresolved_evaluative_query(question)
    if is_eval:
        # Check candidate metrics mentioned in the question
        explicit_metrics = [c for c in candidate_metrics if match_column_in_text(question, [c])]

        # If exactly 1 candidate metric column is named in the question (e.g. "highest GPA", or "GPA of highest performing"),
        # that singular metric reliably resolves the evaluative ranking metric
        if len(explicit_metrics) == 1:
            logger.info(f"Evaluative query '{concept}' resolved by singular explicit metric '{explicit_metrics[0].get('original_name')}'")
            return None
        elif len(explicit_metrics) >= 2:
            # Multiple metrics mentioned without establishing ranking priority: ask clarification
            options = [c["original_name"] for c in explicit_metrics[:4]]
            clean_concept = re.sub(r"\s+", " ", concept).strip()
            return ClassificationResult(
                category=ClassificationCategory.RELEVANT_AMBIGUOUS,
                confidence=0.95,
                reason=(
                    f"The question inquires about '{concept}', but mentions multiple "
                    f"candidate metrics ({', '.join(options)})."
                ),
                missing_fields=[],
                ambiguities=[f"Unresolved ranking metric for '{concept}'"],
                clarification_question=f"Which metric should be used to determine '{clean_concept}'?",
                clarification_options=options,
            )

        # Evaluative concept has NO explicit metric column:
        # Inspect available candidate metrics in the schema
        available_cols_str = ", ".join(f"'{c.get('original_name')}'" for c in schema_summary)

        if len(candidate_metrics) == 0:
            # The dataset lacks any performance or ranking metric!
            return ClassificationResult(
                category=ClassificationCategory.RELEVANT_UNANSWERABLE,
                confidence=0.98,
                reason=(
                    f"The dataset '{dataset_name}' does not contain performance metrics or quantifiable measures "
                    f"to determine '{concept}'. "
                    f"Available columns are: {available_cols_str}."
                ),
                missing_fields=[f"Performance metric for '{concept}'"],
                ambiguities=[],
                clarification_question=None,
                clarification_options=None,
            )

        elif len(candidate_metrics) >= 2:
            # Multiple plausible metrics exist: must ask targeted clarification!
            options = [c["original_name"] for c in candidate_metrics[:4]]
            clean_concept = re.sub(r"\s+", " ", concept).strip()
            return ClassificationResult(
                category=ClassificationCategory.RELEVANT_AMBIGUOUS,
                confidence=0.95,
                reason=(
                    f"The question inquires about '{concept}', but the dataset contains multiple "
                    f"plausible metrics ({', '.join(options)})."
                ),
                missing_fields=[],
                ambiguities=[f"Unresolved ranking metric for '{concept}'"],
                clarification_question=f"Which metric should be used to determine '{clean_concept}'?",
                clarification_options=options,
            )

        else:  # exactly 1 candidate metric
            metric_name = candidate_metrics[0]["original_name"]
            clean_concept = re.sub(r"\s+", " ", concept).strip()
            return ClassificationResult(
                category=ClassificationCategory.RELEVANT_AMBIGUOUS,
                confidence=0.90,
                reason=(
                    f"The question inquires about '{concept}' without specifying a metric. "
                    f"The available metric in the dataset is '{metric_name}'."
                ),
                ambiguities=[f"Unresolved metric for '{concept}'"],
                clarification_question=f"Should '{clean_concept}' be determined by '{metric_name}'?",
                clarification_options=[f"Highest {metric_name}", "Other criteria"],
            )

    return None
