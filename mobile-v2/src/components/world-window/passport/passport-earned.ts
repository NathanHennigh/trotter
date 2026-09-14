export type ArrivalBaseline = { codes: string[]; syncedAt?: string };
/** Loading an existing archive or changing a filter must never award old stamps. */
export function earnedCountries(
  previous: ArrivalBaseline | null,
  current: ArrivalBaseline,
) {
  if (!previous || !current.syncedAt || previous.syncedAt === current.syncedAt)
    return [];
  const known = new Set(previous.codes);
  return current.codes.filter((code) => !known.has(code));
}
