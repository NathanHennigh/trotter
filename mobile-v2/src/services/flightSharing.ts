import {
  clearAuthToken, getApiBaseUrl, getAuthRevision, getStoredToken,
  hydrateStoredToken, subscribeAuthToken,
} from './travelTrips';

export type SharedFlight = {
  dep_airport: string;
  arr_airport: string;
  travel_date: string;
  flight_number?: string | null;
  dep_time?: string | null;
  arr_time?: string | null;
  airline?: string | null;
};
export type RetainedFlight = {
  id: string;
  passenger_name: string | null;
  assigned_passenger_name?: string | null;
  reason: 'other_traveler' | 'companion' | 'unassigned';
  status: 'retained' | 'needs_review' | 'canceled' | 'belongs_to_you';
  shareable: boolean;
  requires_assignment?: boolean;
  share_blocked_reason?: string | null;
  flight: (SharedFlight & { pnr?: string | null }) | null;
};
export type FlightShare = {
  id: string;
  passenger_name: string;
  sender_name: string;
  recipient_email: string;
  status: 'pending' | 'accepted' | 'declined' | 'revoked' | 'expired';
  created_at: string;
  expires_at: string;
  accepted_at?: string | null;
  flights: SharedFlight[];
};
export type FlightSharingInbox = {
  items: RetainedFlight[];
  incoming: FlightShare[];
  outgoing: FlightShare[];
};
export type CreateFlightShare = {
  item_ids: string[];
  passenger_name: string;
  recipient_email: string;
  client_request_id: string;
};
export type CreatedFlightShare = { share: FlightShare; share_url: string };
export type AcceptedFlightShare = { share: FlightShare; added_flights: number; existing_flights: number };

export const flightSharing = {
  inbox: () => request<FlightSharingInbox>('/travel-sharing/inbox'),
  assign: (id: string, passenger_name: string) => request<RetainedFlight>(`/travel-sharing/items/${encodeURIComponent(id)}`, 'PATCH', { passenger_name }),
  create: (input: CreateFlightShare) => request<CreatedFlightShare>('/travel-sharing', 'POST', input),
  resolve: (token: string) => request<FlightShare>('/travel-sharing/resolve', 'POST', { token }),
  accept: (id: string) => request<AcceptedFlightShare>(`/travel-sharing/${encodeURIComponent(id)}/accept`, 'POST'),
  decline: (id: string) => request<{ share: FlightShare }>(`/travel-sharing/${encodeURIComponent(id)}/decline`, 'POST'),
  revoke: (id: string) => request<{ share: FlightShare }>(`/travel-sharing/${encodeURIComponent(id)}/revoke`, 'POST'),
  link: (id: string) => request<{ share_url: string }>(`/travel-sharing/${encodeURIComponent(id)}/link`, 'POST'),
};

// A late response must never put one account's tickets into another account's UI.
async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const initialRevision = getAuthRevision();
  const token = getStoredToken() ?? await hydrateStoredToken();
  if (initialRevision !== getAuthRevision()) throw new Error('Your account changed.');
  if (!token) throw new Error('Sign in to view shared flights.');
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let unsubscribe = () => {};
  const guard = () => {
    if (initialRevision !== getAuthRevision() || token !== getStoredToken()) throw new Error('Your account changed.');
  };
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(method === 'GET'
        ? 'Flights took too long to load. Check your connection and retry.'
        : 'The request is taking longer than expected. Refresh to check its status before trying again.'));
      controller.abort();
    }, 30000);
    unsubscribe = subscribeAuthToken(() => {
      reject(new Error('Your account changed.'));
      controller.abort();
    });
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
        unsubscribe();
        await clearAuthToken();
        throw new Error('Your session expired. Sign in again.');
      }
      const text = await response.text();
      guard();
      let data: unknown;
      try { data = text ? JSON.parse(text) : {}; }
      catch { throw new Error('Trotter could not read the response. Please retry.'); }
      if (!response.ok) {
        const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : undefined;
        throw new Error(typeof detail === 'string' ? detail : 'That change could not be completed. Refresh and try again.');
      }
      return data as T;
    })();
    return await Promise.race([work, deadline]);
  } finally {
    clearTimeout(timer);
    unsubscribe();
  }
}
