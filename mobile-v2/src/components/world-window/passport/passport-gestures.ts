/** Decide intent before taking a touch away from the surrounding scroll view. */
export type PaperGestureIntent = "pending" | "turn" | "scroll";
export function paperGestureIntent(dx: number, dy: number): PaperGestureIntent {
  if (!Number.isFinite(dx) || !Number.isFinite(dy) || Math.hypot(dx, dy) < 7)
    return "pending";
  return Math.abs(dy) > Math.abs(dx) * 1.15 ? "scroll" : "turn";
}
export function selectedActivityIndex(
  years: readonly { year: number }[],
  selectedYear: number | null,
) {
  const selected = years.findIndex((item) => item.year === selectedYear);
  return selected >= 0 ? selected : Math.max(0, years.length - 1);
}
