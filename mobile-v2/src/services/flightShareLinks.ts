import React from 'react';
import { Linking, Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { getApiBaseUrl } from './travelTrips';

const STORAGE_KEY = 'trotter.pending-flight-invitation.v1';
const MAX_AGE = 14 * 24 * 60 * 60 * 1000;
const validToken = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{32,128}$/.test(value);
type Invitation = { token: string; receivedAt: number };

/** A link is only a pointer. The server still verifies the recipient's account. */
export function parseFlightShareLink(value: string, apiBaseUrl: string, webAppUrl?: string): string | undefined {
  try {
    const url = new URL(value);
    const api = new URL(apiBaseUrl);
    if (url.username || url.password) return undefined;
    const native = url.protocol === 'trotterv2:' && !url.port && url.hostname === 'flight-share' && (url.pathname === '' || url.pathname === '/');
    const web = url.protocol === 'https:' && url.origin === api.origin && url.pathname === `${api.pathname.replace(/\/$/, '')}/travel-sharing/open`;
    const app = webAppUrl ? new URL(webAppUrl) : undefined;
    const webApp = Boolean(app && url.origin === app.origin && url.pathname === '/' && (url.protocol === 'https:' || (url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname))));
    if (!native && !web && !webApp) return undefined;
    if ((native && url.hash) || (web && url.search)) return undefined;
    if (webApp && url.search) return undefined;
    const params = native ? url.searchParams : new URLSearchParams(url.hash.slice(1));
    const key = webApp ? 'flight-invitation' : 'token';
    const tokens = params.getAll(key);
    return tokens.length === 1 && [...params.keys()].every(param => param === key) && validToken(tokens[0]) ? tokens[0] : undefined;
  } catch { return undefined; }
}

export function readPendingFlightInvitation(raw: string | null, now = Date.now()): Invitation | undefined {
  if (!raw) return undefined;
  try {
    const value = JSON.parse(raw);
    if (validToken(value.token) && Number.isFinite(value.receivedAt) && value.receivedAt <= now && now - value.receivedAt < MAX_AGE) return value;
  } catch { /* Invalid saved pointers never prevent the app opening. */ }
  return undefined;
}

async function readSaved(): Promise<string | null> {
  if (Platform.OS === 'web') return globalThis.sessionStorage?.getItem(STORAGE_KEY) ?? null;
  return SecureStore.getItemAsync(STORAGE_KEY);
}
async function save(value?: Invitation) {
  if (Platform.OS === 'web') {
    if (value) globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(value));
    else globalThis.sessionStorage?.removeItem(STORAGE_KEY);
  } else if (value) {
    await SecureStore.setItemAsync(STORAGE_KEY, JSON.stringify(value), { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY });
  } else await SecureStore.deleteItemAsync(STORAGE_KEY);
}

type InvitationContext = { token?: string; ready: boolean; consume: (token: string) => void };
const Context = React.createContext<InvitationContext>({ ready: true, consume: () => undefined });
export const useFlightInvitation = () => React.useContext(Context);

/** Keep the invitation through OAuth or a process restart, without saving flight data. */
export function FlightInvitationProvider({ children }: { children: React.ReactNode }) {
  const [invitation, setInvitation] = React.useState<Invitation>();
  const [ready, setReady] = React.useState(false);
  const current = React.useRef<Invitation | undefined>(undefined);
  const writes = React.useRef<Promise<void>>(Promise.resolve());
  const persist = React.useCallback((value?: Invitation) => {
    writes.current = writes.current.catch(() => undefined).then(() => save(value)).catch(() => undefined);
  }, []);
  React.useEffect(() => {
    let active = true;
    let receivedLive = false;
    const webUrl = Platform.OS === 'web' ? globalThis.location?.origin : undefined;
    const receive = (url: string) => {
      const token = parseFlightShareLink(url, getApiBaseUrl(), webUrl);
      if (!token || !active) return;
      receivedLive = true;
      const next = { token, receivedAt: Date.now() };
      current.current = next;
      setInvitation(next);
      persist(next);
    };
    const listener = Linking.addEventListener('url', ({ url }) => receive(url));
    void Promise.all([readSaved().catch(() => null), Linking.getInitialURL().catch(() => null)]).then(([raw, initialUrl]) => {
      if (!active) return;
      // A newer link received while storage loads must win over old state.
      if (!receivedLive) {
        const url = initialUrl ?? (Platform.OS === 'web' ? globalThis.location?.href : undefined);
        const initial = url ? parseFlightShareLink(url, getApiBaseUrl(), webUrl) : undefined;
        const next = initial ? { token: initial, receivedAt: Date.now() } : readPendingFlightInvitation(raw);
        current.current = next;
        setInvitation(next);
        persist(next);
        if (initial && Platform.OS === 'web') globalThis.history?.replaceState({}, '', '/');
      }
      setReady(true);
    });
    return () => { active = false; listener.remove(); };
  }, [persist]);
  const consume = React.useCallback((token: string) => {
    if (current.current?.token !== token) return;
    current.current = undefined;
    setInvitation(undefined);
    persist();
  }, [persist]);
  return React.createElement(Context.Provider, { value: { token: invitation?.token, ready, consume } }, children);
}
