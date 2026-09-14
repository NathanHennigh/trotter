import { Platform } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import * as Crypto from 'expo-crypto';

const NATIVE_CALLBACK = 'trotterv2://oauthredirect';
const PENDING_WEB_KEY = 'trotter.oauth.pending';
const SESSION_TIMEOUT = 10 * 60 * 1000;
let activeSession: Promise<string> | undefined;
let sessionSequence = 0;

export class GoogleSignInCanceled extends Error {
  constructor() { super('Sign-in canceled.'); this.name = 'GoogleSignInCanceled'; }
}

export function getOAuthRedirectUri() {
  if (Platform.OS !== 'web') return NATIVE_CALLBACK;
  const origin = browserLocation()?.origin;
  if (!origin) throw new Error('Sign-in requires a browser window.');
  return `${origin}/oauthredirect`;
}

// A token parameter alone never makes an unrelated URL an auth callback.
export function readOAuthCallbackToken(url: string, expectedRedirect: string) {
  const parsed = new URL(url);
  const expected = new URL(expectedRedirect);
  if (parsed.protocol !== expected.protocol || parsed.host !== expected.host
      || parsed.pathname !== expected.pathname || parsed.username || parsed.password) {
    throw new Error('This sign-in link does not belong to Trotter. Please try again.');
  }
  for (const [key, value] of expected.searchParams) {
    if (parsed.searchParams.getAll(key).length !== 1 || parsed.searchParams.get(key) !== value) {
      throw new Error('This sign-in link belongs to a different attempt. Please try again.');
    }
  }
  const fragment = new URLSearchParams(parsed.hash.slice(1));
  const tokens = [...parsed.searchParams.getAll('token'), ...fragment.getAll('token')];
  if (parsed.searchParams.has('error') || fragment.has('error')) throw new GoogleSignInCanceled();
  if (tokens.length !== 1 || !tokens[0] || /\s/.test(tokens[0])) {
    throw new Error('Google did not return a valid sign-in. Please try again.');
  }
  return tokens[0];
}

export function requestGoogleAuthToken(apiBaseUrl: string): Promise<string> {
  if (Platform.OS === 'web') return openGoogleSession(apiBaseUrl);
  if (activeSession) return activeSession;
  const sequence = ++sessionSequence;
  activeSession = openGoogleSession(apiBaseUrl).then(token => {
    if (sequence !== sessionSequence) throw new GoogleSignInCanceled();
    return token;
  }).finally(() => { if (sequence === sessionSequence) activeSession = undefined; });
  return activeSession;
}

async function openGoogleSession(apiBaseUrl: string) {
  const redirect = getOAuthRedirectUri();
  if (Platform.OS === 'web') {
    const storage = webSessionStorage();
    if (!storage) throw new Error('Allow session storage in this browser to sign in.');
    // The existing backend web redirect is an exact registered URL.
    storage.setItem(PENDING_WEB_KEY, JSON.stringify({ redirect, createdAt: Date.now() }));
    browserLocation()!.assign(`${apiBaseUrl}/auth/google/start?app_redirect_uri=${encodeURIComponent(redirect)}`);
    return new Promise<never>(() => undefined);
  }
  // The backend signs and preserves this exact redirect URI in OAuth state.
  const expected = `${redirect}?attempt=${Crypto.randomUUID()}`;
  const startUrl = `${apiBaseUrl}/auth/google/start?app_redirect_uri=${encodeURIComponent(expected)}`;
  const result = await WebBrowser.openAuthSessionAsync(startUrl, redirect, { preferEphemeralSession: true });
  if (result.type !== 'success') throw new GoogleSignInCanceled();
  return readOAuthCallbackToken(result.url, expected);
}

export function consumeWebOAuthCallback(): string | undefined {
  if (Platform.OS !== 'web') return undefined;
  const location = browserLocation();
  if (!location?.href) return undefined;
  const callbackUrl = location.href;
  const parsed = new URL(callbackUrl);
  const expected = new URL(getOAuthRedirectUri());
  if (parsed.origin !== expected.origin || parsed.pathname !== expected.pathname) return undefined;
  const storage = webSessionStorage();
  const raw = storage?.getItem(PENDING_WEB_KEY);
  storage?.removeItem(PENDING_WEB_KEY);
  // Erase bearer tokens even when rejecting an unsolicited callback.
  (globalThis as { history?: History }).history?.replaceState({}, '', '/');
  if (!raw) throw new Error('Start sign-in from Trotter to connect your account.');
  const pending = JSON.parse(raw) as { redirect?: string; createdAt?: number };
  if (pending.redirect !== expected.href || !pending.createdAt
      || Date.now() - pending.createdAt > SESSION_TIMEOUT || pending.createdAt > Date.now()) {
    throw new Error('This sign-in attempt expired. Please try again.');
  }
  return readOAuthCallbackToken(callbackUrl, expected.href);
}

export function cancelGoogleAuthSession() {
  sessionSequence += 1;
  activeSession = undefined;
  if (Platform.OS === 'web') webSessionStorage()?.removeItem(PENDING_WEB_KEY);
  else {
    try { WebBrowser.dismissAuthSession(); } catch { /* Android uses its custom tab session result. */ }
  }
}

function browserLocation() { return (globalThis as { location?: Location }).location; }
function webSessionStorage() {
  try { return (globalThis as { sessionStorage?: Storage }).sessionStorage; }
  catch { return undefined; }
}
