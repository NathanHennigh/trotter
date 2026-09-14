import type { TripSummary } from '../../../data/trotterMock';
import { buildCountryArrivals } from '../../../utils/countryArrivals';
import { travelCountry, isSomalilandAirport } from '../../../utils/travelCountry';
import { stampIdentity } from '../../trotter/stamps/stampIdentity';
import { passportArtwork } from './passport-artwork';

export function countryArtwork(country: string, preferred?: string) {
  if (preferred && preferred in passportArtwork) return preferred;
  // The approved/native Nicaragua impression deliberately uses the existing
  // Arenal volcano drawing; the asset manifest has no Nicaragua-prefixed file.
  if (country.trim().toLowerCase() === 'nicaragua') return 'costa_rica_arenal_volcano';
  const prefix = country.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') + '_';
  return Object.keys(passportArtwork).find(key => key.startsWith(prefix)) ?? '';
}

/** Connections count as visits. Keep this adapter additive: original destination
 * records and manually corrected first-entry fields always remain available. */
export function buildPassportArrivals(trips: TripSummary[]) {
  const visits = trips.flatMap(trip => {
    const byCountry = new Map<string, TripSummary>();
    const metadata = (trip.segments ?? []).find(segment => (segment.arrPoint?.country ?? segment.arrCountry)?.trim().toLowerCase() === trip.country.trim().toLowerCase());
    const base = travelCountry(trip.country, trip.countryCode ?? metadata?.arrPoint?.countryCode ?? metadata?.arrCountryCode, trip.airportCode);
    byCountry.set(base.travelCountryKey, { ...trip, ...base, stamp: { ...trip.stamp, country: base.country, city: undefined, icon: countryArtwork(base.country, trip.stamp.icon) } });
    const ordered = [...(trip.segments ?? [])].filter(s => Number.isFinite(Date.parse(s.arrTime))).sort((a, b) => Date.parse(a.arrTime) - Date.parse(b.arrTime));
    for (const segment of ordered) {
      const point = segment.arrPoint, arrivalCountry = point?.country ?? segment.arrCountry, arrivalCode = point?.countryCode ?? segment.arrCountryCode;
      if (!arrivalCountry && !isSomalilandAirport(segment.arrAirport)) continue;
      const identity = travelCountry(arrivalCountry ?? 'Somaliland', arrivalCode, segment.arrAirport);
      const known = byCountry.get(identity.travelCountryKey), date = segment.arrTime.slice(0, 10);
      if (known) {
        const previousDate = known.firstCountryEntryDate ?? known.stamp.date ?? known.startDate;
        const parsedDate = Date.parse(previousDate), previousISO = /^\d{4}-\d{2}-\d{2}/.exec(previousDate)?.[0] ?? (Number.isFinite(parsedDate) ? new Date(parsedDate).toISOString().slice(0, 10) : known.startDate);
        if (date < previousISO || date === previousISO && !known.firstCountryEntryAirport) byCountry.set(identity.travelCountryKey, { ...known, firstCountryEntryAirport: segment.arrAirport, firstCountryEntryDate: date });
        continue;
      }
      byCountry.set(identity.travelCountryKey, { ...trip, ...identity, id: `${trip.id}:arrival:${identity.travelCountryKey}`, airportCode: segment.arrAirport,
        firstCountryEntryAirport: segment.arrAirport, firstCountryEntryDate: date,
        stamp: { ...stampIdentity(identity.country, identity.countryCode ?? identity.travelCountryKey), country: identity.country, icon: countryArtwork(identity.country), airportCode: segment.arrAirport, date, city: undefined } });
    }
    // A virtual country visit carries only its own arrival legs. This prevents
    // the preserved Somaliland adapter from re-adding HGA for every connection.
    return [...byCountry.values()].map(visit => ({ ...visit, segments: visit.segments?.filter(segment => {
      if (segment.arrAirport === (visit.firstCountryEntryAirport ?? visit.stamp.airportCode ?? visit.airportCode)) return true;
      const point = segment.arrPoint, arrivalCountry = point?.country ?? segment.arrCountry;
      if (!arrivalCountry && !isSomalilandAirport(segment.arrAirport)) return false;
      return travelCountry(arrivalCountry ?? 'Somaliland', point?.countryCode ?? segment.arrCountryCode, segment.arrAirport).travelCountryKey === visit.travelCountryKey;
    }) }));
  });
  return buildCountryArrivals(visits);
}
