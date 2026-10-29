import { Platform } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import * as Crypto from 'expo-crypto';

const NATIVE_CALLBACK = 'trotterv2://oauthredirect';
const PENDING_WEB_KEY = 'trotter.oauth.pending';
const SESSION_TIMEOUT = 10 * 60 * 1000;
let activeSession: Promise<string> | undefined;
let sessionSequence = 0;
let cancelGmailSession: (() => void) | undefined;
let cancelReauthentication: (() => void) | undefined;

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
  const error = parsed.searchParams.get('error') || fragment.get('error');
  if (error === 'access_denied') throw new GoogleSignInCanceled();
  if (error === 'reauth_wrong_account') throw new Error('Choose the account you currently use for Trotter. Nothing has been changed.');
  if (error) throw new Error('Google sign-in could not be completed. Please try again.');
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
  // The backend signs and preserves this exact redirect URI in OAuth state.
  const expected = `${redirect}?attempt=${Crypto.randomUUID()}`;
  if (Platform.OS === 'web') {
    const storage = webSessionStorage();
    if (!storage) throw new Error('Allow session storage in this browser to sign in.');
    storage.setItem(PENDING_WEB_KEY, JSON.stringify({ redirect: expected, createdAt: Date.now() }));
    browserLocation()!.assign(`${apiBaseUrl}/auth/google/start?app_redirect_uri=${encodeURIComponent(expected)}`);
    return new Promise<never>(() => undefined);
  }
  const startUrl = `${apiBaseUrl}/auth/google/start?app_redirect_uri=${encodeURIComponent(expected)}`;
  const result = await WebBrowser.openAuthSessionAsync(startUrl, redirect, { preferEphemeralSession: true });
  if (result.type !== 'success') throw new GoogleSignInCanceled();
  return readOAuthCallbackToken(result.url, expected);
}

export function consumeWebOAuthCallback(): string | undefined {
  if (Platform.OS !== 'web') return undefined;
  if (completeWebGmailCallback()) return undefined;
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
  let pending: { redirect?: string; createdAt?: number }, attempt: URL;
  try {
    pending = JSON.parse(raw);
    attempt = new URL(pending.redirect ?? '');
  } catch { throw new Error('This sign-in attempt expired. Please try again.'); }
  if (attempt.origin !== expected.origin || attempt.pathname !== expected.pathname || attempt.username || attempt.password || attempt.hash
      || [...attempt.searchParams.keys()].length !== 1 || !attempt.searchParams.get('attempt')
      || typeof pending.createdAt !== 'number' || !Number.isFinite(pending.createdAt)
      || Date.now() - pending.createdAt > SESSION_TIMEOUT || pending.createdAt > Date.now()) {
    throw new Error('This sign-in attempt expired. Please try again.');
  }
  return readOAuthCallbackToken(callbackUrl, attempt.href);
}

export function cancelGoogleAuthSession() {
  sessionSequence += 1;
  activeSession = undefined;
  cancelGmailSession?.();
  cancelReauthentication?.();
  if (Platform.OS === 'web') webSessionStorage()?.removeItem(PENDING_WEB_KEY);
  else {
    try { WebBrowser.dismissAuthSession(); } catch { /* Android uses its custom tab session result. */ }
  }
}

export class GmailConnectionCanceled extends Error {
  constructor() { super('Gmail connection canceled.'); this.name = 'GmailConnectionCanceled'; }
}

// Gmail consent never supplies or replaces the app's login token. A popup keeps
// the existing browser tab (including any unsaved planner edits) mounted.
export async function requestGmailConnection(prepare: (redirect: string) => Promise<string>) {
  if (cancelGmailSession) throw new Error('A Gmail connection is already open.');
  const redirect = getOAuthRedirectUri();
  const expected = `${redirect}?flow=gmail&attempt=${Crypto.randomUUID()}`;
  if (Platform.OS !== 'web') {
    let canceled = false;
    let cancel!: () => void;
    const cancellation = new Promise<never>((_, reject) => {
      cancel = () => { canceled = true; try { WebBrowser.dismissAuthSession(); } catch { /* Android custom tab may close separately. */ } reject(new GmailConnectionCanceled()); };
    });
    cancelGmailSession = cancel;
    try {
      await Promise.race([cancellation, (async () => {
        const start = await prepare(expected);
        if (canceled) throw new GmailConnectionCanceled();
        const result = await WebBrowser.openAuthSessionAsync(start, redirect, { preferEphemeralSession: true });
        if (canceled || result.type !== 'success') throw new GmailConnectionCanceled();
        readGmailCallback(result.url, expected);
      })()]);
    } finally { if (cancelGmailSession === cancel) cancelGmailSession = undefined; }
    return;
  }
  const browser = (globalThis as { window?: Window }).window;
  // Open synchronously from the tap, before preparing the authenticated URL.
  const popup = browser?.open('about:blank', '_blank', 'popup,width=500,height=680');
  if (!browser || !popup) throw new Error('Allow pop-ups for Trotter, then try connecting Gmail again.');
  await new Promise<void>((resolve, reject) => {
    let finished = false;
    const finish = (error?: unknown) => {
      if (finished) return;
      finished = true;
      browser.removeEventListener('message', onMessage);
      clearInterval(closed); clearTimeout(timeout);
      cancelGmailSession = undefined;
      try { popup.close(); } catch { /* Already closed. */ }
      if (error) reject(error); else resolve();
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== browser.location.origin || event.source !== popup
          || event.data?.type !== 'trotter.gmail.callback' || typeof event.data.url !== 'string') return;
      let callback: URL;
      try { callback = new URL(event.data.url); } catch { return; }
      if (callback.searchParams.get('attempt') !== new URL(expected).searchParams.get('attempt')) return;
      try { readGmailCallback(event.data.url, expected); finish(); } catch (error) { finish(error); }
    };
    browser.addEventListener('message', onMessage);
    const closed = setInterval(() => { if (popup.closed) finish(new GmailConnectionCanceled()); }, 500);
    const timeout = setTimeout(() => finish(new Error('Gmail connection expired. Please try again.')), SESSION_TIMEOUT);
    cancelGmailSession = () => finish(new GmailConnectionCanceled());
    void prepare(expected).then(url => { if (!finished) popup.location.replace(url); }).catch(finish);
  });
}

export function readGmailCallback(url: string, expectedRedirect: string) {
  const parsed = new URL(url), expected = new URL(expectedRedirect);
  if (parsed.origin !== expected.origin || parsed.protocol !== expected.protocol || parsed.host !== expected.host
      || parsed.pathname !== expected.pathname || parsed.username || parsed.password
      || [...expected.searchParams].some(([key, value]) => parsed.searchParams.getAll(key).length !== 1 || parsed.searchParams.get(key) !== value)) {
    throw new Error('This Gmail connection belongs to a different attempt. Please try again.');
  }
  const fragment = new URLSearchParams(parsed.hash.slice(1));
  const error = parsed.searchParams.get('error') || fragment.get('error');
  if (error === 'access_denied') throw new GmailConnectionCanceled();
  if (error) throw new Error(error === 'gmail_wrong_account'
    ? 'This Google account belongs to a different Trotter account. Choose the one linked to this account, or sign in to that Trotter account first.'
    : error === 'gmail_permission_required' ? 'Allow read-only Gmail access to import your flight confirmations.'
      : error === 'gmail_refresh_required' ? 'Gmail needs permission to stay connected. Please connect again.'
        : 'Gmail was not connected. Please try again.');
  const connected = [...parsed.searchParams.getAll('gmail'), ...fragment.getAll('gmail')];
  if (connected.length !== 1 || connected[0] !== 'connected') throw new Error('Gmail connection could not be confirmed. Please try again.');
}

export function completeWebGmailCallback() {
  if (Platform.OS !== 'web') return false;
  const browser = (globalThis as { window?: Window }).window;
  const location = browserLocation();
  if (!browser || !location) return false;
  const parsed = new URL(location.href);
  const flow = parsed.searchParams.get('flow');
  if (parsed.origin !== location.origin || parsed.pathname !== '/oauthredirect' || !['gmail', 'reauth'].includes(flow ?? '')) return false;
  // Only return the result to this same-origin opener. The parent validates its
  // exact popup reference, unique attempt, endpoint and success marker.
  browser.opener?.postMessage({ type: flow === 'reauth' ? 'trotter.reauth.callback' : 'trotter.gmail.callback', url: location.href }, location.origin);
  if (flow === 'reauth') browser.history.replaceState({}, '', '/oauthredirect?flow=reauth');
  return true;
}

/** A bound verification flow returns a fresh token without replacing the active app account. */
export async function requestGoogleReauthentication(prepare: (redirect: string) => Promise<string>) {
  if (cancelReauthentication) throw new Error('An account verification is already open.');
  const redirect = getOAuthRedirectUri();
  const expected = `${redirect}?flow=reauth&attempt=${Crypto.randomUUID()}`;
  let cancel!: () => void;
  if (Platform.OS !== 'web') {
    let canceled = false;
    const cancellation = new Promise<never>((_, reject) => {
      cancel = () => { canceled = true; try { WebBrowser.dismissAuthSession(); } catch { /* Already closed. */ } reject(new GoogleSignInCanceled()); };
    });
    cancelReauthentication = cancel;
    try {
      return await Promise.race([cancellation, (async () => {
        const url = await prepare(expected);
        if (canceled) throw new GoogleSignInCanceled();
        const result = await WebBrowser.openAuthSessionAsync(url, redirect, { preferEphemeralSession: true });
        if (canceled || result.type !== 'success') throw new GoogleSignInCanceled();
        return readOAuthCallbackToken(result.url, expected);
      })()]);
    } finally { if (cancelReauthentication === cancel) cancelReauthentication = undefined; }
  }
  const browser = (globalThis as { window?: Window }).window;
  // Synchronous opening preserves the user's tap through the authenticated server request.
  const popup = browser?.open('about:blank', '_blank', 'popup,width=500,height=680');
  if (!browser || !popup) throw new Error('Allow pop-ups for Trotter, then try again.');
  return new Promise<string>((resolve, reject) => {
    let finished = false;
    const finish = (token?: string, error?: unknown) => {
      if (finished) return;
      finished = true; browser.removeEventListener('message', onMessage);
      clearInterval(closed); clearTimeout(timeout);
      if (cancelReauthentication === cancel) cancelReauthentication = undefined;
      try { popup.close(); } catch { /* Already closed. */ }
      if (error) reject(error); else resolve(token!);
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== browser.location.origin || event.source !== popup
          || event.data?.type !== 'trotter.reauth.callback' || typeof event.data.url !== 'string') return;
      let callback: URL;
      try { callback = new URL(event.data.url); } catch { return; }
      if (callback.searchParams.get('attempt') !== new URL(expected).searchParams.get('attempt')) return;
      try { finish(readOAuthCallbackToken(event.data.url, expected)); } catch (error) { finish(undefined, error); }
    };
    browser.addEventListener('message', onMessage);
    const closed = setInterval(() => { if (popup.closed) finish(undefined, new GoogleSignInCanceled()); }, 500);
    const timeout = setTimeout(() => finish(undefined, new Error('Account verification expired. Please try again.')), SESSION_TIMEOUT);
    cancel = () => finish(undefined, new GoogleSignInCanceled());
    cancelReauthentication = cancel;
    void prepare(expected).then(url => { if (!finished) popup.location.replace(url); }).catch(error => finish(undefined, error));
  });
}

export function cancelGmailConnection() { cancelGmailSession?.(); }

function browserLocation() { return (globalThis as { location?: Location }).location; }
function webSessionStorage() {
  try { return (globalThis as { sessionStorage?: Storage }).sessionStorage; }
  catch { return undefined; }
}
