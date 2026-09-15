import type { TripSummary } from "../../../data/trotterMock";

/** Bounds in the popup's React root: native measure page coordinates, centered-root-adjusted on web. */
export type TripOpenOrigin = {
  x: number; y: number; width: number; height: number;
  wallet?: { trip: TripSummary; scopeYear?: string; totalFlightCount?: number };
};
