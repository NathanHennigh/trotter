import { requestGoogleAuthToken } from './googleAuth';
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
  const token = await requestGoogleAuthToken(getApiBaseUrl());
  storeAuthToken(token);
  return getMe(token);
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
