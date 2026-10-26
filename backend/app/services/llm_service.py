import re
import json
import logging
from typing import Any, Optional, List
from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.core.config import settings
from app.schemas.classification import ClassificationResult, ClassificationCategory

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
    Formats minimal authorized column metadata and non-sensitive sample values for the prompt.
    Strict privacy guarantees:
    - Never includes uploaded rows or dataset tables.
    - Never includes database credentials or internal physical table names.
    - Uses original user-facing column names only.
    - Filters out sample values for any column flagged as sensitive.
    """
    lines = [f"Dataset: '{dataset_name}'", "Available Columns:"]
    for col in schema_summary:
        col_name = col.get("original_name") or "Unnamed"
        col_type = col.get("inferred_type", "TEXT")
        samples = col.get("sample_values")

        # Suppress samples if column matches sensitive pattern
        if SENSITIVE_COLUMN_PATTERN.search(col_name):
            samples = None

        line = f"- {col_name} ({col_type})"
        if samples and isinstance(samples, list) and len(samples) > 0:
            sample_str = ", ".join(f"'{s}'" for s in samples[:4])
            line += f" [Sample values: {sample_str}]"
        lines.append(line)
    return "\n".join(lines)


# Global hooks for test mocking
_mock_classifier_handler = None
_mock_rewriter_handler = None
_mock_sql_generator_handler = None
_mock_sql_repairer_handler = None
_mock_explanation_handler = None


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


def classify_query_with_gemini(
    dataset_name: str,
    schema_summary: list[dict[str, Any]],
    question: str,
    previous_clarifications: Optional[list[dict[str, str]]] = None,
) -> ClassificationResult:
    """
    Classifies a natural-language question against an authorized dataset schema
    using Gemini with Pydantic structured output validation.
    """
    safety_override = check_deterministic_safety(question)
    if safety_override:
        return safety_override

    try:
        if _mock_classifier_handler is not None:
            return _mock_classifier_handler(dataset_name, schema_summary, question, previous_clarifications)

        schema_context = _format_schema_for_prompt(dataset_name, schema_summary)

        clarification_context = ""
        if previous_clarifications:
            clarification_context = "\nPrevious Clarification Turns in this conversation:\n" + "\n".join(
                f"- Question asked: '{c.get('question')}' -> User clarified: '{c.get('answer')}'"
                for c in previous_clarifications
            )

        system_instruction = (
            "You are an ambiguity-aware database query classification assistant for a Text-to-SQL system.\n"
            "Your task is to analyze the user's natural language question in the context of the provided dataset schema.\n"
            "Classify the question into exactly ONE of the following categories:\n"
            "1. RELEVANT_CLEAR: The question is clear, unambiguous, in scope, and can be directly translated to SQL using available columns.\n"
            "2. RELEVANT_AMBIGUOUS: The question is relevant to the dataset, but has multiple plausible interpretations (e.g. 'top students' could mean by CGPA or attendance; 'recent sales' has no timeframe). Provide a targeted clarification_question and 2-4 concrete clarification_options.\n"
            "3. RELEVANT_UNANSWERABLE: The question is meaningful and related to the domain of the data, but one or more required columns or metrics are absent from the dataset. Specify the missing fields in missing_fields and explain the limitation.\n"
            "4. OUT_OF_SCOPE: The question is completely unrelated to the domain represented by the dataset (e.g., asking about world geography or recipes when looking at a college admissions dataset).\n"
            "5. NONSENSICAL: The input is gibberish, random keystrokes, or cannot reasonably be understood as a query.\n"
            "6. IMPROPER_OR_UNSAFE: The question requests destructive database modifications, unauthorized operations, or jailbreaks.\n\n"
            "CRITICAL RULES:\n"
            "- Do NOT assume or invent columns that are not in the schema.\n"
            "- If a metric or column is ambiguous, you MUST classify as RELEVANT_AMBIGUOUS and provide clarification_question and options.\n"
            "- If a requested column does not exist, classify as RELEVANT_UNANSWERABLE.\n"
        )

        prompt = (
            f"{schema_context}\n"
            f"{clarification_context}\n\n"
            f"User Question: \"{question}\"\n\n"
            "Classify the question and return the structured result."
        )

        api_key = settings.gemini_api_key
        if not api_key or api_key == "placeholder_key":
            return ClassificationResult(
                category=ClassificationCategory.RELEVANT_CLEAR,
                confidence=0.8,
                reason="Defaulting to RELEVANT_CLEAR (Gemini API key not configured in environment).",
                missing_fields=[],
                ambiguities=[],
                clarification_question=None,
                clarification_options=None,
            )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=ClassificationResult,
                temperature=0.0,
            ),
        )

        if not response.text:
            raise ValueError("Empty response received from Gemini API.")

        result = ClassificationResult.model_validate_json(response.text)
        return result

    except APIError as e:
        logger.error(f"Gemini API Provider Error: {str(e)}")
        return ClassificationResult(
            category=ClassificationCategory.NONSENSICAL,
            confidence=0.0,
            reason="The AI classification service encountered a provider error. Please try rephrasing your question.",
            missing_fields=[],
            ambiguities=[],
        )
    except Exception as e:
        logger.error(f"Classification parsing/execution error: {str(e)}")
        return ClassificationResult(
            category=ClassificationCategory.NONSENSICAL,
            confidence=0.0,
            reason=f"Failed to process query classification: {str(e)}",
            missing_fields=[],
            ambiguities=[],
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
            model="gemini-2.5-flash",
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
) -> str:
    """
    Generates a PostgreSQL SELECT query for the specified question and authorized dataset schema.
    """
    try:
        if _mock_sql_generator_handler is not None:
            return _mock_sql_generator_handler(dataset_name, table_name, columns, question)

        api_key = settings.gemini_api_key
        if not api_key or api_key == "placeholder_key":
            # Fallback SQL for placeholder dev environment
            first_col = columns[0]["internal_name"] if columns else "*"
            return f"SELECT {first_col} FROM uploaded_data.{table_name} LIMIT 10"

        col_lines = []
        for c in columns:
            orig = c.get("original_name")
            internal = c.get("internal_name")
            itype = c.get("inferred_type", "TEXT")
            col_lines.append(f"- '{orig}' (Type: {itype}) -> SQL column name: {internal}")

        cols_str = "\n".join(col_lines)

        system_instruction = (
            "You are a specialized Text-to-SQL generation assistant.\n"
            "Your task is to write a single, clean PostgreSQL SELECT query that accurately answers the user's question.\n"
            "CRITICAL RULES:\n"
            f"1. You MUST query from the table: uploaded_data.{table_name}\n"
            "2. Use ONLY the listed internal SQL column names in SELECT, WHERE, ORDER BY, GROUP BY.\n"
            "3. Exactly one SELECT statement is allowed. Do NOT generate multiple statements.\n"
            "4. NEVER generate mutations (INSERT, UPDATE, DELETE, MERGE) or DDL (DROP, ALTER, CREATE).\n"
            "5. Do NOT include comments (-- or /* */) or markdown formatting. Output raw SQL only."
        )

        prompt = (
            f"Dataset Name: '{dataset_name}'\n"
            f"Authorized Target Table: uploaded_data.{table_name}\n"
            "Available Columns in this table:\n"
            f"{cols_str}\n\n"
            f"User Question: \"{question}\"\n\n"
            "Write the PostgreSQL query that answers this question. Output ONLY the raw SQL query:"
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
        logger.error(f"Error generating SQL with Gemini: {str(e)}")
        raise


def repair_sql_with_gemini(
    dataset_name: str,
    table_name: str,
    columns: list[dict[str, Any]],
    question: str,
    failed_sql: str,
    error_message: str,
    attempt: int,
) -> str:
    """
    Prompts Gemini to repair a candidate SQL query that failed AST validation or database execution.
    """
    try:
        if _mock_sql_repairer_handler is not None:
            return _mock_sql_repairer_handler(dataset_name, table_name, columns, question, failed_sql, error_message, attempt)

        api_key = settings.gemini_api_key
        if not api_key or api_key == "placeholder_key":
            return failed_sql

        col_lines = [
            f"- '{c.get('original_name')}' -> SQL column: {c.get('internal_name')} ({c.get('inferred_type')})"
            for c in columns
        ]
        cols_str = "\n".join(col_lines)

        system_instruction = (
            "You are a SQL repair assistant. A previously generated SQL query failed validation or execution.\n"
            "Your task is to fix the query so that it successfully parses and executes on PostgreSQL.\n"
            f"You MUST query strictly from uploaded_data.{table_name}.\n"
            "Output ONLY the corrected raw SQL statement without markdown fences."
        )

        prompt = (
            f"User Question: \"{question}\"\n"
            f"Target Table: uploaded_data.{table_name}\n"
            "Authorized Columns:\n"
            f"{cols_str}\n\n"
            f"Failed SQL:\n{failed_sql}\n\n"
            f"Error Message:\n{error_message}\n\n"
            f"Repair Attempt: {attempt} of 2.\n"
            "Correct the SQL query to resolve this error. Output ONLY the raw SQL:"
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
        logger.error(f"Error repairing SQL with Gemini: {str(e)}")
        raise


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
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        explanation = response.text.strip() if response.text else ""
        return explanation or f"Retrieved {row_count} matching record(s) based on your query."

    except Exception as e:
        logger.warning(f"Error generating explanation with Gemini: {e}")
        return f"Retrieved {row_count} matching record(s) based on your query."
