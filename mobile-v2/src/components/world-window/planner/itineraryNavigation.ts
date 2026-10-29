/** Layout coordinates are relative to the itinerary's scroll content. */
export function visibleItineraryDay(dates: readonly string[], offsets: Readonly<Record<string, number>>, scrollY: number, inset: number) {
  let current = dates[0];
  for (const date of dates) {
    if (Number.isFinite(offsets[date]) && offsets[date] <= Math.max(0, scrollY) + inset + 24) current = date;
  }
  return current;
}

export function itineraryDayOffset(offset: number | undefined, inset: number) {
  return offset === undefined || !Number.isFinite(offset) ? undefined : Math.max(0, offset - inset - 8);
}

export function reorderPreview(ids: readonly string[], id: string, target: number) {
  const from = ids.indexOf(id);
  if (from < 0) return [...ids];
  const result = [...ids]; result.splice(from, 1); result.splice(Math.max(0, Math.min(result.length, target)), 0, id);
  return result;
}

export function stopPositions(ids: readonly string[], heights: Readonly<Record<string, number>>) {
  const positions: Record<string, number> = {}; let height = 0;
  for (const id of ids) { positions[id] = height; height += heights[id] || 94; }
  return { positions, height };
}

/** Cross each neighbouring row halfway; variable-height rows can still reach either end. */
export function reorderTarget(ids: readonly string[], id: string, dy: number, heights: Readonly<Record<string, number>>) {
  const from = ids.indexOf(id); if (from < 0) return -1;
  let target = from, crossed = 0;
  if (dy > 0) for (let i = from + 1; i < ids.length; i++) {
    const height = heights[ids[i]] || 94;
    if (dy >= crossed + height / 2) target = i;
    crossed += height;
  }
  else for (let i = from - 1; i >= 0; i--) {
    const height = heights[ids[i]] || 94;
    if (-dy >= crossed + height / 2) target = i;
    crossed += height;
  }
  return target;
}
