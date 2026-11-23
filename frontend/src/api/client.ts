import type { ApiError } from '../types/index.ts';

/**
 * NammaClean API Client
 * Configured with environment-based base URL targeting FastAPI backend.
 */
const API_BASE_URL =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) ||
  'http://localhost:8000/api/v1';

export const TOKEN_STORAGE_KEY = 'nammaclean.access_token';

const getStorage = (): Storage | null => {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage;
    }
    if (typeof localStorage !== 'undefined') {
      return localStorage;
    }
  } catch {
    return null;
  }
  return null;
};

export class ApiClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  setToken(token: string | null): void {
    this.token = token;
    const storage = getStorage();
    if (storage) {
      try {
        if (token) {
          storage.setItem(TOKEN_STORAGE_KEY, token);
        } else {
          storage.removeItem(TOKEN_STORAGE_KEY);
        }
      } catch {
        // Ignore storage errors in restricted contexts
      }
    }
  }

  logout(): void {
    this.setToken(null);
    const storage = getStorage();
    if (storage) {
      try {
        storage.removeItem('nammaclean.user_role');
        storage.removeItem('nammaclean.user_email');
      } catch {
        // Ignore storage errors in restricted contexts
      }
    }
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('nammaclean:logout'));
    }
  }

  getToken(): string | null {
    const storage = getStorage();
    if (storage) {
      try {
        const stored = storage.getItem(TOKEN_STORAGE_KEY);
        if (stored) {
          this.token = stored;
          return stored;
        } else if (this.token) {
          // Stored token was removed; do not retain stale in-memory token
          this.token = null;
          return null;
        }
      } catch {
        // Fallback to in-memory token if storage is restricted
      }
    }
    return this.token;
  }

  getHeaders(extraHeaders: HeadersInit = {}, body?: BodyInit | null): Headers {
    const headers = new Headers(extraHeaders);
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    if (!headers.has('Content-Type') && !isFormData) {
      headers.set('Content-Type', 'application/json');
    }
    const activeToken = this.getToken();
    if (activeToken && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${activeToken}`);
    }
    return headers;
  }

  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    const url = `${this.baseUrl}${cleanEndpoint}`;

    const config: RequestInit = {
      ...options,
      headers: this.getHeaders(options.headers || {}, options.body),
    };

    try {
      const response = await fetch(url, config);

      if (!response.ok) {
        if (response.status === 401) {
          // Automatic 401 interception: clear invalid / expired tokens
          this.setToken(null);
          const storage = getStorage();
          if (storage) {
            try {
              storage.removeItem('nammaclean.user_role');
              storage.removeItem('nammaclean.user_email');
            } catch {
              // Ignore storage errors in restricted contexts
            }
          }
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('nammaclean:unauthorized'));
          }
        }
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

  postForm<T>(endpoint: string, formData: FormData, headers?: HeadersInit): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: formData,
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
