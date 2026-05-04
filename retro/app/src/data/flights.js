export const FLIGHTS = [
  { id: 1, from: 'JFK', to: 'LHR', date: '14 MAR 2025', dur: '7H 05M', mi: 3459, carrier: 'BA 178' },
  { id: 2, from: 'LHR', to: 'DXB', date: '22 MAR 2025', dur: '6H 50M', mi: 3406, carrier: 'EK 004' },
  { id: 3, from: 'DXB', to: 'SIN', date: '01 APR 2025', dur: '7H 00M', mi: 3646, carrier: 'SQ 497' },
  { id: 4, from: 'SIN', to: 'NRT', date: '10 APR 2025', dur: '7H 20M', mi: 3328, carrier: 'NH 842' },
  { id: 5, from: 'NRT', to: 'LAX', date: '18 APR 2025', dur: '9H 30M', mi: 5478, carrier: 'UA 837' },
  { id: 6, from: 'LAX', to: 'JFK', date: '22 APR 2025', dur: '5H 15M', mi: 2475, carrier: 'AA 006' },
];

export const TOTAL_MI = FLIGHTS.reduce((s, f) => s + f.mi, 0);

// [longitude, latitude] for d3-geo
export const CITY_GEO = {
  JFK: [-73.8, 40.6],
  LHR: [-0.45, 51.5],
  DXB: [55.4, 25.2],
  SIN: [103.8, 1.4],
  NRT: [140.4, 35.8],
  LAX: [-118.4, 33.9],
};
