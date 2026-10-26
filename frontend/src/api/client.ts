import {
  HealthResponse,
  DatasetSummary,
  DatasetSchema,
  DatasetPreview,
  DatasetDeleteResult,
  QueryResponse,
  QueryHistoryListResponse,
  SuggestedQuestionsResponse,
} from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const DEFAULT_USER_ID = 'default_user';

class ApiClient {
  private baseUrl: string;
  private currentUserId: string = DEFAULT_USER_ID;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  public setUserId(userId: string) {
    this.currentUserId = userId;
  }

  public getUserId(): string {
    return this.currentUserId;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = new Headers(options.headers || {});

    // Ensure session identity header is attached
    if (!headers.has('X-User-ID')) {
      headers.set('X-User-ID', this.currentUserId);
    }

    // Default to JSON unless sending FormData
    if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData.message) {
          errorMessage = errorData.message;
        } else if (errorData.detail) {
          errorMessage = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
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

  // Queries (Phase 3 & 4)
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

  public async executeQuery(queryId: string): Promise<QueryResponse> {
    return this.request<QueryResponse>(`/api/queries/${queryId}/execute`, {
      method: 'POST',
    });
  }

  public async getQuery(queryId: string): Promise<QueryResponse> {
    return this.request<QueryResponse>(`/api/queries/${queryId}`);
  }

  public async getQueries(params?: {
    datasetId?: string;
    status?: string;
    category?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }): Promise<QueryHistoryListResponse> {
    const qp = new URLSearchParams();
    if (params?.datasetId) qp.append('dataset_id', params.datasetId);
    if (params?.status) qp.append('status', params.status);
    if (params?.category) qp.append('category', params.category);
    if (params?.search) qp.append('search', params.search);
    if (params?.limit !== undefined) qp.append('limit', params.limit.toString());
    if (params?.offset !== undefined) qp.append('offset', params.offset.toString());

    const qs = qp.toString() ? `?${qp.toString()}` : '';
    return this.request<QueryHistoryListResponse>(`/api/queries${qs}`);
  }

  public async getSuggestedQuestions(datasetId: string): Promise<SuggestedQuestionsResponse> {
    return this.request<SuggestedQuestionsResponse>(`/api/datasets/${datasetId}/suggested-questions`);
  }

  public getExportUrl(queryId: string): string {
    return `${this.baseUrl}/api/queries/${queryId}/export`;
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
