import countries from './countries.json';
import airports from './airports.json';
import airlines from './airlines.json';

export type CatalogEntry = {
  key: string;
  name: string;
  region: string;
  aliases?: readonly string[];
  country?: string;
  countryName?: string;
  city?: string;
  lat?: number;
  lon?: number;
  icao?: string;
  sourceId?: string;
  sourceUrl?: string;
  sharedCode?: boolean;
  operators?: readonly { key: string; name: string; countries: readonly string[]; icao: readonly string[]; sourceUrl: string }[];
};
export type CollectionCatalog = {
  metadata: {
    version: string;
    snapshotDate: string;
    label: string;
    scope: string;
    notes: readonly string[];
    total: number;
    sources: readonly {name: string; url: string; license: string; sha256: string; retrievedAt: string; revision?: string}[];
  };
  entries: readonly CatalogEntry[];
};
export const countryCatalog: CollectionCatalog = countries;
export const airportCatalog: CollectionCatalog = airports;
export const airlineCatalog: CollectionCatalog = airlines;
