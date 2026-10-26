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
