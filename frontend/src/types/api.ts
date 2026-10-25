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

