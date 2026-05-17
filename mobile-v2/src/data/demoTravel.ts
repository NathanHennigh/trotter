import localFlightFixtureJson from './localFlightFixture.json';

export interface RoutePoint {
  code: string;
  city: string;
  lat: number;
  lon: number;
}

export interface DemoRoute {
  id: string;
  from: RoutePoint;
  to: RoutePoint;
  color?: string;
}

export type FlightRoute = DemoRoute & {
  segmentId?: number;
  tripId?: number;
  tripTitle?: string | null;
  depTime?: string | null;
  arrTime?: string | null;
  airline?: string | null;
  flightNumber?: string | null;
  distanceKm?: number | null;
};

export interface DemoTrip {
  id: string;
  title: string;
  countryFlag: string;
  dates: string;
  route: string;
  miles: string;
  flights: string;
  airlines: string;
  accent: string;
  stamp: string;
  imageLabel: string;
}

interface LocalFlightFixture {
  routes: FlightRoute[];
  airports: RoutePoint[];
}

const localFlightFixture = localFlightFixtureJson as LocalFlightFixture;

export const airports: Record<string, RoutePoint> = {
  DFW: { code: 'DFW', city: 'Dallas/Fort Worth', lat: 32.8998, lon: -97.0403 },
  HND: { code: 'HND', city: 'Tokyo', lat: 35.5494, lon: 139.7798 },
  CDG: { code: 'CDG', city: 'Paris', lat: 49.0097, lon: 2.5479 },
  DEN: { code: 'DEN', city: 'Denver', lat: 39.8561, lon: -104.6737 },
  LHR: { code: 'LHR', city: 'London', lat: 51.47, lon: -0.4543 },
  FCO: { code: 'FCO', city: 'Rome', lat: 41.8003, lon: 12.2389 },
  SIN: { code: 'SIN', city: 'Singapore', lat: 1.3644, lon: 103.9915 },
  NRT: { code: 'NRT', city: 'Tokyo Narita', lat: 35.772, lon: 140.3929 },
  EZE: { code: 'EZE', city: 'Buenos Aires', lat: -34.8222, lon: -58.5358 },
  GRU: { code: 'GRU', city: 'Sao Paulo', lat: -23.4356, lon: -46.4731 },
  KEF: { code: 'KEF', city: 'Reykjavik', lat: 63.985, lon: -22.6056 },
  AMS: { code: 'AMS', city: 'Amsterdam', lat: 52.3105, lon: 4.7683 },
  JFK: { code: 'JFK', city: 'New York', lat: 40.6413, lon: -73.7781 },
  MEX: { code: 'MEX', city: 'Mexico City', lat: 19.4363, lon: -99.0721 },
};

export const demoRoutes: DemoRoute[] = [
  { id: 'dfw-hnd', from: airports.DFW, to: airports.HND },
  { id: 'dfw-cdg', from: airports.DFW, to: airports.CDG },
  { id: 'dfw-den', from: airports.DFW, to: airports.DEN },
  { id: 'dfw-lhr', from: airports.DFW, to: airports.LHR },
  { id: 'dfw-fco', from: airports.DFW, to: airports.FCO },
  { id: 'dfw-sin', from: airports.DFW, to: airports.SIN },
  { id: 'sin-nrt', from: airports.SIN, to: airports.NRT },
  { id: 'dfw-eze', from: airports.DFW, to: airports.EZE },
  { id: 'dfw-gru', from: airports.DFW, to: airports.GRU },
  { id: 'dfw-kef', from: airports.DFW, to: airports.KEF },
  { id: 'jfk-ams', from: airports.JFK, to: airports.AMS },
  { id: 'mex-dfw', from: airports.MEX, to: airports.DFW },
];

export const cityLights: RoutePoint[] = [
  airports.DFW, airports.HND, airports.CDG, airports.DEN, airports.LHR,
  airports.FCO, airports.SIN, airports.NRT, airports.EZE, airports.GRU,
  airports.KEF, airports.AMS, airports.JFK, airports.MEX,
  { code: 'LAX', city: 'Los Angeles', lat: 33.9416, lon: -118.4085 },
  { code: 'SFO', city: 'San Francisco', lat: 37.6213, lon: -122.379 },
  { code: 'SEA', city: 'Seattle', lat: 47.4502, lon: -122.3088 },
  { code: 'MIA', city: 'Miami', lat: 25.7959, lon: -80.287 },
  { code: 'ORD', city: 'Chicago', lat: 41.9742, lon: -87.9073 },
  { code: 'MAD', city: 'Madrid', lat: 40.4983, lon: -3.5676 },
  { code: 'BCN', city: 'Barcelona', lat: 41.2974, lon: 2.0833 },
  { code: 'IST', city: 'Istanbul', lat: 41.2753, lon: 28.7519 },
  { code: 'CAI', city: 'Cairo', lat: 30.112, lon: 31.4001 },
  { code: 'CPT', city: 'Cape Town', lat: -33.9694, lon: 18.5972 },
  { code: 'BOG', city: 'Bogota', lat: 4.7016, lon: -74.1469 },
  { code: 'LIM', city: 'Lima', lat: -12.0219, lon: -77.1143 },
];

export const flightRoutes: FlightRoute[] = localFlightFixture.routes.length > 0
  ? localFlightFixture.routes
  : demoRoutes;

export const flightMapPoints: RoutePoint[] = localFlightFixture.airports.length > 0
  ? localFlightFixture.airports
  : cityLights;

export const recentTrips: DemoTrip[] = [
  {
    id: 'tokyo',
    title: 'Tokyo, Japan',
    countryFlag: 'JP',
    dates: 'MAY 12 - MAY 21',
    route: 'DFW -> HND',
    miles: '7,238 mi',
    flights: '3 flights',
    airlines: '2 airlines',
    accent: '#B24A35',
    stamp: 'JAPAN / NARITA',
    imageLabel: 'TOKYO PHOTO',
  },
  {
    id: 'paris',
    title: 'Paris, France',
    countryFlag: 'FR',
    dates: 'APR 3 - APR 7',
    route: 'DFW -> CDG',
    miles: '4,869 mi',
    flights: '2 flights',
    airlines: '1 airline',
    accent: '#47726C',
    stamp: 'PARIS / FRANCE',
    imageLabel: 'PARIS PHOTO',
  },
  {
    id: 'denver',
    title: 'Denver, CO',
    countryFlag: 'US',
    dates: 'MAR 14 - MAR 17',
    route: 'DFW -> DEN',
    miles: '641 mi',
    flights: '1 flight',
    airlines: '1 airline',
    accent: '#D69A3A',
    stamp: 'DENVER / COLORADO',
    imageLabel: 'DENVER PHOTO',
  },
];
