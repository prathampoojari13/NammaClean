import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, TOKEN_STORAGE_KEY } from './src/api/client.ts';

// Simple mock Storage implementing standard Web Storage interface
class MockStorage {
  constructor() {
    this.store = new Map();
  }
  getItem(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  }
  setItem(key, value) {
    this.store.set(key, String(value));
  }
  removeItem(key) {
    this.store.delete(key);
  }
  clear() {
    this.store.clear();
  }
}

// Polyfill globalThis.localStorage for test isolation
const originalLocalStorage = globalThis.localStorage;
const mockStorage = new MockStorage();
globalThis.localStorage = mockStorage;

test('1. No token attached when localStorage has no stored token', () => {
  mockStorage.clear();
  const client = new ApiClient('http://localhost:8000/api/v1');

  assert.equal(client.getToken(), null);
  const headers = client.getHeaders();
  assert.equal(headers.get('Authorization'), null);
  assert.equal(headers.get('Content-Type'), 'application/json');
});

test('2. Stored token is automatically recovered after a simulated page refresh', () => {
  mockStorage.clear();
  const testToken = 'simulated-refreshed-citizen-jwt-token';
  mockStorage.setItem(TOKEN_STORAGE_KEY, testToken);

  // Instantiate new client instance (simulates fresh module/page load)
  const client = new ApiClient('http://localhost:8000/api/v1');

  assert.equal(client.getToken(), testToken);
  const headers = client.getHeaders();
  assert.equal(headers.get('Authorization'), `Bearer ${testToken}`);
});

test('3. Replaced token updates immediately without stale cached token', () => {
  mockStorage.clear();
  mockStorage.setItem(TOKEN_STORAGE_KEY, 'initial-token-123');

  const client = new ApiClient('http://localhost:8000/api/v1');
  assert.equal(client.getHeaders().get('Authorization'), 'Bearer initial-token-123');

  // Token is replaced in storage (e.g. login switch or refreshed token)
  mockStorage.setItem(TOKEN_STORAGE_KEY, 'new-token-456');
  assert.equal(client.getHeaders().get('Authorization'), 'Bearer new-token-456');
});

test('4. Removed token clears authorization header without retaining stale credentials', () => {
  mockStorage.clear();
  mockStorage.setItem(TOKEN_STORAGE_KEY, 'logout-test-token');

  const client = new ApiClient('http://localhost:8000/api/v1');
  assert.equal(client.getHeaders().get('Authorization'), 'Bearer logout-test-token');

  // User logs out (token removed from storage)
  mockStorage.removeItem(TOKEN_STORAGE_KEY);
  assert.equal(client.getToken(), null);
  assert.equal(client.getHeaders().get('Authorization'), null);

  // Explicit setToken(null) also clears
  client.setToken('manual-token');
  assert.equal(client.getHeaders().get('Authorization'), 'Bearer manual-token');
  client.setToken(null);
  assert.equal(client.getHeaders().get('Authorization'), null);
});

test('5. FormData request preserves boundary without forcing application/json', () => {
  mockStorage.clear();
  mockStorage.setItem(TOKEN_STORAGE_KEY, 'valid-token');
  const client = new ApiClient('http://localhost:8000/api/v1');

  const formData = new FormData();
  formData.append('file', 'test-content');

  const headers = client.getHeaders({}, formData);
  assert.equal(headers.has('Content-Type'), false, 'Content-Type must not be forced on FormData');
  assert.equal(headers.get('Authorization'), 'Bearer valid-token', 'Bearer token must still attach');
});

test('6. Standard JSON request sets Content-Type: application/json', () => {
  const client = new ApiClient('http://localhost:8000/api/v1');
  const headers = client.getHeaders({}, JSON.stringify({ description: 'test' }));

  assert.equal(headers.get('Content-Type'), 'application/json');
});
