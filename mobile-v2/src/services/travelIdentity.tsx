import React from 'react';
import { AppState } from 'react-native';
import { clearAuthToken, getApiBaseUrl, getAuthRevision, getStoredToken, hydrateStoredToken, subscribeAuthToken, useTravelTrips } from './travelTrips';

export type TravelNameRecovery = {
  id: string;
  state: 'queued' | 'running' | 'completed' | 'failed';
  checked: number;
  added: number;
  existing: number;
  needs_review: number;
  error: string | null;
};
export type TravelIdentity = {
  aliases: string[];
  primary_name: string | null;
  confirmed: boolean;
  onboarding_completed: boolean;
  recovery: TravelNameRecovery | null;
};

export const travelIdentityApi = {
  get: () => request<TravelIdentity>('/ingest/travel-name-aliases'),
  saveNames: (aliases: string[]) => request<TravelIdentity>('/ingest/travel-name-aliases', 'PUT', { aliases, confirmed: true }),
  completeOnboarding: () => request<TravelIdentity>('/ingest/travel-onboarding/complete', 'POST', {}),
  retryRecovery: () => request<TravelIdentity>('/ingest/travel-name-recovery', 'POST', {}),
  claimSelf: (itemId: string, passengerName: string) => request<TravelIdentity>(`/ingest/travel-inbox/${encodeURIComponent(itemId)}/claim-self`, 'POST', { passenger_name: passengerName }),
};

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const revision = getAuthRevision();
  const token = getStoredToken() ?? await hydrateStoredToken();
  const guard = () => {
    if (getAuthRevision() !== revision || getStoredToken() !== token) throw new Error('Your account changed.');
  };
  guard();
  if (!token) throw new Error('Sign in to manage your travel names.');
  const controller = new AbortController();
  let unsubscribe = () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(method === 'GET' ? 'Your travel names took too long to load. Please try again.' : 'This is taking longer than expected. Refresh to check whether your names were saved.'));
      controller.abort();
    }, method === 'GET' ? 8000 : 30000);
    unsubscribe = subscribeAuthToken(() => { reject(new Error('Your account changed.')); controller.abort(); });
  });
  try {
    const work = (async () => {
      const response = await fetch(`${getApiBaseUrl()}${path}`, {
        method, signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      guard();
      if (response.status === 401) {
        unsubscribe(); await clearAuthToken();
        throw new Error('Your session expired. Sign in again.');
      }
      const raw = await response.text();
      guard();
      let data: unknown;
      try { data = raw ? JSON.parse(raw) : {}; } catch { throw new Error('Trotter could not read the response. Please try again.'); }
      if (!response.ok) {
        const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : undefined;
        throw new Error(typeof detail === 'string' ? detail : response.status === 422 ? 'Check your names and try again.' : 'Your travel names could not be updated. Please try again.');
      }
      return data as T;
    })();
    return await Promise.race([work, deadline]);
  } finally { clearTimeout(timer); unsubscribe(); }
}

type TravelIdentityContext = {
  identity?: TravelIdentity;
  loading: boolean;
  saving: boolean;
  error?: string;
  refresh: () => Promise<TravelIdentity | undefined>;
  saveNames: (aliases: string[]) => Promise<TravelIdentity>;
  completeOnboarding: () => Promise<TravelIdentity>;
  claimSelf: (itemId: string, passengerName: string) => Promise<TravelIdentity>;
  retryRecovery: () => Promise<TravelIdentity>;
};
const missing = async (): Promise<never> => { throw new Error('Travel names are unavailable. Please reopen Trotter.'); };
const Context = React.createContext<TravelIdentityContext>({ loading: true, saving: false, refresh: missing, saveNames: missing, completeOnboarding: missing, claimSelf: missing, retryRecovery: missing });
export const useTravelIdentity = () => React.useContext(Context);

/** Account-bound names and durable recovery stay active after the setup screen closes. */
export function TravelIdentityProvider({ children }: { children: React.ReactNode }) {
  const { accountId, accountRevision, refresh: refreshTrips } = useTravelTrips();
  const owner = `${accountId ?? ''}:${accountRevision ?? ''}`;
  const ownerRef = React.useRef(owner); ownerRef.current = owner;
  const [record, setRecord] = React.useState<{ owner: string; identity: TravelIdentity }>();
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string>();
  const [foreground, setForeground] = React.useState(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const alive = React.useRef(true), sequence = React.useRef(0), mutating = React.useRef<symbol | undefined>(undefined), reading = React.useRef<symbol | undefined>(undefined);
  const refreshedJobs = React.useRef(new Set<string>());
  const refreshTripsRef = React.useRef(refreshTrips); refreshTripsRef.current = refreshTrips;
  const identity = record?.owner === owner ? record.identity : undefined;
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; sequence.current += 1; }; }, []);
  React.useEffect(() => {
    const sub = AppState.addEventListener('change', state => setForeground(state === 'active'));
    return () => sub.remove();
  }, []);
  const refresh = React.useCallback(async () => {
    if (!accountId || mutating.current || reading.current) return undefined;
    const read = Symbol(); reading.current = read;
    const version = ++sequence.current;
    try {
      const next = await travelIdentityApi.get();
      if (alive.current && ownerRef.current === owner && version === sequence.current) {
        setRecord({ owner, identity: next }); setError(undefined); setLoading(false);
      }
      return alive.current && ownerRef.current === owner && version === sequence.current ? next : undefined;
    } catch (cause) {
      if (alive.current && ownerRef.current === owner && version === sequence.current) { setError(errorMessage(cause)); setLoading(false); }
      throw cause;
    } finally { if (reading.current === read) reading.current = undefined; }
  }, [accountId, owner]);
  React.useEffect(() => {
    reading.current = undefined; mutating.current = undefined; sequence.current += 1;
    setLoading(true); setSaving(false); setError(undefined); refreshedJobs.current.clear();
    void refresh().catch(() => undefined);
  }, [refresh]);
  const recovery = identity?.recovery;
  const pending = recovery?.state === 'queued' || recovery?.state === 'running';
  React.useEffect(() => {
    if (!foreground || !pending) return;
    const timer = setInterval(() => { void refresh().catch(() => undefined); }, 4000);
    return () => clearInterval(timer);
  }, [foreground, pending, refresh]);
  React.useEffect(() => {
    if (!foreground || !recovery || recovery.state !== 'completed' || refreshedJobs.current.has(recovery.id)) return;
    refreshedJobs.current.add(recovery.id);
    void refreshTripsRef.current().catch(() => {
      // The recovery is already committed. A later normal trip refresh sees it.
      if (alive.current && ownerRef.current === owner) setError('Your flights were recovered. Refresh Trips to see the update.');
    });
  }, [foreground, recovery?.id, recovery?.state, owner]);
  const mutate = React.useCallback(async (action: () => Promise<TravelIdentity>) => {
    if (mutating.current) throw new Error('Your names are being saved. Please wait a moment.');
    const mutation = Symbol(); mutating.current = mutation; const version = ++sequence.current; setSaving(true); setError(undefined);
    try {
      const next = await action();
      if (!alive.current || ownerRef.current !== owner || version !== sequence.current) throw new Error('Your account changed.');
      setRecord({ owner, identity: next }); setLoading(false);
      return next;
    } catch (cause) {
      if (alive.current && ownerRef.current === owner && version === sequence.current) setError(errorMessage(cause));
      throw cause;
    } finally {
      if (mutating.current === mutation) mutating.current = undefined;
      if (alive.current && ownerRef.current === owner) setSaving(false);
    }
  }, [owner]);
  return <Context.Provider value={{ identity, loading: !identity && loading, saving, error, refresh,
    saveNames: aliases => mutate(() => travelIdentityApi.saveNames(aliases)),
    completeOnboarding: () => mutate(travelIdentityApi.completeOnboarding),
    claimSelf: (itemId, passengerName) => mutate(() => travelIdentityApi.claimSelf(itemId, passengerName)),
    retryRecovery: () => mutate(travelIdentityApi.retryRecovery),
  }}>{children}</Context.Provider>;
}

const errorMessage = (cause: unknown) => cause instanceof Error ? cause.message : 'Please try again.';
