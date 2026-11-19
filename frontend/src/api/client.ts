import { ApiError } from '../types';

/**
 * NammaClean API Client
 * Configured with environment-based base URL targeting FastAPI backend.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export class ApiClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  setToken(token: string | null): void {
    this.token = token;
  }

  getToken(): string | null {
    return this.token;
  }

  private getHeaders(extraHeaders: HeadersInit = {}): Headers {
    const headers = new Headers(extraHeaders);
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    if (this.token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${this.token}`);
    }
    return headers;
  }

  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    const url = `${this.baseUrl}${cleanEndpoint}`;

    const config: RequestInit = {
      ...options,
      headers: this.getHeaders(options.headers || {}),
    };

    try {
      const response = await fetch(url, config);

      if (!response.ok) {
        let errorData: ApiError;
        try {
          errorData = await response.json();
        } catch {
          errorData = { detail: response.statusText || 'Unknown network error' };
        }
        errorData.status = response.status;
        throw errorData;
      }

      // Handle 204 No Content
      if (response.status === 204) {
        return {} as T;
      }

      return (await response.json()) as T;
    } catch (err: unknown) {
      if ((err as ApiError).detail) {
        throw err;
      }
      throw {
        detail: (err as Error).message || 'Failed to connect to NammaClean backend server.',
        status: 0,
      } as ApiError;
    }
  }

  get<T>(endpoint: string, optionsOrHeaders?: RequestInit | HeadersInit): Promise<T> {
    if (optionsOrHeaders && ('headers' in optionsOrHeaders || 'signal' in optionsOrHeaders || 'cache' in optionsOrHeaders)) {
      return this.request<T>(endpoint, { method: 'GET', ...(optionsOrHeaders as RequestInit) });
    }
    return this.request<T>(endpoint, { method: 'GET', headers: optionsOrHeaders as HeadersInit });
  }

  post<T>(endpoint: string, data?: unknown, headers?: HeadersInit): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: data !== undefined ? JSON.stringify(data) : undefined,
      headers,
    });
  }

  put<T>(endpoint: string, data?: unknown, headers?: HeadersInit): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: data !== undefined ? JSON.stringify(data) : undefined,
      headers,
    });
  }

  delete<T>(endpoint: string, headers?: HeadersInit): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE', headers });
  }
}

export const apiClient = new ApiClient();
