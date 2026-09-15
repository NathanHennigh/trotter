import type { TripOpenOrigin } from './tripTransition';

export function walletPopupGeometry(width: number, height: number, top: number, bottom: number, origin?: TripOpenOrigin) {
  const panelWidth = Math.min(560, Math.max(1, width - 40));
  const target = { x: (width - panelWidth) / 2, y: top + 52, width: panelWidth,
    height: Math.max(1, height - top - bottom - 68) };
  const anchored = Boolean(origin?.wallet && [origin.x, origin.y, origin.width, origin.height].every(Number.isFinite)
    && origin.width > 40 && origin.height > 40 && origin.y < height - bottom
    && origin.y + origin.height > top && origin.x < width && origin.x + origin.width > 0);
  const source = anchored ? { x: origin!.x, y: origin!.y, width: origin!.width, height: origin!.height }
    : { ...target, y: target.y + 34, height: target.height * .96 };
  return { target, source, anchored };
}
