import React from 'react';
import { Linking, Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { getApiBaseUrl } from './travelTrips';

const STORAGE_KEY = 'trotter.pending-planner-invitation.v1';
const MAX_AGE = 14 * 24 * 60 * 60 * 1000;
const validToken = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{32,128}$/.test(value);
type Invitation = { token: string; receivedAt: number };

export function parsePlannerLink(value: string, apiBaseUrl: string, webAppUrl?: string): string | undefined {
  try {
    const url = new URL(value), api = new URL(apiBaseUrl);
    if (url.username || url.password) return undefined;
    const native = url.protocol === 'trotterv2:' && !url.port && url.hostname === 'planner-invite' && ['', '/'].includes(url.pathname);
    const landing = url.protocol === 'https:' && url.origin === api.origin && url.pathname === `${api.pathname.replace(/\/$/, '')}/planner/open`;
    const app = webAppUrl ? new URL(webAppUrl) : undefined;
    const web = Boolean(app && url.origin === app.origin && url.pathname === '/' && (url.protocol === 'https:' || (url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname))));
    if (!native && !landing && !web) return undefined;
    if ((native && url.hash) || (!native && url.search)) return undefined;
    const params = native ? url.searchParams : new URLSearchParams(url.hash.slice(1));
    const key = web ? 'planner-invitation' : 'token';
    const values = params.getAll(key);
    return values.length === 1 && [...params.keys()].every(name => name === key) && validToken(values[0]) ? values[0] : undefined;
  } catch { return undefined; }
}

export function readPendingPlannerInvitation(raw: string | null, now = Date.now()): Invitation | undefined {
  try {
    const value = raw ? JSON.parse(raw) : null;
    if (value && validToken(value.token) && Number.isFinite(value.receivedAt) && value.receivedAt <= now && now - value.receivedAt < MAX_AGE) return value;
  } catch { /* A bad saved pointer must not prevent launch. */ }
  return undefined;
}

async function readSaved() {
  return Platform.OS === 'web' ? globalThis.sessionStorage?.getItem(STORAGE_KEY) ?? null : SecureStore.getItemAsync(STORAGE_KEY);
}
async function save(value?: Invitation) {
  if (Platform.OS === 'web') {
    if (value) globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(value));
    else globalThis.sessionStorage?.removeItem(STORAGE_KEY);
  } else if (value) await SecureStore.setItemAsync(STORAGE_KEY, JSON.stringify(value), { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY });
  else await SecureStore.deleteItemAsync(STORAGE_KEY);
}

function clearInvitationFragment() {
  if (Platform.OS !== 'web' || !globalThis.location) return;
  globalThis.history?.replaceState(globalThis.history.state, '', `${globalThis.location.pathname}${globalThis.location.search}`);
}

const Context = React.createContext<{ token?: string; ready: boolean; consume: (token: string) => void }>({ ready: true, consume: () => undefined });
export const usePlannerInvitation = () => React.useContext(Context);

/** An invitation survives sign-in, but joining always requires a deliberate action. */
export function PlannerInvitationProvider({ children }: { children: React.ReactNode }) {
  const [invitation, setInvitation] = React.useState<Invitation>();
  const [ready, setReady] = React.useState(false);
  const current = React.useRef<Invitation | undefined>(undefined);
  const writes = React.useRef<Promise<void>>(Promise.resolve());
  const persist = React.useCallback((value?: Invitation) => {
    writes.current = writes.current.catch(() => undefined).then(() => save(value)).catch(() => undefined);
  }, []);
  React.useEffect(() => {
    let active = true, receivedLive = false;
    const webUrl = Platform.OS === 'web' ? globalThis.location?.origin : undefined;
    const receive = (url: string) => {
      const token = parsePlannerLink(url, getApiBaseUrl(), webUrl);
      if (!active || !token) return;
      receivedLive = true;
      const next = { token, receivedAt: Date.now() };
      current.current = next; setInvitation(next); persist(next);
      clearInvitationFragment();
    };
    const listener = Linking.addEventListener('url', ({ url }) => receive(url));
    const onHash = () => { if (Platform.OS === 'web' && globalThis.location?.href) receive(globalThis.location.href); };
    if (Platform.OS === 'web') globalThis.addEventListener?.('hashchange', onHash);
    void Promise.all([readSaved().catch(() => null), Linking.getInitialURL().catch(() => null)]).then(([raw, initialUrl]) => {
      if (!active) return;
      if (!receivedLive) {
        const url = initialUrl ?? (Platform.OS === 'web' ? globalThis.location?.href : undefined);
        const token = url ? parsePlannerLink(url, getApiBaseUrl(), webUrl) : undefined;
        const next = token ? { token, receivedAt: Date.now() } : readPendingPlannerInvitation(raw);
        current.current = next; setInvitation(next); persist(next);
        if (token) clearInvitationFragment();
      }
      setReady(true);
    });
    return () => { active = false; listener.remove(); if (Platform.OS === 'web') globalThis.removeEventListener?.('hashchange', onHash); };
  }, [persist]);
  const consume = React.useCallback((token: string) => {
    if (current.current?.token !== token) return;
    current.current = undefined; setInvitation(undefined); persist();
  }, [persist]);
  return React.createElement(Context.Provider, { value: { token: invitation?.token, ready, consume } }, children);
}
