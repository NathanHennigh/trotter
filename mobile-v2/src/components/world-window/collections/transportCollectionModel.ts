import { airlineCatalog, airportCatalog, countryCatalog } from '../../../data/collections/catalogs';
import type { AirlineRecord, AirportRecord, PassportArchive } from '../passport/passport-model';
import { airlineName } from '../AirlineLogo';
import { resolveCatalogKey } from './catalogProgress';

export type TransportKind = 'airports' | 'airlines';
export type TransportEntry = {
  key: string; name: string; city?: string; country?: string; countryKey?: string;
  countryName?: string; region?: string; lat?: number; lon?: number;
  record?: AirportRecord | AirlineRecord; lifetimeRecord?: AirportRecord | AirlineRecord;
  inCatalog: boolean; firstVisit?: string;
};
export const transportCatalog = (kind: TransportKind) => kind === 'airports' ? airportCatalog : airlineCatalog;
const countries = new Map(countryCatalog.entries.map(entry => [entry.key, entry]));
const normalizedCode = (value?: string) => value?.trim().toUpperCase() ?? '';

export function transportFirstVisit(record: AirportRecord | AirlineRecord, kind: TransportKind) {
  const code = normalizedCode(record.code);
  return record.trips.flatMap(trip => (trip.segments ?? []).flatMap(segment => kind === 'airports'
    ? [normalizedCode(segment.depAirport) === code ? segment.depTime : '', normalizedCode(segment.arrAirport) === code ? segment.arrTime : '']
    : normalizedCode(segment.airline) === code ? [segment.depTime] : []))
    .filter(date => date && Number.isFinite(Date.parse(date))).sort((a, b) => Date.parse(a) - Date.parse(b))[0];
}

/** Keep historical records visible without counting them against another directory. */
export function transportEntries(kind: TransportKind, archive: PassportArchive, lifetime = archive): TransportEntry[] {
  const scoped = new Map((kind === 'airports' ? archive.airports : archive.airlines).map(record => [record.code.trim().toUpperCase(), record]));
  const earned = new Map((kind === 'airports' ? lifetime.airports : lifetime.airlines).map(record => [record.code.trim().toUpperCase(), record]));
  // A partial lifetime snapshot must not hide an observed record in the selected scope.
  for (const [key, record] of scoped) if (!earned.has(key)) earned.set(key, record);
  const source: ReadonlyArray<Omit<TransportEntry, 'inCatalog'>> = transportCatalog(kind).entries;
  const result = new Map<string, TransportEntry>();
  for (const entry of source) result.set(entry.key, { ...entry, inCatalog: true });
  for (const [key, record] of earned) {
    const entry = result.get(key), country = 'country' in record ? record.country : undefined;
    const countryEntry = countries.get(resolveCatalogKey(countryCatalog, entry?.countryKey ?? entry?.country ?? entry?.countryName ?? country) ?? '');
    const carrier = airlineName(key);
    result.set(key, {
      ...entry, key, inCatalog: Boolean(entry),
      name: kind === 'airlines' ? (carrier !== key ? carrier : entry?.name ?? key) : entry?.name ?? ('city' in record ? record.city : '') ?? key,
      city: entry?.city || ('city' in record ? record.city : undefined),
      countryKey: entry?.countryKey ?? countryEntry?.key,
      countryName: entry?.countryName ?? countryEntry?.name ?? country,
      region: entry?.region ?? countryEntry?.region,
      record: scoped.get(key), lifetimeRecord: record,
      firstVisit: transportFirstVisit(record, kind),
    });
  }
  for (const entry of result.values()) {
    const country = countries.get(entry.countryKey ?? entry.country ?? '');
    entry.countryKey ??= country?.key;
    entry.countryName ??= country?.name ?? entry.country;
    entry.region ??= country?.region;
    entry.record ??= scoped.get(entry.key);
  }
  return [...result.values()];
}

export function filterTransportEntries(entries: TransportEntry[], mode: 'visited' | 'all', region: string, query: string) {
  const search = query.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  return entries.filter(entry => (mode === 'all' || entry.record) && (!region || entry.region === region)
    && `${entry.key} ${entry.name} ${entry.city ?? ''} ${entry.countryName ?? ''}`.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().includes(search))
    .sort((a, b) => mode === 'visited'
      ? (b.record?.flights ?? 0) - (a.record?.flights ?? 0) || a.key.localeCompare(b.key)
      : (a.city || a.name).localeCompare(b.city || b.name) || a.key.localeCompare(b.key));
}
