import { Linking, Platform } from 'react-native';
import { getApiBaseUrl, getStoredToken, storeAuthToken } from './travelTrips';

export type ScanJobStatus = {
  job_id: string;
  state: string;
  scanned_count: number;
  parsed_count: number;
  segment_count: number;
  started_at?: string | null;
  updated_at?: string | null;
  error_message?: string | null;
};

export type QueryComparisonStatus = {
  status: string;
  v1_count: number;
  v2_count: number;
  v3_count: number;
  both: number;
  only_in_v1: number;
  only_in_v2: number;
  v1_v3_delta: number;
};

export type UnparsedCandidateList = {
  total: number;
  candidates: Array<{
    message_id: number;
    provider_msg_id: string;
    from_email?: string | null;
    subject?: string | null;
    status: string;
    parse_version: number;
    parse_error?: string | null;
    created_at?: string | null;
  }>;
};

export type UserInfo = {
  user_id: number;
  email: string;
  name?: string | null;
};

export async function signInWithGoogle() {
  const redirectUri = getOAuthRedirectUri();
  const startUrl = `${getApiBaseUrl()}/auth/google/start?app_redirect_uri=${encodeURIComponent(redirectUri)}`;
  if (Platform.OS === 'web') {
    const browser = globalThis as typeof globalThis & { location?: { assign: (url: string) => void } };
    if (!browser.location) throw new Error('Web sign-in requires a browser location.');
    browser.location.assign(startUrl);
    return new Promise<never>(() => undefined);
  }
  const callbackUrl = await openExternalAuthSession(startUrl, redirectUri);
  const token = readQueryParam(callbackUrl, 'token');
  if (!token) {
    throw new Error('Google sign-in completed, but no app token was returned.');
  }

  storeAuthToken(token);
  return getMe(token);
}

function getOAuthRedirectUri() {
  if (Platform.OS !== 'web') return 'trotterv2://oauthredirect';
  const browser = globalThis as typeof globalThis & { location?: { origin?: string } };
  if (!browser.location?.origin) throw new Error('Web sign-in requires a browser origin.');
  return `${browser.location.origin}/oauthredirect`;
}

function openExternalAuthSession(startUrl: string, redirectUri: string) {
  return new Promise<string>((resolve, reject) => {
    let settled = false;
    let subscription: { remove: () => void } | undefined;
    const timeout = setTimeout(() => finish(undefined, new Error('Google sign-in timed out before Trotter received a token.')), 10 * 60 * 1000);

    const finish = (url?: string, error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      subscription?.remove();
      if (error) reject(error);
      else resolve(url ?? '');
    };

    subscription = Linking.addEventListener('url', ({ url }) => {
      if (url.startsWith(redirectUri) || readQueryParam(url, 'token')) finish(url);
    });

    Linking.openURL(startUrl).catch((error) => {
      finish(undefined, error instanceof Error ? error : new Error(String(error)));
    });
  });
}

function readQueryParam(url: string, key: string) {
  try {
    return new URL(url).searchParams.get(key) ?? undefined;
  } catch {
    const match = new RegExp(`[?&]${key}=([^&]+)`).exec(url);
    return match ? decodeURIComponent(match[1]) : undefined;
  }
}

export async function getMe(token = getStoredToken()) {
  if (!token) throw new Error('No auth token. Sign in with Google first.');
  const response = await fetch(`${getApiBaseUrl()}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Profile failed: ${response.status}`));
  return data as UserInfo;
}

export async function requestDevToken() {
  const response = await fetch(`${getApiBaseUrl()}/auth/dev-token`);
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Dev token failed: ${response.status}`));
  if (!data.access_token) throw new Error('Dev token response did not include access_token.');
  storeAuthToken(String(data.access_token));
  return data as { access_token: string; email: string; name?: string | null; user_id: number };
}

export async function startGmailImport() {
  const response = await authFetch('/ingest/gmail/import', { method: 'POST' });
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Import failed: ${response.status}`));
  return data as { job_id: string };
}

export async function getJobStatus(jobId: string) {
  const response = await authFetch(`/ingest/jobs/${jobId}`);
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Job status failed: ${response.status}`));
  return data as ScanJobStatus;
}

export async function runQueryComparison() {
  const response = await authFetch('/ingest/test-queries');
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Query comparison failed: ${response.status}`));
  return data as QueryComparisonStatus;
}

export async function listUnparsedCandidates(limit = 25) {
  const response = await authFetch(`/ingest/unparsed-candidates?limit=${limit}`);
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Unparsed candidates failed: ${response.status}`));
  return data as UnparsedCandidateList;
}

async function authFetch(path: string, init?: RequestInit) {
  const token = getStoredToken();
  if (!token) throw new Error('No auth token. Use Dev Token or pass EXPO_PUBLIC_TROTTER_AUTH_TOKEN.');
  return fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
  });
}

async function readJson(response: Response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function readError(data: unknown, fallback: string) {
  if (data && typeof data === 'object' && 'detail' in data) return String((data as { detail: unknown }).detail);
  return fallback;
}
