/**
 * src/store/useFlightsStore.js
 * Zustand store for flight data.
 * Fetches real segments from the backend, falls back to dummy data in dev.
 */

import { create } from 'zustand';
import { getSegments } from '../api/trips';
import AIRPORTS from '../data/airports.json';

// Haversine distance in miles
function haversineMiles(lon1, lat1, lon2, lat2) {
  const R  = 3958.8;
  const d1 = (lat2 - lat1) * (Math.PI / 180);
  const d2 = (lon2 - lon1) * (Math.PI / 180);
  const a  =
    Math.sin(d1 / 2) ** 2 +
    Math.cos(lat1 * (Math.PI / 180)) *
    Math.cos(lat2 * (Math.PI / 180)) *
    Math.sin(d2 / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Convert a raw API segment to the shape the UI expects. */
function normalise(seg) {
  const fromCoord = AIRPORTS[seg.dep_airport];
  const toCoord   = AIRPORTS[seg.arr_airport];
  const distMi    = seg.distance_km
    ? seg.distance_km * 0.621371
    : fromCoord && toCoord
    ? haversineMiles(fromCoord[0], fromCoord[1], toCoord[0], toCoord[1])
    : 0;

  const dep = new Date(seg.dep_time);
  const dateStr = dep.toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  }).toUpperCase();

  const durMs = new Date(seg.arr_time) - dep;
  const durH  = Math.floor(durMs / 3_600_000);
  const durM  = Math.floor((durMs % 3_600_000) / 60_000);

  return {
    id:      seg.id,
    from:    seg.dep_airport,
    to:      seg.arr_airport,
    date:    dateStr,
    dur:     `${durH}H ${String(durM).padStart(2, '0')}M`,
    mi:      Math.round(distMi),
    carrier: seg.airline && seg.flight_number
      ? `${seg.airline} ${seg.flight_number}`
      : seg.airline ?? '—',
    fromCoord,
    toCoord,
  };
}

export const useFlightsStore = create((set, get) => ({
  flights:  [],   // normalised flight objects
  totalMi:  0,
  cityGeo:  {},   // { IATA: [lon, lat] } — computed from seen airports
  loading:  false,
  error:    null,

  load: async (token) => {
    set({ loading: true, error: null });
    try {
      const segments = await getSegments(token);
      const flights  = segments.map(normalise);
      const totalMi  = flights.reduce((s, f) => s + f.mi, 0);

      // Build city geo from airports actually seen in the data
      const cityGeo = {};
      flights.forEach(f => {
        if (f.fromCoord) cityGeo[f.from] = f.fromCoord;
        if (f.toCoord)   cityGeo[f.to]   = f.toCoord;
      });

      set({ flights, totalMi, cityGeo, loading: false });
    } catch (e) {
      set({ error: e.message, loading: false });
    }
  },

  /** Seed with dummy data for offline/dev use. */
  seedDummy: (dummyFlights) => {
    const totalMi = dummyFlights.reduce((s, f) => s + f.mi, 0);
    const cityGeo = {};
    dummyFlights.forEach(f => {
      if (AIRPORTS[f.from]) cityGeo[f.from] = AIRPORTS[f.from];
      if (AIRPORTS[f.to])   cityGeo[f.to]   = AIRPORTS[f.to];
    });
    set({ flights: dummyFlights, totalMi, cityGeo });
  },
}));
