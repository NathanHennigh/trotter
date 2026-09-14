import type { StampTemplate } from '../../trotter/stamps/PngStamp';

export type StampLabelBox = { x: number; y: number; width: number; height: number };
export type StampFootprint = { x: number; y: number; width: number; height: number; labels: StampLabelBox[] };
export const STAMP_WIDTH = 204.75, STAMP_HEIGHT = 165.75;

// Crop the same calibrated native frame and label geometry used to paint the
// stamp. This removes the old canvas margins without clipping any ink or text.
// It works for new countries and edited templates without a per-country asset.
export function stampFootprint(template: StampTemplate): StampFootprint {
  const boxes = [template.frame, template.country, template.icon, template.date, template.airport];
  const x = Math.min(...boxes.map(b => b.left * STAMP_WIDTH)) - 7;
  const y = Math.min(...boxes.map(b => b.top * STAMP_HEIGHT)) - 7;
  const right = Math.max(...boxes.map(b => (b.left + b.width) * STAMP_WIDTH)) + 7;
  const bottom = Math.max(...boxes.map(b => (b.top + b.height) * STAMP_HEIGHT)) + 7;
  const width = right - x, height = bottom - y;
  const labels = [template.country, template.date, template.airport].map(b => ({
    x: (b.left * STAMP_WIDTH - x) / width, y: (b.top * STAMP_HEIGHT - y) / height,
    width: b.width * STAMP_WIDTH / width, height: b.height * STAMP_HEIGHT / height,
  }));
  // Circular lettering spans the top of the frame rather than its straight
  // text box; reserve that arc as well when other impressions overlap a frame.
  if (template.titleMode === 'circleArc') {
    const b = template.frame;
    labels.push({ x: (b.left * STAMP_WIDTH - x) / width, y: (b.top * STAMP_HEIGHT - y) / height,
      width: b.width * STAMP_WIDTH / width, height: b.height * STAMP_HEIGHT * .38 / height });
  }
  return { x, y, width, height, labels };
}
