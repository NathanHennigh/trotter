// Application travel identity, deliberately distinct from ISO country codes.
export const SOMALILAND_TRAVEL_KEY = 'X-SOMALILAND';
export const SOMALILAND_ICON_KEY = 'somaliland_laas_geel';
const SOMALILAND_AIRPORTS = new Set(['HGA', 'BBO']);

export function isSomalilandAirport(code?: string) {
  return SOMALILAND_AIRPORTS.has(code?.trim().toUpperCase() ?? '');
}

export function travelCountry(country: string, countryCode?: string, airportCode?: string) {
  const somaliland = country.trim().toLowerCase() === 'somaliland'
    || countryCode === SOMALILAND_TRAVEL_KEY || isSomalilandAirport(airportCode);
  if (somaliland) return { country: 'Somaliland', countryCode: undefined, travelCountryKey: SOMALILAND_TRAVEL_KEY };
  return { country, countryCode, travelCountryKey: countryCode?.toUpperCase() ?? country.trim().toUpperCase() };
}
