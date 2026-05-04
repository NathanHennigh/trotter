/**
 * src/api/client.js
 * Thin fetch wrapper — automatically injects the Bearer JWT.
 * Framework-agnostic: works in any future frontend that copies src/api/.
 */

import { BASE_URL } from './config';

async function request(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail ?? detail; } catch (_) {}
    throw new Error(detail);
  }

  // 204 No Content
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  get:    (path, token)       => request(path, { token }),
  post:   (path, body, token) => request(path, { method: 'POST', body, token }),
  delete: (path, token)       => request(path, { method: 'DELETE', token }),
};
