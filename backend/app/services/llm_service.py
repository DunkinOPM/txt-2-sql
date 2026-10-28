import time
import re
import json
import logging
from typing import Any, Optional, List
from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.core.config import settings
from app.schemas.classification import (
    ClassificationResult,
    QueryUnderstandingResult,
    ClassificationCategory,
)
from app.services.ambiguity_detector import (
    detect_query_ambiguity_and_classification,
    detect_out_of_scope_query,
    is_unresolved_evaluative_query,
    get_candidate_metric_columns,
    match_column_in_text,
)
from app.services.sql_semantic_validator import (
    generate_semantic_sql,
    repair_semantic_sql,
    extract_query_intent,
    find_column_by_name,
)

logger = logging.getLogger(__name__)

# Regular expressions for stripping SQL comments to de-obfuscate inputs like DROP/**/TABLE
SQL_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
SQL_LINE_COMMENT_RE = re.compile(r"--[^\r\n]*")

# Deterministic patterns for safety & prompt injection.
UNSAFE_SQL_PATTERNS = [
    re.compile(
        r"\b(drop\s+(table|database|schema|view|index|user|role)|"
        r"truncate\s+(table\s+)?\w+|"
        r"delete\s+from|"
        r"insert\s+into|"
        r"update\s+\w+\s+set|"
        r"alter\s+(table|database|schema|system|role|user)|"
        r"create\s+(table|database|schema|role|user)|"
        r"grant\s+\w+|"
        r"revoke\s+\w+)\b",
        re.IGNORECASE
    ),
    re.compile(
        r"(;\s*(drop|delete|truncate|update|insert|alter|create|grant|revoke|copy|execute)\b|"
        r"\bcopy\s+.*?\s+from\s+program|"
        r"\bpg_read_file|"
        r"\bpg_write_file|"
        r"\blo_import|"
        r"\blo_export|"
        r"\bexec\s*\(|"
        r"\bxp_cmdshell|"
        r"\bexecute\s+immediate)",
        re.IGNORECASE
    ),
]

PROMPT_INJECTION_PATTERNS = [
    re.compile(
        r"(ignore\s+(all\s+)?(previous|prior|above)\s+instructions|"
        r"disregard\s+(all\s+)?(previous|prior|system)\s+instructions|"
        r"forget\s+(all\s+)?(prior|previous|above)\s+instructions|"
        r"override\s+(all\s+)?(previous|prior|system)\s+instructions|"
        r"system\s+prompt|"
        r"reveal\s+(the\s+)?(system\s+)?prompt|"
        r"show\s+(the\s+)?system\s+prompt|"
        r"bypass\s+(safety|guardrails)|"
        r"you\s+are\s+now\s+in\s+dan\s+mode|"
        r"developer\s+mode\s+output|"
        r"jailbreak|"
        r"\[system\]|"
        r"<\|im_start\|>|"
        r"role:\s*system|"
        r"<\s*/?\s*(system|instruction|guidelines)\s*>)",
        re.IGNORECASE
    ),
]

# Sensitive column name patterns for secondary schema defense
SENSITIVE_COLUMN_PATTERN = re.compile(
    r"\b(email|phone|mobile|address|salary|tax|ssn|password|secret|credit|token|pin)\b",
    re.IGNORECASE
)


def check_deterministic_safety(question: str) -> Optional[ClassificationResult]:
    """
    Enforces deterministic safety checks before and independent of LLM classification.
    Strips inline and block comments to catch obfuscated keywords (e.g. DROP/**/TABLE),
    mutating SQL statements, and prompt injection attempts.
    """
    deobfuscated = SQL_BLOCK_COMMENT_RE.sub(" ", question)
    deobfuscated = SQL_LINE_COMMENT_RE.sub(" ", deobfuscated)
    q = " ".join(deobfuscated.split()).strip()

    for pattern in UNSAFE_SQL_PATTERNS:
        if pattern.search(q) or pattern.search(question):
            return ClassificationResult(
                category=ClassificationCategory.IMPROPER_OR_UNSAFE,
                confidence=1.0,
                reason="The request contains disallowed destructive or mutating database operations.",
                missing_fields=[],
                ambiguities=[],
                clarification_question=None,
                clarification_options=None,
            )

    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(q) or pattern.search(question):
            return ClassificationResult(
                category=ClassificationCategory.IMPROPER_OR_UNSAFE,
                confidence=1.0,
                reason="The request contains instruction overrides or prompt extraction attempts.",
                missing_fields=[],
                ambiguities=[],
                clarification_question=None,
                clarification_options=None,
            )

    return None


def _format_schema_for_prompt(dataset_name: str, schema_summary: list[dict[str, Any]]) -> str:
    """
    Formats authorized table metadata, column definitions, data types, and privacy-safe sample values.
    Strict privacy guarantees:
    - Never includes database credentials or unrestricted table dumps.
    - Suppresses sample values for any column flagged as sensitive (passwords, emails, SSN, tokens, etc.).
    - Limits sample values to 3 representative non-empty values per column.
    """
    lines = [f"Authorized Dataset: '{dataset_name}'", "Available Columns & Types:"]
    for col in schema_summary:
        orig = col.get("original_name") or "Unnamed"
        internal = col.get("internal_name") or orig.lower()
        itype = col.get("inferred_type", "TEXT")
        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
        samples = col.get("sample_values")

        # Suppress samples if column matches sensitive pattern
        if SENSITIVE_COLUMN_PATTERN.search(orig) or SENSITIVE_COLUMN_PATTERN.search(internal):
            samples = None

        line = f"- '{orig}' (SQL internal name: {internal}, Type: {itype}, {nullable})"
        if samples and isinstance(samples, list) and len(samples) > 0:
            clean_samples = [str(s).strip() for s in samples[:3] if str(s).strip()]
            if clean_samples:
                sample_str = ", ".join(f"'{s}'" for s in clean_samples)
                line += f" [Sample values: {sample_str}]"
        lines.append(line)
    return "\n".join(lines)


# Global hooks for test mocking
_mock_classifier_handler = None
_mock_rewriter_handler = None
_mock_sql_generator_handler = None
_mock_sql_repairer_handler = None
_mock_explanation_handler = None
_mock_suggested_questions_handler = None


def set_mock_suggested_questions(handler):
    global _mock_suggested_questions_handler
    _mock_suggested_questions_handler = handler


def set_mock_classifier(handler):
    global _mock_classifier_handler
    _mock_classifier_handler = handler


def set_mock_rewriter(handler):
    global _mock_rewriter_handler
    _mock_rewriter_handler = handler


def set_mock_sql_generator(handler):
    global _mock_sql_generator_handler
    _mock_sql_generator_handler = handler


def set_mock_sql_repairer(handler):
    global _mock_sql_repairer_handler
    _mock_sql_repairer_handler = handler


def set_mock_explanation(handler):
    global _mock_explanation_handler
    _mock_explanation_handler = handler


def _validate_and_sanitize_gemini_understanding(
    result: QueryUnderstandingResult,
    schema_summary: list[dict[str, Any]],
    dataset_name: str,
    question: str,
) -> QueryUnderstandingResult:
    """
    Enforces deterministic backend verification and sanitization on Gemini's understanding:
    1. Validates referenced columns and requested outputs against actual authorized schema.
    2. Reclassifies to RELEVANT_UNANSWERABLE if user requested non-existent schema columns.
    3. Guarantees non-empty targeted clarification questions and concrete options for RELEVANT_AMBIGUOUS.
    4. Guards against destructive SQL or prompt injection attempts in output fields.
    """
    safety = check_deterministic_safety(question)
    if safety:
        return safety

    # Verify requested outputs and referenced columns against authorized schema
    missing_cols = []
    resolved_outputs = []
    for out in result.requested_outputs:
        out_clean = out.lower().strip("?,.'\"();: ")
        matched_col = find_column_by_name(out_clean, schema_summary)
        if matched_col:
            resolved_outputs.append(matched_col.get("original_name", out))
        else:
            # Check if this output is an aggregate function like COUNT(*) or AVG(...)
            if not re.match(r"^(avg|sum|count|min|max)\b", out_clean, re.I):
                if not any(out_clean == (c.get("original_name") or "").lower() for c in schema_summary):
                    missing_cols.append(out)

    # If Gemini classified as RELEVANT_CLEAR, but requested non-existent columns:
    if result.classification == ClassificationCategory.RELEVANT_CLEAR and missing_cols:
        avail_str = ", ".join(f"'{c.get('original_name')}'" for c in schema_summary)
        missing_str = ", ".join(f"'{m}'" for m in missing_cols)
        return QueryUnderstandingResult(
            classification=ClassificationCategory.RELEVANT_UNANSWERABLE,
            intent_summary=result.intent_summary or f"Inquiry for {missing_str}",
            requested_outputs=resolved_outputs,
            measures=result.measures,
            filters=result.filters,
            grouping=result.grouping,
            sorting_and_ranking=result.sorting_and_ranking,
            result_limit=result.result_limit,
            referenced_columns=result.referenced_columns,
            missing_information=missing_cols,
            reason=f"The dataset '{dataset_name}' does not contain column(s) {missing_str}. Available columns: {avail_str}.",
            confidence=0.95,
        )

    # If Gemini classified as RELEVANT_AMBIGUOUS, guarantee non-empty question and options
    if result.classification == ClassificationCategory.RELEVANT_AMBIGUOUS:
        cand_cols = get_candidate_metric_columns(schema_summary)
        is_eval, _ = is_unresolved_evaluative_query(question)
        if not cand_cols and is_eval:
            avail_str = ", ".join(f"'{c.get('original_name')}'" for c in schema_summary)
            return QueryUnderstandingResult(
                classification=ClassificationCategory.RELEVANT_UNANSWERABLE,
                intent_summary=result.intent_summary or "Inquiry requiring performance metric",
                requested_outputs=result.requested_outputs,
                measures=result.measures,
                filters=result.filters,
                grouping=result.grouping,
                sorting_and_ranking=result.sorting_and_ranking,
                result_limit=result.result_limit,
                referenced_columns=result.referenced_columns,
                missing_information=["performance metric"],
                reason=(
                    f"The question is related to {dataset_name}, but the dataset does not contain "
                    f"any performance metrics or ranking columns. Available fields include: {avail_str}."
                ),
                confidence=0.95,
            )

        clarif_q = (result.clarification_question or "").strip()
        if not clarif_q:
            clarif_q = f"Which metric or column should be used to interpret this question in dataset '{dataset_name}'?"

        raw_opts = [o.strip() for o in (result.clarification_options or []) if o and o.strip()]
        sanitized_opts = []
        for o in raw_opts:
            matched = find_column_by_name(o, schema_summary)
            if matched:
                sanitized_opts.append(matched["original_name"])
            else:
                found_col = None
                for col in schema_summary:
                    orig = col.get("original_name", "")
                    if orig and orig.lower() in o.lower():
                        found_col = orig
                        break
                if found_col:
                    sanitized_opts.append(found_col)
                else:
                    sanitized_opts.append(o)

        opts = list(dict.fromkeys(sanitized_opts))
        if not opts:
            cand_cols = get_candidate_metric_columns(schema_summary)
            opts = [c["original_name"] for c in cand_cols[:4]] if cand_cols else [c["original_name"] for c in schema_summary[:4]]

        return QueryUnderstandingResult(
            classification=ClassificationCategory.RELEVANT_AMBIGUOUS,
            intent_summary=result.intent_summary,
            requested_outputs=result.requested_outputs,
            measures=result.measures,
            filters=result.filters,
            grouping=result.grouping,
            sorting_and_ranking=result.sorting_and_ranking,
            result_limit=result.result_limit,
            referenced_columns=result.referenced_columns,
            missing_information=result.missing_information,
            clarification_question=clarif_q,
            clarification_options=opts,
            reason=result.reason or "The question contains multiple plausible interpretations.",
            confidence=result.confidence,
        )

    return result


def deterministic_classify_query(
    dataset_name: str,
    schema_summary: list[dict[str, Any]],
    question: str,
    previous_clarifications: Optional[list[dict[str, str]]] = None,
) -> QueryUnderstandingResult:
    """
    Deterministic offline/fallback classifier for resilience when Gemini API is rate-limited (HTTP 429),
    in test environments without API keys, or temporarily unavailable.
    Strictly adheres to the 6 classification categories and produces full QueryUnderstandingResult.
    """
    # 1. Safety check
    safety = check_deterministic_safety(question)
    if safety:
        return safety

    # 2. Out of scope detection (foreign entities, trivia, general AI)
    oos = detect_out_of_scope_query(
        dataset_name=dataset_name,
        schema_summary=schema_summary,
        question=question,
    )
    if oos:
        return QueryUnderstandingResult(
            classification=ClassificationCategory.OUT_OF_SCOPE,
            intent_summary="Out-of-scope query",
            reason=oos.reason,
            confidence=0.95,
        )

    # 3. Evaluative ambiguity & metric detection
    ambig = detect_query_ambiguity_and_classification(
        dataset_name=dataset_name,
        schema_summary=schema_summary,
        question=question,
        previous_clarifications=previous_clarifications,
    )
    if ambig:
        return QueryUnderstandingResult(
            classification=ClassificationCategory.RELEVANT_AMBIGUOUS,
            intent_summary=f"Ambiguous query: {ambig.reason}",
            clarification_question=ambig.clarification_question,
            clarification_options=ambig.clarification_options,
            reason=ambig.reason,
            confidence=0.95,
        )

    q_lower = question.lower()
    words = [w.strip("?,.'\"();: ") for w in q_lower.split() if w.strip("?,.'\"();: ")]

    # 4. Gibberish / Nonsensical detection
    if not words:
        return QueryUnderstandingResult(
            classification=ClassificationCategory.NONSENSICAL,
            confidence=0.99,
            reason="Empty query input.",
        )

    vowels = set("aeiouy")
    is_gibberish = False
    if any(w in ("asdfghjkl", "qwerty", "zxcvbnm", "asdf", "qwer", "zxcv", "hjkl") for w in words):
        is_gibberish = True
    else:
        long_words = [w for w in words if len(w) >= 5 and w.isalpha()]
        if long_words and all(not any(ch in vowels for ch in w) for w in long_words):
            is_gibberish = True

    if is_gibberish:
        return QueryUnderstandingResult(
            classification=ClassificationCategory.NONSENSICAL,
            confidence=0.95,
            reason="The question appears to be nonsensical or random characters.",
        )

    # 5. Out of scope patterns
    out_of_scope_patterns = [
        r"\b(capital of|weather in|recipe for|translate to|tell me a joke|who is the president|who won the world cup)\b",
        r"\b(write a poem|sing a song|how to cook|france|germany|paris|tokyo|olympics)\b",
    ]
    if any(re.search(pat, q_lower) for pat in out_of_scope_patterns):
        return QueryUnderstandingResult(
            classification=ClassificationCategory.OUT_OF_SCOPE,
            confidence=0.95,
            reason=f"The question is completely unrelated to the dataset '{dataset_name}'.",
        )

    # Check query intent & missing columns
    intent = extract_query_intent(question, schema_summary)

    # 6. Missing column check
    if intent.get("missing_column"):
        avail = ", ".join(f"'{c.get('original_name')}'" for c in schema_summary)
        return QueryUnderstandingResult(
            classification=ClassificationCategory.RELEVANT_UNANSWERABLE,
            confidence=0.95,
            reason=f"The dataset '{dataset_name}' does not contain column '{intent['missing_column']}'. Available columns: {avail}.",
            missing_information=[intent["missing_column"]],
        )

    has_schema_target = bool(
        intent.get("primary_target_col") or
        intent.get("target_columns") or
        intent.get("agg_column") or
        intent.get("order_column") or
        intent.get("group_by_column") or
        intent.get("filters")
    )

    is_full_table_inquiry = any(
        phrase in q_lower
        for phrase in ("all records", "all rows", "all data", "show all", "list all", "display all", "everything")
    )

    if has_schema_target or is_full_table_inquiry:
        req_outputs = [c["original_name"] for c in intent.get("target_columns", [])]
        measures = [f"{intent['aggregation']}({intent['agg_column']['original_name']})"] if intent.get("aggregation") and intent.get("agg_column") else ([intent["aggregation"]] if intent.get("aggregation") else [])
        sorting = f"{intent['order_column']['internal_name']} {intent.get('order_direction', 'DESC')}" if intent.get("order_column") else None
        limit = intent.get("limit")
        filters = [f"{f['column']['original_name']} {f['op']} {f['value']}" for f in intent.get("filters", [])]
        grouping = [intent["group_by_column"]["original_name"]] if intent.get("group_by_column") else []
        ref_cols = [c["original_name"] for c in schema_summary if match_column_in_text(question, [c])]

        return QueryUnderstandingResult(
            classification=ClassificationCategory.RELEVANT_CLEAR,
            intent_summary=f"Query for {', '.join(req_outputs) if req_outputs else 'records'}",
            requested_outputs=req_outputs,
            measures=measures,
            filters=filters,
            grouping=grouping,
            sorting_and_ranking=sorting,
            result_limit=limit,
            referenced_columns=ref_cols,
            missing_information=[],
            reason="The question is relevant to the dataset schema and clear for SQL translation.",
            confidence=0.95,
        )

    return QueryUnderstandingResult(
        classification=ClassificationCategory.OUT_OF_SCOPE,
        confidence=0.90,
        reason=f"The question does not refer to columns, entities, or operations available in dataset '{dataset_name}'.",
    )


def classify_query_with_gemini(
    dataset_name: str,
    schema_summary: list[dict[str, Any]],
    question: str,
    previous_clarifications: Optional[list[dict[str, str]]] = None,
) -> QueryUnderstandingResult:
    """
    Classifies a natural-language question against an authorized dataset schema
    using Gemini as the PRIMARY natural-language query interpreter with Pydantic structured output.
    """
    # 1. Deterministic safety check (rejects SQL injection / destructive patterns)
    safety_override = check_deterministic_safety(question)
    if safety_override:
        return safety_override

    # 2. If a mock classifier handler is explicitly registered (for testing), honor it directly
    if _mock_classifier_handler is not None:
        try:
            mock_res = _mock_classifier_handler(dataset_name, schema_summary, question, previous_clarifications)
            if isinstance(mock_res, QueryUnderstandingResult):
                return _validate_and_sanitize_gemini_understanding(mock_res, schema_summary, dataset_name, question)
            elif isinstance(mock_res, dict):
                return _validate_and_sanitize_gemini_understanding(QueryUnderstandingResult(**mock_res), schema_summary, dataset_name, question)
            return _validate_and_sanitize_gemini_understanding(mock_res, schema_summary, dataset_name, question)
        except Exception as e:
            logger.error(f"Classification parsing/execution error in mock: {str(e)}")
            return QueryUnderstandingResult(
                classification=ClassificationCategory.NONSENSICAL,
                confidence=0.0,
                reason="The AI classification service encountered an unexpected error. Please try rephrasing your question.",
            )

    api_key = settings.gemini_api_key
    if not api_key or api_key in ("placeholder_key", "dev_placeholder_key"):
        return deterministic_classify_query(
            dataset_name=dataset_name,
            schema_summary=schema_summary,
            question=question,
            previous_clarifications=previous_clarifications,
        )

    # 3. Dedicated Gemini Classification & Structured Intent Understanding Call
    schema_context = _format_schema_for_prompt(dataset_name, schema_summary)

    clarification_context = ""
    if previous_clarifications:
        clarification_context = "\nPrevious Clarification Turns in this conversation:\n" + "\n".join(
            f"- Question asked: '{c.get('question')}' -> User clarified: '{c.get('answer')}'"
            for c in previous_clarifications
        )

    system_instruction = (
        "You are an expert AI natural-language database query interpreter for a PostgreSQL Text-to-SQL system.\n"
        "Your task is to deeply analyze the user's natural language question in the context of the authorized dataset schema.\n"
        "You must determine the exact analytical intent, resolve which schema columns are referenced, identify any ambiguities, "
        "and classify the question into exactly ONE of the 6 categories:\n\n"
        "CATEGORIES:\n"
        "1. RELEVANT_CLEAR: The question is clear, unambiguous, in-scope, and can be directly translated to SQL using available columns.\n"
        "2. RELEVANT_AMBIGUOUS: The question is relevant to the dataset, but contains unresolved evaluative or ranking concepts (such as 'top performing', 'best student', 'good performance', 'most successful'), or multiple plausible interpretations exist without an explicit metric in the question or schema. You MUST provide a targeted clarification_question and 2-4 concrete clarification_options based on available columns.\n"
        "3. RELEVANT_UNANSWERABLE: The question is meaningful and related to the dataset's domain, but one or more required columns, entities, or metrics are absent from the dataset. Specify the missing columns in missing_information and explain the limitation in reason.\n"
        "4. OUT_OF_SCOPE: The question asks about foreign entities, concepts, or domains completely absent from and unrelated to the dataset schema (e.g. asking for 'apples', 'weather', or 'recipe' on a student or employee dataset). Explain clearly in reason.\n"
        "5. NONSENSICAL: The input is gibberish, random keystrokes, or cannot reasonably be understood as a data query.\n"
        "6. IMPROPER_OR_UNSAFE: The question requests destructive database modifications, unauthorized operations, or jailbreaks.\n\n"
        "CRITICAL RULES FOR INTENT UNDERSTANDING:\n"
        "- requested_outputs: List all specific columns or attributes the user wants returned/displayed (e.g. ['gpa', 'age']). Include ALL requested attributes! If the user says 'and give the age too', include 'age'!\n"
        "- measures: List any quantitative aggregations requested (e.g. ['AVG(age)'], ['COUNT(*)']). Do NOT generate aggregations when individual entity record properties are requested!\n"
        "- filters: List any filter conditions (e.g. ['age > 20', 'department = Computer Science']).\n"
        "- grouping: List any grouping columns requested (e.g. ['department']).\n"
        "- sorting_and_ranking: Specify ordering or ranking metric and direction (e.g. 'gpa DESC'). For queries asking for properties of the highest or lowest entity (e.g. 'What is the GPA of the highest performing student and give the age too'), identify the ranking metric from the question/schema (e.g. 'gpa DESC') and set result_limit to 1. Do NOT confuse entity superlatives with scalar MAX/MIN!\n"
        "- result_limit: Specify row limit (e.g. 1 for single entity, 5 for top 5).\n"
        "- referenced_columns: List all schema column names referenced directly or indirectly.\n"
        "- missing_information: List any requested columns or metrics not present in the schema.\n"
    )

    prompt = (
        f"{schema_context}\n"
        f"{clarification_context}\n\n"
        f"User Question: \"{question}\"\n\n"
        "Interpret the user question in the context of the dataset schema and return the structured QueryUnderstandingResult JSON."
    )

    last_exc = None
    for attempt in range(3):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=QueryUnderstandingResult,
                    temperature=0.0,
                ),
            )

            if not response.text:
                raise ValueError("Empty response received from Gemini API.")

            result = QueryUnderstandingResult.model_validate_json(response.text)
            return _validate_and_sanitize_gemini_understanding(
                result=result,
                schema_summary=schema_summary,
                dataset_name=dataset_name,
                question=question,
            )

        except Exception as e:
            last_exc = e
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "spikes in demand" in err_str.lower()) and attempt < 2:
                logger.warning(f"Gemini 503 spike, retrying query understanding (attempt {attempt+1}/3)...")
                time.sleep(2.0)
                continue
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < 2:
                wait_sec = 12.0
                m_delay = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str)
                if m_delay:
                    wait_sec = float(m_delay.group(1)) + 1.0
                logger.warning(f"Gemini 429 rate limit reached, backing off for {wait_sec:.1f}s (attempt {attempt+1}/3)...")
                time.sleep(wait_sec)
                continue
            logger.error(f"Gemini API query understanding failure: {err_str}")
            break

    # Fail safely: return safe failure with clear error explanation, NEVER mark clear!
    return QueryUnderstandingResult(
        classification=ClassificationCategory.NONSENSICAL,
        confidence=0.0,
        reason=f"The AI query understanding service encountered an error ({str(last_exc)}). Please try submitting your question again.",
    )


def rewrite_query_with_gemini(
    original_question: str,
    clarification_question: str,
    user_answer: str,
) -> str:
    """
    Rewrites the original user question into an unambiguous refined question by
    incorporating the user's clarification answer.
    """
    try:
        if _mock_rewriter_handler is not None:
            return _mock_rewriter_handler(original_question, clarification_question, user_answer)

        api_key = settings.gemini_api_key
        if not api_key or api_key == "placeholder_key":
            return f"{original_question} ({user_answer})"

        prompt = (
            f"Original Question: \"{original_question}\"\n"
            f"Clarifying Question: \"{clarification_question}\"\n"
            f"User's Clarification: \"{user_answer}\"\n\n"
            "Combine the original question and the user's clarification into a single, concrete, "
            "unambiguous question ready for SQL translation. Output ONLY the refined question string, nothing else."
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        refined = response.text.strip().strip('"') if response.text else ""
        return refined or f"{original_question} ({user_answer})"
    except Exception as e:
        logger.warning(f"Failed to rewrite query via Gemini: {e}")
        return f"{original_question} ({user_answer})"


def generate_sql_with_gemini(
    dataset_name: str,
    table_name: str,
    columns: list[dict[str, Any]],
    question: str,
    structured_intent: Optional[dict[str, Any] | QueryUnderstandingResult] = None,
) -> str:
    """
    Generates a PostgreSQL SELECT query for the specified question, authorized dataset schema,
    and structured intent representation.
    """
    try:
        if _mock_sql_generator_handler is not None:
            import inspect
            sig = inspect.signature(_mock_sql_generator_handler)
            if len(sig.parameters) >= 5:
                return _mock_sql_generator_handler(dataset_name, table_name, columns, question, structured_intent)
            return _mock_sql_generator_handler(dataset_name, table_name, columns, question)

        api_key = settings.gemini_api_key
        if not api_key or api_key in ("placeholder_key", "dev_placeholder_key"):
            return generate_semantic_sql(
                question=question,
                table_name=table_name,
                columns=columns,
                dataset_name=dataset_name,
                structured_intent=structured_intent,
            )

        col_lines = []
        for c in columns:
            orig = c.get("original_name")
            internal = c.get("internal_name")
            itype = c.get("inferred_type", "TEXT")
            col_lines.append(f"- '{orig}' (Type: {itype}) -> SQL column name: {internal}")

        cols_str = "\n".join(col_lines)

        intent_block = ""
        if structured_intent:
            intent_dict = structured_intent if isinstance(structured_intent, dict) else structured_intent.model_dump()
            req_outs = intent_dict.get("requested_outputs", [])
            measures = intent_dict.get("measures", [])
            filters = intent_dict.get("filters", [])
            grouping = intent_dict.get("grouping", [])
            sorting = intent_dict.get("sorting_and_ranking")
            limit = intent_dict.get("result_limit")
            intent_summary = intent_dict.get("intent_summary", "")

            intent_block = (
                "\nSTRUCTURED INTENT UNDERSTANDING:\n"
                f"- Analytical Goal: {intent_summary}\n"
                f"- Requested Output Columns: {', '.join(req_outs) if req_outs else 'All applicable'}\n"
                f"- Measures/Aggregations: {', '.join(measures) if measures else 'None'}\n"
                f"- Filters: {', '.join(filters) if filters else 'None'}\n"
                f"- Grouping: {', '.join(grouping) if grouping else 'None'}\n"
                f"- Sorting/Ranking: {sorting or 'None'}\n"
                f"- Row Limit: {limit if limit is not None else 'None'}\n"
            )

        system_instruction = (
            "You are an expert Text-to-SQL generation assistant specializing in PostgreSQL.\n"
            "Your task is to generate a single, accurate, semantically correct PostgreSQL SELECT query that directly answers the user's question adhering to the validated structured intent.\n"
            "CRITICAL RULES:\n"
            f"1. You MUST query strictly from the authorized table: uploaded_data.{table_name}\n"
            "2. Use ONLY the provided internal SQL column names in SELECT, WHERE, ORDER BY, GROUP BY, and HAVING.\n"
            "3. Respect PostgreSQL data types: perform aggregations (AVG, SUM, MIN, MAX) only on compatible numeric/date types.\n"
            "4. Preserve the user's intended operation and structured intent:\n"
            "   - If requested output columns are specified (e.g. GPA and Age), project ALL of them in the SELECT clause: SELECT <col1>, <col2>.\n"
            "   - If the user asks for average/mean, use AVG(column).\n"
            "   - If the user asks for count/number of records, use COUNT(*).\n"
            "   - If the user asks for total/sum, use SUM(column).\n"
            "   - If the user asks for maximum/highest scalar value, use MAX(column) or ORDER BY column DESC LIMIT 1.\n"
            "   - If the question asks for properties/columns of the record with the highest or lowest metric (e.g. 'What is the age of the highest scoring student?', 'What is the GPA of the highest performing student and give the age too'), perform an Argmax/Argmin: SELECT <col1>, <col2> FROM uploaded_data.table ORDER BY <metric> DESC LIMIT 1. Include ALL requested output columns in SELECT. NEVER calculate MAX() or scalar aggregations for entity queries!\n"
            "   - If the question asks for grouping ('by <col>', 'per <col>'), include that column in SELECT and GROUP BY.\n"
            "   - If the question asks for top N or specifies a limit, use ORDER BY and LIMIT N.\n"
            "   - If the question has filters ('older than 20', 'in Department X'), use appropriate WHERE clauses with type-safe comparisons (e.g., ILIKE or LOWER(col) = LOWER('val') for text).\n"
            "5. Exactly one SELECT statement is allowed. Do NOT generate multiple statements.\n"
            "6. NEVER generate mutations (INSERT, UPDATE, DELETE, MERGE) or DDL (DROP, ALTER, CREATE).\n"
            "7. NEVER fall back to 'SELECT * FROM table' or selecting arbitrary columns when intent cannot be satisfied.\n"
            "8. Output ONLY the raw PostgreSQL SELECT statement. Do NOT include markdown code fences (```sql) or comments."
        )

        prompt = (
            f"Dataset Name: '{dataset_name}'\n"
            f"Authorized Target Table: uploaded_data.{table_name}\n"
            "Available Columns in this table:\n"
            f"{cols_str}\n"
            f"{intent_block}\n"
            f"User Question: \"{question}\"\n\n"
            "Write the PostgreSQL query that answers this question adhering to the structured intent. Output ONLY the raw SQL query:"
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
            ),
        )

        sql_text = response.text.strip() if response.text else ""
        # Strip any markdown code fences if present
        sql_text = re.sub(r"^```(?:sql)?\s*", "", sql_text, flags=re.IGNORECASE)
        sql_text = re.sub(r"\s*```$", "", sql_text)
        return sql_text.strip()

    except Exception as e:
        logger.warning(f"Error generating SQL with Gemini ({e}); falling back to deterministic semantic generator.")
        return generate_semantic_sql(
            question=question,
            table_name=table_name,
            columns=columns,
            dataset_name=dataset_name,
            structured_intent=structured_intent,
        )


def repair_sql_with_gemini(
    dataset_name: str,
    table_name: str,
    columns: list[dict[str, Any]],
    question: str,
    failed_sql: str,
    error_message: str,
    attempt: int,
    structured_intent: Optional[dict[str, Any] | QueryUnderstandingResult] = None,
) -> str:
    """
    Prompts Gemini to repair a candidate SQL query that failed AST validation or database execution.
    """
    try:
        if _mock_sql_repairer_handler is not None:
            import inspect
            sig = inspect.signature(_mock_sql_repairer_handler)
            if len(sig.parameters) >= 8:
                return _mock_sql_repairer_handler(dataset_name, table_name, columns, question, failed_sql, error_message, attempt, structured_intent)
            return _mock_sql_repairer_handler(dataset_name, table_name, columns, question, failed_sql, error_message, attempt)

        api_key = settings.gemini_api_key
        if not api_key or api_key in ("placeholder_key", "dev_placeholder_key"):
            return repair_semantic_sql(
                question=question,
                table_name=table_name,
                columns=columns,
                failed_sql=failed_sql,
                error_message=error_message,
                dataset_name=dataset_name,
                structured_intent=structured_intent,
            )

        col_lines = [
            f"- '{c.get('original_name')}' -> SQL column: {c.get('internal_name')} ({c.get('inferred_type')})"
            for c in columns
        ]
        cols_str = "\n".join(col_lines)

        intent_block = ""
        if structured_intent:
            intent_dict = structured_intent if isinstance(structured_intent, dict) else structured_intent.model_dump()
            req_outs = intent_dict.get("requested_outputs", [])
            sorting = intent_dict.get("sorting_and_ranking")
            limit = intent_dict.get("result_limit")
            intent_block = f"\nSTRUCTURED INTENT:\n- Outputs: {', '.join(req_outs)}\n- Sorting: {sorting}\n- Limit: {limit}\n"

        system_instruction = (
            "You are an expert SQL repair assistant for PostgreSQL.\n"
            "A previously generated SQL query failed AST validation, database execution, or semantic verification.\n"
            "Your task is to repair the query so that it satisfies PostgreSQL syntax, passes security constraints, "
            "and strictly answers the user's original question with the correct aggregations, filters, or columns.\n"
            f"CRITICAL: You MUST query strictly from uploaded_data.{table_name}.\n"
            "Output ONLY the corrected raw SQL statement without markdown fences or comments."
        )

        prompt = (
            f"User Question: \"{question}\"\n"
            f"Target Table: uploaded_data.{table_name}\n"
            "Authorized Columns:\n"
            f"{cols_str}\n"
            f"{intent_block}\n"
            f"Failed SQL:\n{failed_sql}\n\n"
            f"Error Message:\n{error_message}\n\n"
            f"Repair Attempt: {attempt} of 2.\n"
            "Correct the SQL query to resolve this error. Output ONLY the raw SQL:"
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
            ),
        )

        sql_text = response.text.strip() if response.text else ""
        sql_text = re.sub(r"^```(?:sql)?\s*", "", sql_text, flags=re.IGNORECASE)
        sql_text = re.sub(r"\s*```$", "", sql_text)
        return sql_text.strip()

    except Exception as e:
        logger.warning(f"Error repairing SQL with Gemini ({e}); falling back to deterministic semantic repair.")
        return repair_semantic_sql(
            question=question,
            table_name=table_name,
            columns=columns,
            failed_sql=failed_sql,
            error_message=error_message,
            dataset_name=dataset_name,
            structured_intent=structured_intent,
        )


def generate_explanation_with_gemini(
    question: str,
    generated_sql: str,
    row_count: int,
) -> str:
    """
    Generates a concise, user-friendly 1-2 sentence explanation of the executed query and results.
    """
    try:
        if _mock_explanation_handler is not None:
            return _mock_explanation_handler(question, generated_sql, row_count)

        api_key = settings.gemini_api_key
        if not api_key or api_key == "placeholder_key":
            return f"Retrieved {row_count} matching record(s) based on your query."

        prompt = (
            f"Question: \"{question}\"\n"
            f"Executed SQL: \"{generated_sql}\"\n"
            f"Records Retrieved: {row_count}\n\n"
            "Provide a concise, helpful 1-2 sentence natural language explanation of the results "
            "and what filters/calculations were applied. Do not include raw code or jargon."
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        explanation = response.text.strip() if response.text else ""
        return explanation or f"Retrieved {row_count} matching record(s) based on your query."

    except Exception as e:
        logger.warning(f"Error generating explanation with Gemini: {e}")
        return f"Retrieved {row_count} matching record(s) based on your query."
def generate_suggested_questions_with_gemini(
    dataset_name: str,
    columns: list[dict[str, Any]],
) -> list[str]:
    """
    Generates 3-4 natural language analytical questions grounded ONLY in the dataset's schema.
    Under no circumstances are raw rows, credentials, or sensitive sample values passed to Gemini.
    """



    def build_heuristic_questions() -> list[str]:
        questions = [f"What is the total number of records in {dataset_name}?"]
        numeric_cols = [
            c["original_name"] for c in columns
            if c.get("inferred_type") in ("INTEGER", "BIGINT", "NUMERIC", "FLOAT", "DOUBLE_PRECISION")
        ]
        text_cols = [
            c["original_name"] for c in columns
            if c.get("inferred_type") in ("TEXT", "VARCHAR")
        ]
        date_cols = [
            c["original_name"] for c in columns
            if c.get("inferred_type") in ("DATE", "TIMESTAMP", "TIMESTAMPTZ")
        ]

        if numeric_cols:
            questions.append(f"What is the highest and lowest {numeric_cols[0]}?")
        if text_cols:
            questions.append(f"Show the breakdown of records by {text_cols[0]}.")
        if date_cols:
            questions.append(f"What is the earliest and latest {date_cols[0]}?")
        elif len(numeric_cols) > 1:
            questions.append(f"What is the average {numeric_cols[1]}?")
        elif len(text_cols) > 1:
            questions.append(f"List the distinct values of {text_cols[1]}.")

        return questions[:4]

    if _mock_suggested_questions_handler is not None:
        try:
            return _mock_suggested_questions_handler(dataset_name, columns)
        except Exception as e:
            logger.warning(f"Error in mock suggested questions handler: {e}")
            return build_heuristic_questions()

    try:
        api_key = settings.gemini_api_key
        if not api_key or api_key == "placeholder_key":
            return build_heuristic_questions()

        cols_str = "\n".join(
            f"- {c.get('original_name')} ({c.get('inferred_type')})"
            for c in columns
        )
        system_instruction = (
            "You are a data assistant suggesting natural language questions for a dataset. "
            "Suggest 3 to 4 diverse, concise, interesting questions that can be answered using ONLY "
            "the provided column names and data types. Do NOT assume any unlisted columns. "
            "Return ONLY a JSON array of strings, for example: [\"Question 1?\", \"Question 2?\"]"
        )
        prompt = (
            f"Dataset Name: '{dataset_name}'\n"
            f"Available Schema Columns:\n{cols_str}\n\n"
            "Return 3 to 4 natural language questions as a JSON list of strings:"
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3,
            ),
        )
        if not response.text:
            return build_heuristic_questions()

        cleaned = re.sub(r"^```(?:json)?\s*", "", response.text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed) and parsed:
            return parsed[:4]
        return build_heuristic_questions()

    except Exception as e:
        logger.warning(f"Error generating suggested questions with Gemini: {e}")
        return build_heuristic_questions()
