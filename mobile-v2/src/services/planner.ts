import {
  clearAuthToken, getApiBaseUrl, getAuthRevision, getStoredToken,
  hydrateStoredToken, subscribeAuthToken,
} from './travelTrips';

export type PlannerRole = 'owner' | 'editor' | 'contributor';
export type PlannerPace = 'relaxed' | 'balanced' | 'packed';
export type PlannerTransport = 'walk' | 'drive' | 'transit';
export type PlannerDreamScope = { id: string; country: string; city: string | null; label: string };
export type PlannerDreamDestination = PlannerDreamScope & { count: number };
export type PlannerDreamSharing = { enabled: boolean; active: boolean; paused_reason: string | null; consented_at: string | null };
export type PlannerDreamSuggestion = { dream_item_id: string; title: string; category: string; city: string | null; country: string | null; image_url?: string | null };
export type PlannerDreamSuggestions = {
  scope: PlannerDreamScope | null; sharing: PlannerDreamSharing | null; total: number;
  suggestions: PlannerDreamSuggestion[]; next_cursor: string | null;
};
export type PlannerTripSummary = {
  id: string; title: string; destination: string; start_date: string; end_date: string;
  timezone: string; pace: PlannerPace; transport: PlannerTransport; role: PlannerRole;
  transport_modes?: PlannerTransport[];
  version: number; member_count: number; idea_count: number; cover_image_url?: string | null; updated_at: string;
  match_scope?: PlannerDreamScope | null; dream_sharing?: PlannerDreamSharing | null;
};
export type PlannerIdea = {
  id: string; title: string; category: string; city?: string | null; country?: string | null;
  image_url?: string | null; source_url?: string | null; google_place_id?: string | null;
  latitude?: number | null; longitude?: number | null; duration_minutes: number; must_do: boolean;
  score: number; my_vote: -1 | 0 | 1; contributors: { user_id: string; name: string }[];
  source_count: number; created_by: string; status: 'ready' | 'processing' | 'needs_details';
};
export type PlannerMember = { user_id: string; name: string; role: PlannerRole };
export type PlannerInvite = { id: string; label?: string | null; role: 'editor' | 'contributor'; expires_at: string; status: string; uses: number };
export type PlannerStop = {
  id: string; idea_id?: string | null; title: string; start_time: string; duration_minutes: number;
  locked: boolean; kind: 'place' | 'booking' | 'break'; notes?: string;
  travel_minutes?: number | null; travel_source?: 'google' | 'estimate' | 'unknown';
  travel_from_stop_id?: string | null; travel_mode?: PlannerTransport | null; travel_blocked?: boolean; user_created?: boolean;
};
export type PlannerStay = { status: 'needed' | 'suggested' | 'selected' | 'not_needed'; idea_id?: string; city?: string; reason?: string };
export type PlannerDay = { date: string; stops: PlannerStop[]; stay?: PlannerStay; planning_note?: string };
export type PlannerExclusionReason = { code: 'needs_location' | 'processing' | 'closed' | 'opening_hours' | 'transport_required' | 'travel_unverified' | 'low_interest' | 'duplicate' | 'no_fit'; transport_mode?: PlannerTransport };
export type PlannerPlan = { days: PlannerDay[]; warnings: string[]; unplaced_idea_ids: string[]; unplaced_reasons?: Record<string, PlannerExclusionReason> };
export type PlannerRevision = { id: string; plan: PlannerPlan; source: string; created_at: string; base_version: number };
export type PlannerJob = { id: string; status: 'queued' | 'running' | 'completed' | 'failed'; message?: string; revision_id?: string };
export type PlannerTrip = PlannerTripSummary & {
  ideas: PlannerIdea[]; members: PlannerMember[]; invites: PlannerInvite[];
  plan: PlannerPlan | null; draft: PlannerRevision | null; generation: PlannerJob | null;
};
export type PlannerInvitePreview = {
  trip: Pick<PlannerTripSummary, 'id' | 'title' | 'destination' | 'start_date' | 'end_date' | 'cover_image_url'>;
  inviter_name: string; role: 'editor' | 'contributor'; member_count: number; status: string;
};
export type PlannerCreate = Pick<PlannerTripSummary, 'title' | 'destination' | 'start_date' | 'end_date' | 'timezone' | 'pace' | 'transport'> & {
  client_request_id: string; dream_item_ids?: string[]; match_scope_id?: string | null; transport_modes?: PlannerTransport[];
};
export type PlannerNewIdea = {
  title: string; category?: string; city?: string; country?: string; source_url?: string;
  latitude?: number; longitude?: number; duration_minutes?: number; client_request_id: string;
};

export class PlannerApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'PlannerApiError'; }
}
const listeners = new Set<(tripId?: string) => void>();
export function subscribePlannerChanges(listener: (tripId?: string) => void) {
  listeners.add(listener); return () => { listeners.delete(listener); };
}
function changed(tripId?: string) { listeners.forEach(listener => listener(tripId)); }
const path = (id: string) => `/planner/trips/${encodeURIComponent(id)}`;
const child = (id: string, suffix: string) => `${path(id)}/${suffix}`;

export const plannerApi = {
  list: (signal?: AbortSignal) => request<{ trips: PlannerTripSummary[] }>('/planner/trips', 'GET', undefined, signal),
  get: (id: string, signal?: AbortSignal) => request<PlannerTrip>(path(id), 'GET', undefined, signal),
  create: (body: PlannerCreate) => mutation<PlannerTrip>('/planner/trips', 'POST', body),
  update: (id: string, body: Partial<PlannerCreate> & { expected_version: number }) => mutation<PlannerTrip>(path(id), 'PATCH', body, id),
  removeTrip: (id: string, expectedVersion: number) => mutation<{ deleted: boolean }>(`${path(id)}?expected_version=${expectedVersion}`, 'DELETE', undefined, id),
  importDreams: (id: string, dream_item_ids: string[]) => mutation<PlannerTrip>(child(id, 'ideas/import'), 'POST', { dream_item_ids }, id),
  dreamDestinations: (signal?: AbortSignal) => request<{ destinations: PlannerDreamDestination[] }>('/planner/dreams/destinations', 'GET', undefined, signal),
  dreamSuggestions: (id: string, cursor?: string, signal?: AbortSignal) => request<PlannerDreamSuggestions>(`${child(id, 'dream-suggestions')}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, 'GET', undefined, signal),
  importMatchingDreams: (id: string, body: { scope_id: string; all: true } | { scope_id: string; dream_item_ids: string[] }) => mutation<PlannerTrip>(child(id, 'dream-suggestions/import'), 'POST', body, id),
  setDreamSharing: (id: string, scope_id: string, enabled: boolean) => mutation<PlannerTrip>(child(id, 'dream-sharing'), 'PUT', { scope_id, enabled }, id),
  bookings: (id: string, signal?: AbortSignal) => request<{ bookings: { segment_id: string; title: string; date: string; start_time: string; duration_minutes: number; flight_number: string | null }[] }>(child(id, 'bookings'), 'GET', undefined, signal),
  importBookings: (id: string, expected_version: number, segment_ids: string[]) => mutation<PlannerTrip>(child(id, 'bookings/import'), 'POST', { expected_version, segment_ids }, id),
  addIdea: (id: string, body: PlannerNewIdea) => mutation<PlannerTrip>(child(id, 'ideas'), 'POST', body, id),
  addSource: (id: string, body: { source_url: string; shared_text?: string; client_request_id: string }) => mutation<PlannerTrip>(child(id, 'sources'), 'POST', body, id),
  updateIdea: (id: string, ideaId: string, body: Partial<Pick<PlannerIdea, 'duration_minutes' | 'must_do' | 'title' | 'city' | 'country'>>) =>
    mutation<PlannerTrip>(child(id, `ideas/${encodeURIComponent(ideaId)}`), 'PATCH', body, id),
  removeIdea: (id: string, ideaId: string) => mutation<PlannerTrip>(child(id, `ideas/${encodeURIComponent(ideaId)}`), 'DELETE', undefined, id),
  vote: (id: string, ideaId: string, value: -1 | 0 | 1) => mutation<PlannerTrip>(child(id, `ideas/${encodeURIComponent(ideaId)}/vote`), 'PUT', { value }, id),
  generate: (id: string, body: { expected_version: number; client_request_id: string; day?: string; pace?: PlannerPace; mode?: 'ai' | 'rules' }) =>
    mutation<PlannerJob>(child(id, 'generate'), 'POST', body, id),
  job: (id: string, jobId: string, signal?: AbortSignal) => request<PlannerJob>(child(id, `jobs/${encodeURIComponent(jobId)}`), 'GET', undefined, signal),
  savePlan: (id: string, expected_version: number, plan: PlannerPlan) => mutation<PlannerTrip>(child(id, 'plan'), 'PUT', { expected_version, plan }, id),
  acceptDraft: (id: string, expected_version: number, revision_id: string) => mutation<PlannerTrip>(child(id, 'draft/accept'), 'POST', { expected_version, revision_id }, id),
  discardDraft: (id: string, expected_version: number) => mutation<PlannerTrip>(child(id, 'draft'), 'DELETE', { expected_version }, id),
  history: (id: string, signal?: AbortSignal) => request<{ revisions: PlannerRevision[] }>(child(id, 'history'), 'GET', undefined, signal),
  restore: (id: string, expected_version: number, revision_id: string) => mutation<PlannerTrip>(child(id, 'restore'), 'POST', { expected_version, revision_id }, id),
  invite: (id: string, body: { role: 'editor' | 'contributor'; label?: string; recipient_email?: string; client_request_id: string }) =>
    mutation<{ invite: PlannerInvite; share_url: string; token: string }>(child(id, 'invites'), 'POST', body, id),
  revoke: (id: string, inviteId: string) => mutation<PlannerTrip>(child(id, `invites/${encodeURIComponent(inviteId)}`), 'DELETE', undefined, id),
  previewInvite: (token: string, signal?: AbortSignal) => request<PlannerInvitePreview>('/planner/invites/resolve', 'POST', { token }, signal, true),
  acceptInvite: (token: string) => mutation<PlannerTrip>('/planner/invites/accept', 'POST', { token }),
  changeRole: (id: string, memberId: string, role: 'editor' | 'contributor') =>
    mutation<PlannerTrip>(child(id, `members/${encodeURIComponent(memberId)}`), 'PATCH', { role }, id),
  removeMember: (id: string, memberId: string) => mutation<PlannerTrip>(child(id, `members/${encodeURIComponent(memberId)}`), 'DELETE', undefined, id),
};

async function mutation<T>(url: string, method: string, body?: unknown, tripId?: string) {
  const data = await request<T>(url, method, body); changed(tripId); return data;
}

async function request<T>(url: string, method = 'GET', body?: unknown, signal?: AbortSignal, publicRequest = false): Promise<T> {
  const revision = getAuthRevision();
  const token = publicRequest ? undefined : getStoredToken() ?? await hydrateStoredToken();
  if (!publicRequest && revision !== getAuthRevision()) throw new PlannerApiError('Your account changed. Open the trip again.', 401);
  if (!publicRequest && !token) throw new PlannerApiError('Sign in to open your trips.', 401);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let unsubscribe = () => {};
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const guard = () => {
    if (!publicRequest && (revision !== getAuthRevision() || token !== getStoredToken())) throw new PlannerApiError('Your account changed. Open the trip again.', 401);
  };
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => { controller.abort(); reject(new PlannerApiError(method === 'GET'
      ? 'The trip took too long to load. Check your connection and retry.'
      : 'The connection timed out. Refresh to check whether your change was saved before trying again.', 408)); }, 30000);
    if (!publicRequest) unsubscribe = subscribeAuthToken(() => { controller.abort(); reject(new PlannerApiError('Your account changed. Open the trip again.', 401)); });
  });
  try {
    return await Promise.race([deadline, (async () => {
      const response = await fetch(`${getApiBaseUrl()}${url}`, { method, signal: controller.signal,
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      guard();
      if (response.status === 401 && !publicRequest) { unsubscribe(); await clearAuthToken(); throw new PlannerApiError('Your session expired. Sign in again.', 401); }
      const raw = await response.text(); guard();
      let result: any;
      try { result = raw ? JSON.parse(raw) : {}; } catch { throw new PlannerApiError('Trotter could not read the response. Please retry.', response.status); }
      if (!response.ok) {
        const detail = result?.detail;
        const message = typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message
          : response.status === 409 ? 'This trip has changed. Your edits are still here; review the latest plan before saving again.'
          : response.status === 404 ? 'This trip is no longer available, or you no longer have access.'
          : response.status === 422 ? 'Check the dates, times and required details, then try again.'
          : 'That change could not be completed. Please try again.';
        throw new PlannerApiError(message, response.status);
      }
      return result as T;
    })()]);
  } finally { clearTimeout(timer); unsubscribe(); signal?.removeEventListener('abort', abort); }
}
