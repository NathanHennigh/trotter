const AIRLINE_NAMES: Record<string, string> = {
  AA: 'American Airlines',
  AC: 'Air Canada',
  AF: 'Air France',
  AS: 'Alaska Airlines',
  BA: 'British Airways',
  B6: 'JetBlue',
  DL: 'Delta Air Lines',
  EK: 'Emirates',
  ET: 'Ethiopian Airlines',
  F9: 'Frontier Airlines',
  G4: 'Allegiant Air',
  IB: 'Iberia',
  KL: 'KLM',
  LH: 'Lufthansa',
  NK: 'Spirit Airlines',
  QF: 'Qantas',
  QR: 'Qatar Airways',
  SQ: 'Singapore Airlines',
  SY: 'Sun Country Airlines',
  TK: 'Turkish Airlines',
  UA: 'United Airlines',
  VS: 'Virgin Atlantic',
  WN: 'Southwest Airlines',
  WS: 'WestJet',
};

export function airlineDisplayName(airline?: string) {
  const value = airline?.trim();
  if (!value) return undefined;
  return AIRLINE_NAMES[value.toUpperCase()] ?? value;
}

export function formatAirlineNames(airlines: string[]) {
  return Array.from(new Set(airlines.map(airlineDisplayName).filter(Boolean))).join(' / ');
}

export function formatAirlineFlight(airline?: string, flightNumber?: string) {
  const name = airlineDisplayName(airline);
  const number = flightNumber?.trim().replace(/^([A-Z0-9]{2})(\d)/i, '$1 $2');
  return [name, number].filter(Boolean).join(' · ') || 'Airline pending';
}
