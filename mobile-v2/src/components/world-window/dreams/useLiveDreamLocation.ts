import React from "react";
import { fetchDreamLocationDetails, type DreamItem, type DreamLocationDetails } from "../../../services/dreams";
import { getAuthRevision, subscribeAuthToken } from "../../../services/travelTrips";

/** Short-lived detail data is cancelled and discarded on close or account change. */
export function useLiveDreamLocation(item: DreamItem, enabled = true) {
  const revision = React.useSyncExternalStore(subscribeAuthToken, getAuthRevision, getAuthRevision);
  const [attempt, retry] = React.useReducer(value => value + 1, 0);
  const [state, setState] = React.useState<{ key: string; details?: DreamLocationDetails; error?: string; loading: boolean }>();
  const google = item.locationProvider === "google_places";
  const key = JSON.stringify([item.id, revision, item.locationPlaceId, item.locationCandidateIds, item.locationStatus, enabled, attempt]);
  React.useEffect(() => {
    if (!enabled || !google || !/^\d+$/.test(item.id) || item.locationStatus === "queued" || item.locationStatus === "running") { setState(undefined); return; }
    let active = true;
    const controller = new AbortController();
    setState({ key, loading: true });
    void fetchDreamLocationDetails(item.id, controller.signal).then(details => {
      if (active) setState({ key, details, loading: false });
    }).catch(error => { if (active) setState({ key, loading: false, error: error instanceof Error ? error.message : "Location details could not load." }); });
    return () => { active = false; controller.abort(); };
  }, [key, google, enabled]);
  return { details: state?.key === key ? state.details : undefined, loading: state?.key === key && state.loading,
    error: state?.key === key ? state.error : undefined, retry };
}
