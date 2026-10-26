import {
  HealthResponse,
  DatasetSummary,
  DatasetSchema,
  DatasetPreview,
  DatasetDeleteResult,
  QueryResponse,
} from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = new Headers(options.headers || {});

    // Only set application/json if body is not FormData
    if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }

    // Include development user header for local development session context
    if (!headers.has('X-User-ID')) {
      headers.set('X-User-ID', 'default_user');
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let errorMessage = `HTTP error ${response.status}: ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData && errorData.message) {
          errorMessage = errorData.message;
        } else if (errorData && errorData.detail) {
          if (typeof errorData.detail === 'string') {
            errorMessage = errorData.detail;
          } else if (errorData.detail.message) {
            errorMessage = errorData.detail.message;
          }
        }
      } catch {
        // Fallback to generic message
      }
      throw new Error(errorMessage);
    }

    return response.json();
  }

  // Health
  public async getHealth(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/api/health');
  }

  // Datasets
  public async uploadDataset(file: File): Promise<DatasetSummary> {
    const formData = new FormData();
    formData.append('file', file);
    return this.request<DatasetSummary>('/api/datasets', {
      method: 'POST',
      body: formData,
    });
  }

  public async listDatasets(): Promise<DatasetSummary[]> {
    return this.request<DatasetSummary[]>('/api/datasets');
  }

  public async getDataset(datasetId: string): Promise<DatasetSummary> {
    return this.request<DatasetSummary>(`/api/datasets/${datasetId}`);
  }

  public async getDatasetSchema(datasetId: string): Promise<DatasetSchema> {
    return this.request<DatasetSchema>(`/api/datasets/${datasetId}/schema`);
  }

  public async getDatasetPreview(datasetId: string, limit: number = 20): Promise<DatasetPreview> {
    return this.request<DatasetPreview>(`/api/datasets/${datasetId}/preview?limit=${limit}`);
  }

  public async deleteDataset(datasetId: string): Promise<DatasetDeleteResult> {
    return this.request<DatasetDeleteResult>(`/api/datasets/${datasetId}`, {
      method: 'DELETE',
    });
  }

  // Queries (Phase 3)
  public async createQuery(datasetId: string, question: string): Promise<QueryResponse> {
    return this.request<QueryResponse>('/api/queries', {
      method: 'POST',
      body: JSON.stringify({ dataset_id: datasetId, question }),
    });
  }

  public async submitClarification(
    queryId: string,
    selectedOption?: string,
    freeTextAnswer?: string
  ): Promise<QueryResponse> {
    return this.request<QueryResponse>(`/api/queries/${queryId}/clarifications`, {
      method: 'POST',
      body: JSON.stringify({
        selected_option: selectedOption || null,
        free_text_answer: freeTextAnswer || null,
      }),
    });
  }

  public async getQuery(queryId: string): Promise<QueryResponse> {
    return this.request<QueryResponse>(`/api/queries/${queryId}`);
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
