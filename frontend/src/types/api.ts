export interface HealthResponse {
  status: 'healthy' | 'degraded';
  database: string;
  readonly_database: string;
  version: string;
  environment: string;
}

export interface ApiError {
  error_code: string;
  message: string;
  request_id?: string;
  details?: Record<string, unknown>;
}

export interface DatasetColumn {
  id: string;
  dataset_id: string;
  ordinal_position: number;
  original_name: string;
  internal_name: string;
  inferred_type: string;
  nullable: boolean;
  sample_values?: string[] | number[] | boolean[] | null;
  created_at: string;
}

export interface DatasetSummary {
  id: string;
  owner_id: string;
  display_name: string;
  original_filename: string;
  file_format: 'csv' | 'xlsx';
  status: 'uploading' | 'importing' | 'ready' | 'failed' | 'deleting';
  row_count: number;
  column_count: number;
  created_at: string;
  updated_at: string;
  error_code?: string | null;
  error_message?: string | null;
}

export interface DatasetSchema {
  dataset_id: string;
  display_name: string;
  table_name: string;
  row_count: number;
  column_count: number;
  columns: DatasetColumn[];
}

export interface DatasetPreview {
  dataset_id: string;
  display_name: string;
  columns: string[];
  internal_columns: string[];
  column_types: Record<string, string>;
  rows: Record<string, any>[];
  total_preview_rows: number;
  total_dataset_rows: number;
}

export interface DatasetDeleteResult {
  dataset_id: string;
  display_name: string;
  message: string;
  deleted: boolean;
}

export interface QueryTurn {
  id: string;
  turn_number: number;
  role: 'user' | 'assistant' | 'system';
  turn_type: 'question' | 'clarification' | 'clarification_answer' | 'status' | 'explanation';
  content: string;
  clarification_options?: string[] | null;
  created_at: string;
}

export interface QueryResponse {
  id: string;
  dataset_id: string;
  original_question: string;
  refined_question?: string | null;
  category?: 'RELEVANT_CLEAR' | 'RELEVANT_AMBIGUOUS' | 'RELEVANT_UNANSWERABLE' | 'OUT_OF_SCOPE' | 'NONSENSICAL' | 'IMPROPER_OR_UNSAFE' | null;
  status: 'classifying' | 'awaiting_clarification' | 'ready_for_sql' | 'generating_sql' | 'validating_sql' | 'executing' | 'completed' | 'rejected' | 'failed';
  assistant_message: string;
  clarification_question?: string | null;
  clarification_options?: string[] | null;
  generated_sql?: string | null;
  explanation?: string | null;
  columns?: string[] | null;
  rows?: Record<string, any>[] | null;
  result_row_count?: number | null;
  execution_duration_ms?: number | null;
  turns: QueryTurn[];
  created_at: string;
  updated_at: string;
  error_code?: string | null;
  error_message?: string | null;
}
export interface QueryHistoryItem {
  id: string;
  dataset_id: string;
  dataset_name: string;
  original_question: string;
  refined_question?: string | null;
  category?: 'RELEVANT_CLEAR' | 'RELEVANT_AMBIGUOUS' | 'RELEVANT_UNANSWERABLE' | 'OUT_OF_SCOPE' | 'NONSENSICAL' | 'IMPROPER_OR_UNSAFE' | null;
  status: 'classifying' | 'awaiting_clarification' | 'ready_for_sql' | 'generating_sql' | 'validating_sql' | 'executing' | 'completed' | 'rejected' | 'failed';
  result_row_count?: number | null;
  execution_duration_ms?: number | null;
  error_code?: string | null;
  created_at: string;
  updated_at: string;
}

export interface QueryHistoryListResponse {
  items: QueryHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SuggestedQuestionsResponse {
  dataset_id: string;
  dataset_name: string;
  questions: string[];
}


export interface User {
  id: string;
  email: string;
  username: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface RegisterPayload {
  email: string;
  username: string;
  password: string;
}

export interface LoginPayload {
  username_or_email: string;
  password: string;
}
