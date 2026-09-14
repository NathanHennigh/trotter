import type { StampShapeKey } from './PngStamp';

export const NATIVE_STAMP_SHAPES = [
  'roundedImmigrationWithBand',
  'circularCityDoubleLine',
  'archedCountryCanonical',
  'shieldBadgeRounded',
  'roundedImmigrationCanonical',
] as const satisfies readonly StampShapeKey[];

export const NATIVE_STAMP_COLORS = ['#B6543F', '#2F5E9E', '#52745A', '#9A5A32', '#C79A43'] as const;

/** A country's stamp must not change when another trip is added or reordered. */
export function stampIdentity(country: string, countryCode?: string): { shape: StampShapeKey; color: string } {
  const name = country.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').trim().toUpperCase().replace(/\s+/g, ' ');
  const code = countryCode?.trim().toUpperCase();
  if (code === 'US' || ['UNITED STATES', 'UNITED STATES OF AMERICA', 'USA'].includes(name)) {
    return { shape: 'shieldBadgeRounded', color: '#52745A' };
  }
  const key = name === 'SOMALILAND' || code === 'X-SOMALILAND'
    ? 'X-SOMALILAND' : code && /^[A-Z]{2}$/.test(code) ? code : name;
  // FNV-1a is stable across native and web runtimes. Hash only country identity,
  // never list position, arrival date, airport, or the number of recorded trips.
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash = Math.imul(hash ^ key.charCodeAt(index), 16777619) >>> 0;
  }
  const index = hash % NATIVE_STAMP_SHAPES.length;
  return { shape: NATIVE_STAMP_SHAPES[index], color: NATIVE_STAMP_COLORS[index] };
}
