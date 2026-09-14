/** Screen-space bounds of the paper that opened an itinerary. */
import type { TripSummary } from "../../../data/trotterMock";

export type TripOpenOrigin = {
  x: number; y: number; width: number; height: number;
  wallet?: { trip: TripSummary; scopeYear?: string; totalFlightCount?: number };
};
