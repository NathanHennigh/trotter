import type { TripSummary } from "../../../data/trotterMock";

/** Bounds in the popup's React root: native measure page coordinates, centered-root-adjusted on web. */
export type TripOpenOrigin = {
  x: number; y: number; width: number; height: number;
  wallet?: { trip: TripSummary; scopeYear?: string; totalFlightCount?: number };
};

const unit = (value: number) => Math.max(0, Math.min(1, value));
const smooth = (value: number) => {
  const t = unit(value);
  return t * t * (3 - 2 * t);
};

/** One continuous path; sampled once for native interpolation, never on JS frames. */
export function walletMotionFrame(progress: number, anchored = true) {
  const p = unit(progress);
  const travel = anchored ? smooth((p - .025) / .975) : 1 - Math.pow(1 - p, 3);
  const expansion = anchored ? smooth((p - .09) / .91) : travel;
  const lift = anchored && p < .65 ? 22 * Math.pow(Math.sin(Math.PI * p / .65), 2) : 0;
  const reveal = anchored ? smooth((p - .30) / .16) : 1;
  return { travel, expansion, lift, reveal, cover: 1 - reveal,
    summary: 1 - smooth((p - .22) / .10) };
}

export const walletMotionSamples = Array.from({ length: 101 }, (_, index) => index / 100);

/** Project the released sheet a short distance in the finger's direction. */
export function shouldDismissWallet(distance: number, velocity: number, height: number) {
  if (![distance, velocity, height].every(Number.isFinite) || distance < 18) return false;
  const threshold = Math.min(150, Math.max(90, height * .18));
  return distance + velocity * .18 >= threshold;
}
