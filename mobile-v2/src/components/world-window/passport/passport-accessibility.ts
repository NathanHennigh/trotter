import type { BookPayload } from './passport-payload';
import type { PaperPage } from './passport-paper';

function dateText(value: string) {
  const date = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }) : value;
}

/** Text equivalent of the visible non-stamp pages; stamp controls supply theirs. */
export function passportPageDescription(page: PaperPage, payload: BookPayload) {
  if (page.kind === 'identity') {
    const airport = [payload.homeAirport, payload.homeAirportName, payload.homeAirportCountry].filter(Boolean).join(', ');
    return { label: 'Traveler identity', lines: [
      payload.name && `Name: ${payload.name}`,
      airport && `${payload.airportLabel}: ${airport}`,
      payload.firstFlightDate && `Since: ${payload.firstFlightDate.slice(0, 4)}`,
      `Countries: ${payload.countries.toLocaleString()}`,
    ].filter((line): line is string => Boolean(line)) };
  }
  if (page.kind === 'record') return { label: 'Travel record', lines: [
    `Flights: ${payload.flights.toLocaleString()}`,
    `Miles flown: ${payload.miles.toLocaleString()}`,
    ...(payload.register ?? []).map(entry => `${entry.label}: ${entry.value}${entry.detail ? ', ' + entry.detail : ''}`),
    !payload.register && payload.firstFlightDate && `First flight: ${dateText(payload.firstFlightDate)}`,
  ].filter((line): line is string => Boolean(line)) };
  return undefined;
}
