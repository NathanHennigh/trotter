import zoneData from './plannerTimeZones.json';

// IANA tzdb zone1970.tab and iso3166.tab. Includes countries that share a clock.
export type TripTimeZone = { zone: string; codes: string[]; countries: string[]; region: string };
export const tripTimeZones: TripTimeZone[] = zoneData;
const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const aliases: Record<string, string> = { usa: 'US', us: 'US', america: 'US', uk: 'GB', britain: 'GB', turkey: 'TR', turkiye: 'TR', uae: 'AE', 'south korea': 'KR', 'north korea': 'KP', russia: 'RU', vietnam: 'VN', laos: 'LA', taiwan: 'TW' };
export function timeZoneCity(zone: string) { return zone.split('/').at(-1)!.replace(/_/g, ' '); }
export function matchingTimeZones(query: string): TripTimeZone[] {
  const needle = normalize(query), code = aliases[needle];
  return tripTimeZones.filter(row => !needle || (code ? row.codes.includes(code) : [row.zone.replace(/_/g, ' '), ...row.codes, ...row.countries, row.region].some(value => normalize(value).includes(needle))));
}
export function suggestedTimeZone(destination: string): string | undefined {
  const needle = normalize(destination);
  if (!needle) return;
  const city = tripTimeZones.filter(row => normalize(timeZoneCity(row.zone)) === needle);
  if (city.length === 1) return city[0].zone;
  const code = aliases[needle];
  const exact = tripTimeZones.filter(row => code ? row.codes.includes(code) : [...row.codes, ...row.countries].some(value => normalize(value) === needle));
  return exact.length === 1 ? exact[0].zone : undefined;
}
