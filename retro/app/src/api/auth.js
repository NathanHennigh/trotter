/**
 * src/api/auth.js
 */
import { api } from './client';
import { BASE_URL } from './config';

/** Validate a stored JWT — throws if expired/invalid. */
export async function getMe(token) {
  return api.get('/auth/me', token);
}

/**
 * Fetch a real JWT for the dev@localhost test user.
 * Only works when backend DEV_MODE=true.
 */
export async function getDevToken() {
  return api.get('/auth/dev-token');
}

/**
 * Build the URL that opens Google sign-in via the backend web flow.
 * @param {string} appRedirectUri — the deep link the backend will redirect to
 */
export function buildGoogleStartUrl(appRedirectUri) {
  return `${BASE_URL}/auth/google/start?app_redirect_uri=${encodeURIComponent(appRedirectUri)}`;
}
