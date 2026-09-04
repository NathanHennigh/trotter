import type { ImageSourcePropType } from 'react-native';
import { destinationPhotoAssets } from '../assets/generated/destinationPhotoManifest';
import type { CountryIconKey, StampShapeKey } from '../components/trotter/stamps/PngStamp';
import { TrotterAccent, colors } from '../theme/trotterTheme';

export type BottomNavTab = 'globe' | 'trips' | 'passport' | 'dreams' | 'profile';

export type StampType = 'arched' | 'rounded-immigration' | 'circle' | 'shield' | 'horizontal-airport';

export type LandmarkKey =
  | 'goldenGate'
  | 'rockyMountains'
  | 'chichenItza'
  | 'christRedeemer'
  | 'machuPicchu'
  | 'cartagenaClockTower'
  | 'arenalVolcano'
  | 'panamaCanal'
  | 'bigBen'
  | 'eiffelTower'
  | 'sagradaFamilia'
  | 'belemTower'
  | 'colosseum'
  | 'parthenon'
  | 'brandenburgGate'
  | 'amsterdamCanalHouses'
  | 'fuji'
  | 'mountains';

export type StampData = {
  type: StampType;
  color: string;
  title: string;
  subtitle?: string;
  date?: string;
  airportCode?: string;
  footer?: string;
  landmark?: LandmarkKey;
};

export type TripSummary = {
  id: string;
  backendId?: number;
  title: string;
  country: string;
  countryCode?: string;
  city?: string;
  airportCode?: string;
  startDate: string;
  endDate: string;
  firstCountryEntryDate?: string;
  routeLabel: string;
  miles: number;
  flightCount: number;
  itineraryCount?: number;
  airlineCount: number;
  airlines?: string[];
  airports?: string[];
  segments?: TripSegmentSummary[];
  accent: TrotterAccent;
  destinationImage?: ImageSourcePropType;
  stamp: {
    shape: StampShapeKey;
    icon: CountryIconKey;
    color: string;
    country: string;
    city?: string;
    airportCode?: string;
    date: string;
    footer?: string;
  };
};

export type TripSegmentSummary = {
  id: string;
  mode: 'flight';
  depAirport: string;
  arrAirport: string;
  depTime: string;
  arrTime: string;
  airline?: string;
  flightNumber?: string;
  bookingReference?: string;
  distanceMiles?: number;
  confidence?: number;
  depPoint?: {
    code: string;
    city: string;
    lat: number;
    lon: number;
  };
  arrPoint?: {
    code: string;
    city: string;
    lat: number;
    lon: number;
  };
};

export type TravelerProfile = {
  name: string;
  homeAirport: string;
  homeAirportName: string;
  firstFlightDate: string;
  flights: number;
  countries: number;
  airports: number;
  airlines: number;
  miles: number;
  hoursInAir: number;
};

export type CountryStamp = {
  country: string;
  city: string;
  airportCode?: string;
  firstVisitDate?: string;
  visited: boolean;
  stampType: StampType;
  color: string;
  landmark?: LandmarkKey;
};

function formatStampDate(date: string) {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date.toUpperCase();

  const day = String(parsed.getDate()).padStart(2, '0');
  const month = parsed.toLocaleString('en-US', { month: 'short' }).toUpperCase();
  return `${day} ${month} ${parsed.getFullYear()}`;
}

function stampDate(firstCountryEntryDate: string | undefined, startDate: string) {
  return formatStampDate(firstCountryEntryDate ?? startDate);
}

function destinationImage(key: string): ImageSourcePropType | undefined {
  return (destinationPhotoAssets as Record<string, ImageSourcePropType | undefined>)[key];
}

export const recentTrips: TripSummary[] = [
  {
    id: 'tokyo-2025',
    title: 'Tokyo, Japan',
    country: 'Japan',
    countryCode: 'JP',
    city: 'Tokyo',
    airportCode: 'HND',
    startDate: '2025-05-12',
    endDate: '2025-05-21',
    firstCountryEntryDate: '2025-05-12',
    routeLabel: 'DFW -> HND',
    miles: 7238,
    flightCount: 3,
    airlineCount: 2,
    accent: 'red',
    destinationImage: destinationImage('tokyo'),
    stamp: {
      shape: 'roundedImmigrationWithBand',
      icon: 'japan_mount_fuji',
      color: colors.red,
      country: 'Japan',
      city: 'Tokyo',
      airportCode: 'HND',
      date: stampDate('2025-05-12', '2025-05-12'),
      footer: 'FIRST VISIT',
    },
  },
  {
    id: 'paris-2025',
    title: 'Paris, France',
    country: 'France',
    countryCode: 'FR',
    city: 'Paris',
    airportCode: 'CDG',
    startDate: '2025-04-03',
    endDate: '2025-04-07',
    firstCountryEntryDate: '2025-04-07',
    routeLabel: 'DFW -> CDG',
    miles: 4869,
    flightCount: 2,
    airlineCount: 1,
    accent: 'teal',
    destinationImage: destinationImage('paris'),
    stamp: {
      shape: 'circularCityDoubleLine',
      icon: 'france_eiffel_tower',
      color: colors.blue,
      country: 'France',
      city: 'Paris',
      airportCode: 'CDG',
      date: stampDate('2025-04-07', '2025-04-03'),
      footer: 'FIRST VISIT',
    },
  },
  {
    id: 'denver-2025',
    title: 'Denver, CO',
    country: 'United States',
    countryCode: 'US',
    city: 'Denver',
    airportCode: 'DEN',
    startDate: '2025-03-14',
    endDate: '2025-03-17',
    routeLabel: 'DFW -> DEN',
    miles: 641,
    flightCount: 1,
    airlineCount: 1,
    accent: 'mustard',
    destinationImage: destinationImage('denver'),
    stamp: {
      shape: 'shieldBadgeRounded',
      icon: 'united_states_golden_gate_bridge',
      color: colors.green,
      country: 'United States',
      city: 'Denver',
      airportCode: 'DEN',
      date: stampDate(undefined, '2025-03-14'),
      footer: 'DOMESTIC',
    },
  },
  {
    id: 'cancun-2025',
    title: 'Cancun, Mexico',
    country: 'Mexico',
    countryCode: 'MX',
    city: 'Cancun',
    airportCode: 'CUN',
    startDate: '2025-02-22',
    endDate: '2025-02-27',
    firstCountryEntryDate: '2025-02-27',
    routeLabel: 'IAH -> CUN',
    miles: 1712,
    flightCount: 2,
    airlineCount: 1,
    accent: 'teal',
    destinationImage: destinationImage('cancun'),
    stamp: {
      shape: 'archedCountryCanonical',
      icon: 'mexico_chichen_itza',
      color: colors.green,
      country: 'Mexico',
      city: 'Cancun',
      airportCode: 'CUN',
      date: stampDate('2025-02-27', '2025-02-22'),
      footer: 'FIRST VISIT',
    },
  },
  {
    id: 'barcelona-2025',
    title: 'Barcelona, Spain',
    country: 'Spain',
    countryCode: 'ES',
    city: 'Barcelona',
    airportCode: 'BCN',
    startDate: '2025-01-20',
    endDate: '2025-01-25',
    firstCountryEntryDate: '2025-01-25',
    routeLabel: 'DFW -> BCN',
    miles: 5194,
    flightCount: 2,
    airlineCount: 1,
    accent: 'blue',
    destinationImage: destinationImage('barcelona'),
    stamp: {
      shape: 'roundedImmigrationCanonical',
      icon: 'spain_sagrada_familia',
      color: '#9A5A32',
      country: 'Spain',
      city: 'Barcelona',
      airportCode: 'BCN',
      date: stampDate('2025-01-25', '2025-01-20'),
      footer: 'FIRST VISIT',
    },
  },
];

export const travelerProfile: TravelerProfile = {
  name: 'Nathan Trotter',
  homeAirport: 'DFW',
  homeAirportName: 'Dallas Fort Worth',
  firstFlightDate: '18 JUN 2013',
  flights: 143,
  countries: 8,
  airports: 42,
  airlines: 11,
  miles: 183726,
  hoursInAir: 312,
};

export const countryStamps: CountryStamp[] = [
  { country: 'Japan', city: 'Tokyo', airportCode: 'HND', firstVisitDate: '12 MAY 2025', visited: true, stampType: 'arched', color: colors.red, landmark: 'fuji' },
  { country: 'France', city: 'Paris', airportCode: 'CDG', firstVisitDate: '07 APR 2025', visited: true, stampType: 'arched', color: colors.blue, landmark: 'eiffelTower' },
  { country: 'Mexico', city: 'Cancun', airportCode: 'CUN', firstVisitDate: '27 FEB 2025', visited: true, stampType: 'circle', color: colors.green, landmark: 'chichenItza' },
  { country: 'Spain', city: 'Barcelona', airportCode: 'BCN', firstVisitDate: '25 JAN 2025', visited: true, stampType: 'rounded-immigration', color: '#9A5A32', landmark: 'sagradaFamilia' },
  { country: 'Italy', city: 'Rome', airportCode: 'FCO', visited: false, stampType: 'arched', color: colors.mutedInk, landmark: 'colosseum' },
  { country: 'United Kingdom', city: 'London', airportCode: 'LHR', visited: false, stampType: 'circle', color: colors.mutedInk, landmark: 'bigBen' },
  { country: 'Germany', city: 'Berlin', airportCode: 'BER', visited: false, stampType: 'shield', color: colors.mutedInk, landmark: 'brandenburgGate' },
  { country: 'Greece', city: 'Athens', airportCode: 'ATH', visited: false, stampType: 'horizontal-airport', color: colors.mutedInk, landmark: 'parthenon' },
];
